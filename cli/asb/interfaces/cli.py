"""cli/asb/interfaces/cli.py — acesso SSH direto a um workspace vivo, sem
depender do Orca.

`connect()` e o unico lugar que substitui o processo do host pelo cliente
`ssh`: le a conexao viva via `resolve_connection` (nunca inicia, religa ou
muda nada) e troca o processo atual por um shell de login no diretorio do
projeto dentro do container. Um workspace parado ou ausente chega aqui como
`PodmanError` — a mesma excecao de infraestrutura que todo outro comando
deste CLI ja propaga sem disfarce; `connect` nao a engole nem tenta
'up'/'resume' por conta propria.
"""
from __future__ import annotations

import os
import shlex

from ..runtime.connection import resolve_connection


def connect(workspace: str, *, execute=os.execvp) -> int:
    """Substitui o processo do host por um `ssh` conectado a `workspace`.

    So a parte remota (`project_root`) passa por `shlex.quote`: os
    argumentos locais de `ssh_argv` sao entradas de argv separadas, nunca
    texto de shell. `execute` e injetavel para teste; o default `os.execvp`
    substitui o processo — quem chama sem falha nunca ve o `return 0`, que
    so um teste com um `execute` gravador observa.
    """
    info = resolve_connection(workspace)
    remote_path = shlex.quote(str(info.project_root))
    script = f"cd -- {remote_path} && exec ${{SHELL:-/bin/bash}} -l"
    argv = info.ssh_argv(("sh", "-lc", script))
    execute("ssh", argv)
    return 0
