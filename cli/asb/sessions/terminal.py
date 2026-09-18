"""cli/asb/sessions/terminal.py — terminal persistente de sessao via tmux.

`TmuxTerminal` fala com o tmux DENTRO do workspace, sempre por SSH
(`ConnectionInfo.ssh_argv`), nunca por um shell local: cada comando tmux e
uma tupla de argumentos que `ssh_argv` junta com `shlex.join`. O tmux e a
fonte da verdade sobre a sessao; este modulo nao guarda estado.

Comportamentos do tmux 3.3a da imagem de que o parser depende (pinados em
container descartavel, ver relatorio da Tarefa 7):

- argumento terminado em ";" e separador de comando do tmux; "\\;" final
  vira ";" literal — por isso `_tmux_arg` escapa esse caso;
- `new-session -c` expande formatos (`#S`...); "##" e "#" literal;
- comando de UM elemento roda via `sh -c`; com dois ou mais, via exec direto;
- sessao ausente: "can't find session: <nome>"; socket existe mas nenhum
  servidor escuta: "no server running on <socket>" — ambos com exit 1 e
  ambos provam ausencia;
- socket APAGADO com o servidor vivo: "error connecting to <socket> (No
  such file or directory)", exit 1 — NAO prova ausencia (qualquer coisa no
  workspace pode apagar o arquivo), entao e incerteza;
- `list-panes -t =<nome>:` sem `-s` so lista a janela CORRENTE; com `-s`
  lista todas. `-s -t =<nome>` SEM ":" casa por prefixo; por isso sempre
  `-s -t =<nome>:`;
- com `remain-on-exit on`, `#{pane_dead}` e "1" e `#{pane_dead_status}` e o
  exit status do comando (vazio se morto por sinal).
"""
from __future__ import annotations

import re
import shlex
import subprocess
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

from asb.runtime.connection import ConnectionInfo
from asb.sessions.model import TerminalId

# Tempo total por chamada; o SSH ja desiste de conectar em 10 s
# (`ConnectTimeout=10`), isto cobre um servidor que conectou e travou.
_TIMEOUT_SECONDS = 30.0

_PANE_FORMAT = "#{pane_dead} #{pane_dead_status}"
_PANE_LINE = re.compile(r"^([01]) ([0-9]*)$")
_NO_SERVER = re.compile(r"^no server running on \S+$")


class Liveness(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


class TerminalError(RuntimeError):
    """Falha ao iniciar ou encerrar um terminal tmux."""


def _tmux_arg(value: str) -> str:
    """Protege um argumento do separador ";" do proprio tmux."""
    return value[:-1] + "\\;" if value.endswith(";") else value


class TmuxTerminal:
    def __init__(self, connection: ConnectionInfo,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                 ) -> None:
        self._connection = connection
        self._run = run

    def start(self, terminal_id: str, cwd: str | Path,
              command: Sequence[str]) -> None:
        """Cria a sessao desanexada e liga `remain-on-exit` SO nela, na
        mesma invocacao do tmux (`;`), para que um comando que termina na
        hora ainda deixe o pane morto com seu exit status.

        O `TerminalError` e o mesmo para falha definitiva e para falha
        ambigua: em timeout, falha ao executar o `ssh` ou exit 255 do SSH
        a sessao PODE ter sido criada. Quem chama deve sondar com `probe`
        antes de tentar de novo."""
        name = TerminalId(terminal_id)
        cwd = str(cwd)
        if not cwd or not PurePosixPath(cwd).is_absolute():
            raise ValueError(f"cwd deve ser absoluto: {cwd!r}")
        command = tuple(command)
        if not command or not all(isinstance(a, str) and a for a in command):
            raise ValueError(f"comando invalido: {command!r}")
        if len(command) == 1:
            # Um elemento so: o tmux o entrega a `sh -c`.
            command = (shlex.quote(command[0]),)
        remote = (
            "tmux", "new-session", "-d", "-s", name,
            "-c", _tmux_arg(cwd.replace("#", "##")),
            "--", *(_tmux_arg(a) for a in command),
            ";", "set-option", "-t", f"={name}:", "remain-on-exit", "on",
        )
        result = self._call(remote)
        if result is None or result.returncode != 0:
            raise TerminalError(f"falha ao iniciar o terminal {name}: "
                                f"{_detail(result)}")

    def probe(self, terminal_id: str) -> Liveness:
        """ALIVE: sessao existe e pane vivo. DEAD: tmux diz que a sessao
        nao existe ou que o pane morreu. Todo o resto e UNKNOWN."""
        name = TerminalId(terminal_id)
        result = self._pane_state(name)
        if result is None:
            return Liveness.UNKNOWN
        if result.returncode == 0:
            match = _PANE_LINE.fullmatch(result.stdout.rstrip("\n"))
            if match is None:
                return Liveness.UNKNOWN
            return Liveness.DEAD if match.group(1) == "1" else Liveness.ALIVE
        if _session_missing(result, name):
            return Liveness.DEAD
        return Liveness.UNKNOWN

    def capture_exit_status(self, terminal_id: str) -> int | None:
        """Exit status do pane morto, como o tmux o reporta; `None` se a
        sessao sumiu, o pane vive ou a saida nao e classificavel."""
        name = TerminalId(terminal_id)
        result = self._pane_state(name)
        if result is None or result.returncode != 0:
            return None
        match = _PANE_LINE.fullmatch(result.stdout.rstrip("\n"))
        if match is None or match.group(1) != "1" or not match.group(2):
            return None
        return int(match.group(2))

    def stop(self, terminal_id: str) -> None:
        """Mata a sessao. Sessao ja ausente nao e erro."""
        name = TerminalId(terminal_id)
        result = self._call(("tmux", "kill-session", "-t", f"={name}"))
        if result is not None and (result.returncode == 0
                                   or _session_missing(result, name)):
            return
        raise TerminalError(f"falha ao encerrar o terminal {name}: "
                            f"{_detail(result)}")

    def attach_argv(self, terminal_id: str) -> list[str]:
        """argv interativo (com TTY) que anexa exatamente a esta sessao."""
        name = TerminalId(terminal_id)
        return self._connection.ssh_argv(
            ("tmux", "attach-session", "-t", f"={name}"), interactive=True)

    def _pane_state(self, name: TerminalId):
        # `-s`: todos os panes da sessao; mais de um pane vira mais de
        # uma linha e, portanto, UNKNOWN/None — nunca a janela errada.
        return self._call(("tmux", "list-panes", "-s", "-t", f"={name}:",
                           "-F", _PANE_FORMAT))

    def _call(self, remote: tuple[str, ...]):
        """Roda `remote` via SSH nao interativo; `None` em timeout ou falha
        ao executar o `ssh` local (sempre incerteza, nunca ausencia)."""
        argv = self._connection.ssh_argv(remote, interactive=False)
        try:
            return self._run(argv, stdin=subprocess.DEVNULL,
                             capture_output=True, text=True,
                             timeout=_TIMEOUT_SECONDS, check=False,
                             shell=False)
        except (subprocess.TimeoutExpired, OSError):
            return None


def _session_missing(result: subprocess.CompletedProcess,
                     name: TerminalId) -> bool:
    """So o exit 1 do tmux com mensagem pinada prova ausencia; o 255 do
    SSH ou qualquer outra saida nao prova nada."""
    if result.returncode != 1:
        return False
    for line in (result.stderr or "").splitlines():
        line = line.strip()
        if line == f"can't find session: {name}":
            return True
        if _NO_SERVER.fullmatch(line):
            return True
    return False


def _detail(result: subprocess.CompletedProcess | None) -> str:
    if result is None:
        return "ssh expirou ou nao executou"
    lines = (result.stderr or "").strip().splitlines()
    return f"exit {result.returncode}" + (f": {lines[-1]}" if lines else "")
