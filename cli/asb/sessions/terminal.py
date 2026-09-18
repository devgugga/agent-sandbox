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
- com `remain-on-exit on`, `#{pane_dead}` e "1" e `#{pane_dead_status}` e o
  exit status do comando (vazio se morto por sinal).

Uma sessao e achada pela TAG, nao pelo nome (fix wave 2, pinado no tmux
3.3a da imagem num container descartavel com socket `-L` privado): o
operador (`C-b $`) ou o proprio agente podem renomea-la, e um nome que nao
casa mais lia DEAD e abria um SEGUNDO processo na mesma conversa. `start`
grava a opcao de usuario `@asb_session <nome>` na mesma chamada que liga
`remain-on-exit`. `probe`, `capture_exit_status`, `stop` e `attach_argv`
usam `list-panes -a -f <filtro>` com o filtro "tag == nome OU nome ==
nome" (sessao antiga sem tag) e a saida `#{session_id} #{pane_dead}
#{pane_dead_status}`; o `session_id` ($N) vira o alvo de `kill-session` e
`attach-session`. O que o tmux reporta:

- filtro sem casamento com o servidor vivo: exit 0, saida vazia — o tmux
  listou TODAS as sessoes e nenhuma e esta: prova ausencia;
- "no server running on <socket>", exit 1: prova ausencia;
- "error connecting to <socket> (No such file or directory)", exit 1 — o
  socket foi apagado com o servidor vivo, ou nunca existiu: incerteza;
- duas sessoes distintas casando (uma tag forjada, ou uma antiga com o
  nome e outra renomeada com a tag): incerteza, nunca escolhemos uma;
- alvo `$N` que sumiu entre a busca e o kill: "can't find session: $N".
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

_TAG = "@asb_session"
_PANE_FORMAT = "#{session_id} #{pane_dead} #{pane_dead_status}"
_PANE_LINE = re.compile(r"^(\$[0-9]+) ([01]) ([0-9]*)$", re.ASCII)
_NO_SERVER = re.compile(r"^no server running on \S+$")


def _filter(name: TerminalId) -> str:
    """Formato de filtro do tmux: a tag OU o nome exato. `TerminalId` so
    tem `[a-z0-9_-]`, entao nada no nome e sintaxe de formato."""
    return (f"#{{||:#{{==:#{{{_TAG}}},{name}}},"
            f"#{{==:#{{session_name}},{name}}}}}")


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
            ";", "set-option", "-t", f"={name}:", _TAG, name,
        )
        result = self._call(remote)
        if result is None or result.returncode != 0:
            raise TerminalError(f"falha ao iniciar o terminal {name}: "
                                f"{_detail(result)}")

    def probe(self, terminal_id: str) -> Liveness:
        """ALIVE: a sessao (pela tag ou pelo nome) existe e seu pane vive.
        DEAD: o tmux prova que nenhuma sessao e esta, ou o pane morreu.
        Todo o resto e UNKNOWN."""
        found = self._locate(TerminalId(terminal_id))
        if found is _ABSENT:
            return Liveness.DEAD
        if found is None or len(found[1]) != 1:
            # Mais de um pane: nao sabemos qual e o agente.
            return Liveness.UNKNOWN
        dead, _status = found[1][0]
        return Liveness.DEAD if dead else Liveness.ALIVE

    def capture_exit_status(self, terminal_id: str) -> int | None:
        """Exit status do pane morto, como o tmux o reporta; `None` se a
        sessao sumiu, o pane vive ou a saida nao e classificavel."""
        found = self._locate(TerminalId(terminal_id))
        if found is _ABSENT or found is None or len(found[1]) != 1:
            return None
        dead, status = found[1][0]
        if not dead or not status:
            return None
        return int(status)

    def stop(self, terminal_id: str) -> None:
        """Mata a sessao achada pela tag ou pelo nome. Sessao ja ausente
        nao e erro; uma busca incerta levanta sem matar nada."""
        name = TerminalId(terminal_id)
        found = self._locate(name)
        if found is _ABSENT:
            return
        if found is None:
            raise TerminalError(f"falha ao localizar o terminal {name} para "
                                "encerra-lo")
        session_id = found[0]
        result = self._call(("tmux", "kill-session", "-t", session_id))
        if result is not None and (result.returncode == 0
                                   or _session_missing(result, session_id)):
            return
        raise TerminalError(f"falha ao encerrar o terminal {name}: "
                            f"{_detail(result)}")

    def attach_argv(self, terminal_id: str) -> list[str]:
        """argv interativo (com TTY) que anexa exatamente a esta sessao:
        pelo `session_id` quando a tag ou o nome a localizam (um rename nao
        a perde), senao pelo nome exato, que no pior caso nao acha nada."""
        name = TerminalId(terminal_id)
        found = self._locate(name)
        target = (found[0] if found is not None and found is not _ABSENT
                  else f"={name}")
        return self._connection.ssh_argv(
            ("tmux", "attach-session", "-t", target), interactive=True)

    def _locate(self, name: TerminalId):
        """`(session_id, [(pane_dead, status), ...])` da UNICA sessao que
        carrega a tag ou o nome; `_ABSENT` com prova do tmux; `None` na
        duvida (inclusive duas sessoes casando)."""
        result = self._call(("tmux", "list-panes", "-a", "-f", _filter(name),
                             "-F", _PANE_FORMAT))
        if result is None:
            return None
        if result.returncode != 0:
            return _ABSENT if _no_server(result) else None
        lines = result.stdout.splitlines()
        if not lines:
            return _ABSENT
        panes = []
        for line in lines:
            match = _PANE_LINE.fullmatch(line)
            if match is None:
                return None
            panes.append(match.groups())
        if len({session for session, _dead, _status in panes}) != 1:
            return None
        return panes[0][0], [(dead == "1", status)
                             for _session, dead, status in panes]

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

_ABSENT = object()


def _no_server(result: subprocess.CompletedProcess) -> bool:
    """Exit 1 do tmux com "no server running on <socket>" (pinado)."""
    return result.returncode == 1 and any(
        _NO_SERVER.fullmatch(line.strip())
        for line in (result.stderr or "").splitlines())


def _session_missing(result: subprocess.CompletedProcess,
                     target: str) -> bool:
    """So o exit 1 do tmux com mensagem pinada prova ausencia; o 255 do
    SSH ou qualquer outra saida nao prova nada."""
    if result.returncode != 1:
        return False
    for line in (result.stderr or "").splitlines():
        line = line.strip()
        if line == f"can't find session: {target}":
            return True
        if _NO_SERVER.fullmatch(line):
            return True
    return False


def _detail(result: subprocess.CompletedProcess | None) -> str:
    if result is None:
        return "ssh expirou ou nao executou"
    lines = (result.stderr or "").strip().splitlines()
    return f"exit {result.returncode}" + (f": {lines[-1]}" if lines else "")
