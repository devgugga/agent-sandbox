"""cli/asb/runtime/connection.py — conexao SSH tipada de um workspace vivo.

`ConnectionInfo` e a forma tipada da linha que `lifecycle.emit()` imprime, e
`resolve_connection()` a preenche lendo estado JA existente (container,
porta publicada, origem, chave SSH) — nunca criando nem religando nada.
`emit()` continua sendo o UNICO lugar que imprime a conexao para o Orca; este
modulo so lhe da uma forma tipada para nao duplicar a serializacao.
"""
from __future__ import annotations

import getpass
import shlex
from dataclasses import dataclass
from pathlib import Path

# O agente so publica a porta 22 em loopback (`-p 127.0.0.1::22` em
# `lifecycle.prepare_workspace`): o host de conexao e sempre este, nunca o
# que `podman port` devolve na resposta (que pode vir como "0.0.0.0:<porta>"
# dependendo do driver).
SSH_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ConnectionInfo:
    workspace: str
    host: str
    port: int
    username: str
    identity_file: Path
    project_root: Path

    def ssh_argv(self, command: tuple[str, ...] = (), *,
                 interactive: bool = True) -> list[str]:
        """Argumentos de `ssh` para esta conexao, como LISTA — nunca uma
        string de shell. Um `command` nao vazio vira um UNICO argumento
        final via `shlex.join`, exatamente como o operador digitaria depois
        do `ssh host`; isto nunca invoca um shell local.

        `interactive=False` e para chamadas de maquina: sem TTY (`-T`),
        sem prompt de senha (`BatchMode=yes`) e com `ConnectTimeout=10`,
        as mesmas opcoes de `auth.py`. O resto do argv e identico."""
        if (not isinstance(self.port, int) or isinstance(self.port, bool)
                or not (1 <= self.port <= 65535)):
            raise ValueError(f"porta SSH invalida: {self.port!r}")
        if interactive:
            tty = ["-tt"]
        else:
            tty = ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        argv = [
            "ssh", *tty, "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-i", str(self.identity_file),
            "-p", str(self.port),
            "--", f"{self.username}@{self.host}",
        ]
        if command:
            argv.append(shlex.join(command))
        return argv

    def to_lifecycle_payload(self) -> dict[str, object]:
        """Delega para `lifecycle_payload`: mesmas quatro chaves, mesma
        ordem, que `lifecycle.emit()` imprime hoje."""
        return self.lifecycle_payload(
            self.workspace, self.port, self.username, self.project_root)

    @staticmethod
    def lifecycle_payload(workspace: str, port: int, username: str,
                          project_root: Path) -> dict[str, object]:
        """Construtor de payload que NAO exige uma instancia completa de
        `ConnectionInfo` (nem `host` nem `identity_file`, que `emit()` nunca
        resolveu). E o unico lugar que escreve estas quatro chaves, nesta
        ordem — `emit()` e `to_lifecycle_payload()` chamam so este metodo."""
        return {
            "workspace": workspace,
            "port": int(port),
            "user": username,
            "project_root": str(project_root),
        }


def resolve_connection(workspace: str) -> "ConnectionInfo":
    """Conexao viva de `workspace`, lida do estado JA existente.

    Reusa exatamente as buscas que `lifecycle` ja faz (`_require_workspace`
    para container + origem, `layout_for` para `project_root`, `podman port`
    para a porta publicada, `lifecycle.SSH_KEY` para a chave) — nunca inicia,
    religa ou remove um container. Toda falha vira `podman.PodmanError` antes
    de qualquer stdout.
    """
    from .. import lifecycle, podman

    n, home, origin = lifecycle._require_workspace(workspace)
    layout = lifecycle.layout_for(origin, workspace, home)

    mapping = podman.out("port", n["agent"], "22")
    raw_port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
    if not raw_port:
        # Um container parado (workspace suspenso) nao publica porta:
        # `podman port` sai 0 sem saida, e o remedio e religa-lo.
        raise podman.PodmanError(
            f"nao foi possivel determinar a porta SSH de {workspace}: o "
            f"workspace pode estar suspenso; rode 'asb-agent resume "
            f"--workspace {workspace}'")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise podman.PodmanError(
            f"porta SSH corrompida para {workspace}: {raw_port!r}") from exc

    key = lifecycle.SSH_KEY
    if not key.exists():
        raise podman.PodmanError(
            f"chave SSH ausente para {workspace}: {key} "
            "(rode 'asb-agent up' ou 'asb-agent resume' para gera-la)")

    return ConnectionInfo(
        workspace=workspace,
        host=SSH_HOST,
        port=port,
        username=getpass.getuser(),
        identity_file=key,
        project_root=layout.project_root,
    )
