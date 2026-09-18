"""cli/asb/runtime/sandbox.py — fronteira de controlador para o runtime.

`SandboxRuntime` e o unico ponto pelo qual um controlador (ex: a TUI) pede um
workspace pronto. Ele NUNCA reimplementa `up`/`resume`: quando nao ha
runtime vivo, invoca `cli/asb-agent` como um subprocesso injetado (o mesmo
binario que o Orca chama), le a linha JSON que `lifecycle.emit()` imprime, e
so entao confirma com evidencia ao vivo via `resolve_connection`. Este
modulo nunca escreve no `ProjectRegistry`: o vinculo checkout-workspace e o
proprio registro do checkout, criado por `register_checkout` antes de
qualquer workspace existir.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .. import podman
from ..checkouts.model import Checkout
from ..projects.model import Project
from ..projects.registry import CheckoutBinding, ProjectRegistry
from .connection import ConnectionInfo, resolve_connection

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)


def session_volume_mountpoint(workspace: str) -> Path:
    """Mountpoint, no host, do volume de sessao de `workspace`.

    E por ele que o host le a evidencia de sessao dos provedores (os
    subpaths de `lifecycle.SESSION_STATE_DIRS` que o container monta sobre
    `~/.codex/sessions` e `~/.claude/projects`). Reusa `lifecycle.names` e
    `lifecycle._volume_mountpoint`; nunca cria o volume — um volume ausente
    levanta `podman.PodmanError`."""
    from .. import lifecycle  # tardio: mesmo padrao de resolve_connection

    return lifecycle._volume_mountpoint(lifecycle.names(workspace)["session"])


@dataclass
class SandboxRuntime:
    """Fronteira injetavel: `root` localiza `cli/asb-agent`, `registry`
    guarda o relacionamento checkout-workspace, `runner` executa o CLI
    estavel sem acoplar este modulo a `subprocess` real (testes injetam um
    fake)."""

    root: Path
    registry: ProjectRegistry
    runner: Runner = field(default=_default_runner)

    # -- leitura, nunca muta estado de runtime -----------------------------

    def discover(self, project: Project) -> list[tuple[CheckoutBinding, ConnectionInfo]]:
        """Vincula cada `CheckoutBinding` do projeto ao seu estado de
        workspace ao vivo, quando ele existe. Read-only: nunca inicia,
        religa ou remove um container. Um binding cujo workspace nao
        resolve (down, purgado, etc.) e simplesmente omitido — isso nao e
        erro, e o normal de um workspace que o operador parou."""
        found: list[tuple[CheckoutBinding, ConnectionInfo]] = []
        for binding in self.registry.bindings(project.id):
            try:
                info = resolve_connection(binding.workspace)
            except podman.PodmanError:
                continue
            found.append((binding, info))
        return found

    def binding_for(self, checkout: Checkout) -> CheckoutBinding | None:
        """O `CheckoutBinding` do registro que corresponde a `checkout`, ou
        `None`. Read-only, nunca toca Podman."""
        for binding in self.registry.bindings(checkout.project_id):
            if binding.workspace == checkout.workspace:
                return binding
        return None

    # -- unico ponto que pode criar um workspace ---------------------------

    def ensure(self, checkout: CheckoutBinding) -> ConnectionInfo:
        """Conexao pronta para `checkout`. Delega a `cli/asb-agent up` (a
        MESMA fronteira estavel que o Orca chama) somente quando NAO ha
        container do workspace — a UNICA condicao que autoriza a queda para
        esse caminho. Um container que JA existe segue direto para
        `resolve_connection`: qualquer falha dali (porta corrompida, chave
        SSH ausente, origem perdida) significa workspace QUEBRADO, nao
        ausente, e tem de chegar ao chamador SEM disfarce — engoli-la e
        tentar `asb-agent up` so devolveria "workspace ja existe" e
        esconderia o diagnostico real (achado de revisao, ronda 1). So
        grava o vinculo no registro depois que `resolve_connection`
        confirma a prontidao com evidencia ao vivo."""
        from .. import lifecycle  # tardio: mesmo padrao de resolve_connection

        n = lifecycle.names(checkout.workspace)
        if podman.exists("container", n["agent"]):
            return resolve_connection(checkout.workspace)

        argv = [
            str(self.root / "cli" / "asb-agent"), "up",
            "--workspace", checkout.workspace,
            "--repo", str(checkout.source_path),
        ]
        try:
            result = self.runner(argv)
        except OSError as exc:
            # Unico ponto onde o runner injetado pode falhar fora do
            # contrato de `CompletedProcess` (ex: binario 'asb-agent'
            # ausente): sem isto um `OSError` cru escaparia deste modulo,
            # diferente de todo outro caminho de falha aqui (achado de
            # revisao, ronda 1, item Minor).
            raise podman.PodmanError(
                f"nao foi possivel executar 'asb-agent up' para "
                f"{checkout.workspace}: {exc}") from exc
        if result.returncode != 0:
            raise podman.PodmanError(
                f"'asb-agent up' falhou para {checkout.workspace} "
                f"(codigo {result.returncode}): {(result.stderr or '').strip()}")

        stdout_lines = [line for line in (result.stdout or "").splitlines()
                        if line.strip()]
        if not stdout_lines:
            raise podman.PodmanError(
                f"'asb-agent up' nao produziu a linha de conexao para "
                f"{checkout.workspace}")
        try:
            # So valida que a fronteira estavel devolveu o payload esperado;
            # o valor decodificado nao e usado — a evidencia ao vivo abaixo
            # e que decide, nunca o que o subprocesso disse de si mesmo.
            json.loads(stdout_lines[-1])
        except json.JSONDecodeError as exc:
            raise podman.PodmanError(
                f"saida invalida de 'asb-agent up' para {checkout.workspace}: "
                f"{exc}") from exc

        return resolve_connection(checkout.workspace)
