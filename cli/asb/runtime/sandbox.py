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
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .. import podman
from ..checkouts.git import GitError, GitRepository
from ..checkouts.model import Checkout
from ..projects.model import Project
from ..projects.registry import CheckoutBinding, ProjectRegistry
from ..workspace import layout_for
from . import storage
from .connection import ConnectionInfo, resolve_connection

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
Remote = Callable[[ConnectionInfo, Sequence[str]],
                  "subprocess.CompletedProcess[str]"]

_REMOTE_TIMEOUT_SECONDS = 30.0


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)


def _default_remote(connection: ConnectionInfo,
                    argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    """Roda `argv` DENTRO do sandbox por SSH nao interativo."""
    return subprocess.run(connection.ssh_argv(tuple(argv), interactive=False),
                          shell=False, capture_output=True, text=True,
                          timeout=_REMOTE_TIMEOUT_SECONDS, check=False,
                          stdin=subprocess.DEVNULL)


class SandboxError(Exception):
    """Evidencia do sandbox que nao se prova: export, guarda ou purge."""


class WorkspaceStatus(StrEnum):
    """Estado de um workspace visto por `discover`, sem muta-lo."""

    READY = "ready"              # container existe e a conexao resolve
    ABSENT = "absent"            # nenhum container de agente
    UNAVAILABLE = "unavailable"  # existe (ou nao da para saber) mas nao resolve


@dataclass(frozen=True)
class WorkspaceDiscovery:
    """Um binding e o status do seu workspace. `connection` so em READY;
    `reason` (uma linha curta, sem caracteres de controle) so em
    UNAVAILABLE."""

    binding: CheckoutBinding
    status: WorkspaceStatus
    connection: ConnectionInfo | None = None
    reason: str | None = None


_REASON_LIMIT = 120
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _short_reason(error: BaseException) -> str:
    """Primeira linha da mensagem, controles trocados por `?`, truncada."""
    lines = str(error).splitlines() or [type(error).__name__]
    return _CONTROL.sub("?", lines[0].strip())[:_REASON_LIMIT]


def session_volume_mountpoint(workspace: str) -> Path:
    """Mountpoint, no host, do volume de sessao de `workspace`.

    E por ele que o host le a evidencia de sessao dos provedores (os
    subpaths de `storage.SESSION_STATE_DIRS` que o container monta sobre
    `~/.codex/sessions` e `~/.claude/projects`). Reusa `lifecycle.names` e
    `storage.volume_mountpoint` (fronteira publica, Tarefa 6 — antes
    alcancava `storage._volume_mountpoint`, simbolo privado do modulo
    irmao); nunca cria o volume — um volume ausente levanta
    `podman.PodmanError`."""
    from .. import lifecycle  # tardio: mesmo padrao de resolve_connection

    return storage.volume_mountpoint(lifecycle.names(workspace)["session"])


@dataclass
class SandboxRuntime:
    """Fronteira injetavel: `root` localiza `cli/asb-agent`, `registry`
    guarda o relacionamento checkout-workspace, `runner` executa o CLI
    estavel sem acoplar este modulo a `subprocess` real (testes injetam um
    fake)."""

    root: Path
    registry: ProjectRegistry
    runner: Runner = field(default=_default_runner)
    # Git do host (o do operador e as leituras do clone do sandbox) e o
    # comando executado DENTRO do sandbox; ambos injetaveis para testes.
    repository: Callable[[Path], GitRepository] = field(default=GitRepository)
    remote: Remote = field(default=_default_remote)

    # -- leitura, nunca muta estado de runtime -----------------------------

    def discover(self, project: Project) -> list[WorkspaceDiscovery]:
        """Status explicito do workspace de CADA binding do projeto, na
        ordem do registro; nenhum binding e omitido. Read-only: nunca
        inicia, religa ou remove um container. A checagem segue a mesma
        ordem de `ensure()`: sem container de agente e ABSENT; com
        container, uma falha de `resolve_connection` (suspenso, porta
        corrompida, chave ausente, origem perdida) e UNAVAILABLE com o
        motivo. Uma falha da propria checagem de existencia (podman
        ausente) tambem e UNAVAILABLE: nao se sabe se o container falta."""
        from .. import lifecycle  # tardio: mesmo padrao de resolve_connection

        found: list[WorkspaceDiscovery] = []
        for binding in self.registry.bindings(project.id):
            agent = lifecycle.names(binding.workspace)["agent"]
            try:
                if not podman.exists("container", agent):
                    found.append(WorkspaceDiscovery(
                        binding, WorkspaceStatus.ABSENT))
                    continue
                info = resolve_connection(binding.workspace)
            except (podman.PodmanError, OSError,
                    subprocess.SubprocessError) as exc:
                found.append(WorkspaceDiscovery(
                    binding, WorkspaceStatus.UNAVAILABLE,
                    reason=_short_reason(exc)))
                continue
            found.append(WorkspaceDiscovery(
                binding, WorkspaceStatus.READY, connection=info))
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
        esconderia o diagnostico real (achado de revisao, ronda 1). Nunca
        escreve no registro: o vinculo checkout-workspace ja existe (criado
        por `register_checkout`); a conexao so e devolvida depois que
        `resolve_connection` confirma a prontidao com evidencia ao vivo."""
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

    # -- finish: exportar e purgar so com evidencia -------------------------

    def sandbox_head(self, binding: CheckoutBinding) -> tuple[str, str]:
        """`(branch, commit)` do clone do sandbox, validados, so com leituras
        do host (`symbolic-ref`, `rev-parse`). E o que a confirmacao do
        finish mostra e o que `export_head` exige depois."""
        root = self._connection(binding).project_root
        try:
            return self._head(root, self.repository(root),
                              self._operator(binding))
        except GitError as exc:
            raise SandboxError(str(exc)) from exc

    def _head(self, root: Path, sandbox: GitRepository,
              operator: GitRepository) -> tuple[str, str]:
        branch = sandbox.symbolic_branch()
        if branch is None:
            raise SandboxError(
                f"sandbox HEAD in {root} is detached; put the work on a "
                "branch before finishing")
        if not operator.valid_branch_name(branch):
            raise SandboxError(
                f"sandbox branch {branch!r} is not a valid branch name")
        commit = sandbox.commit(f"refs/heads/{branch}")
        if commit is None:
            raise SandboxError(
                f"sandbox branch {branch!r} does not resolve to a commit")
        return branch, commit

    def export_head(self, binding: CheckoutBinding,
                    expected: tuple[str, str] | None = None
                    ) -> tuple[str, str]:
        """Traz o commit EXATO do branch do clone do sandbox para
        `refs/asb/<workspace>/<branch>` no repositorio do operador e devolve
        `(commit, ref)`. Nao reusa `asb-agent pull`: o nome do branch vem
        de um checkout gravavel pelo agente e e validado antes de virar
        refspec. O `+` do refspec so atualiza a ref namespaced, que e nossa,
        nunca um branch do operador. `expected`: o `(branch, commit)` que o
        operador confirmou; qualquer diferenca recusa antes do fetch."""
        connection = self._connection(binding)
        root = connection.project_root
        sandbox = self.repository(root)
        operator = self._operator(binding)
        try:
            branch, commit = self._head(root, sandbox, operator)
            if expected is not None and (branch, commit) != expected:
                raise SandboxError(
                    f"the sandbox changed since the confirmation: it is on "
                    f"{branch} at {commit[:12]}, the confirmation showed "
                    f"{expected[0]} at {(expected[1] or '')[:12]}; nothing "
                    "was merged, confirm again")
            ref = f"refs/asb/{binding.workspace}/{branch}"
            if not operator.valid_ref(ref):
                raise SandboxError(f"export ref {ref!r} is not a valid ref")
            fetched = operator.fetch(root, f"+refs/heads/{branch}:{ref}")
            if not fetched.ok:
                raise SandboxError(
                    f"fetch from the sandbox failed: {fetched.reason()}")
            exported = operator.commit(ref)
            if exported != commit:
                raise SandboxError(
                    f"{ref} is at {exported}, not at the sandbox commit "
                    f"{commit}; the sandbox branch moved during the export")
        except GitError as exc:
            raise SandboxError(str(exc)) from exc
        return commit, ref

    def sandbox_absent(self, binding: CheckoutBinding) -> bool:
        """Prova POSITIVA de que o sandbox do binding nao existe mais: sem
        container de agente, sem volumes do workspace, sem marcador de
        origem e sem o diretorio do clone. Qualquer duvida e `False`."""
        from .. import lifecycle  # tardio: mesmo padrao de resolve_connection

        ws = binding.workspace
        n = lifecycle.names(ws)
        home = Path(os.path.expanduser("~"))
        try:
            if podman.exists("container", n["agent"]):
                return False
            for volume in (n["session"], f"asb-{ws}-containers"):
                if podman.exists("volume", volume):
                    return False
            if lifecycle.origin_of(ws, home) is not None:
                return False
        except (podman.PodmanError, OSError, subprocess.SubprocessError):
            return False
        mount = layout_for(binding.source_path, ws, home).mount
        return not os.path.lexists(mount)

    def purge_integrated(self, binding: CheckoutBinding, target_commit: str,
                         exported: str | None) -> bool:
        """Purga o sandbox do binding so depois de provar que nada nele se
        perde. `False`: ja estava ausente, nada feito. `True`: purgado e
        confirmado ausente. Qualquer outra coisa levanta `SandboxError` sem
        purgar (ou dizendo que o purge nao se confirmou)."""
        if self.sandbox_absent(binding):
            return False
        problems = self._unexported_work(binding, target_commit, exported)
        if problems:
            raise SandboxError("purging would lose " + "; ".join(problems))
        argv = [str(self.root / "cli" / "asb-agent"), "purge",
                "--workspace", binding.workspace, "--yes"]
        try:
            result = self.runner(argv)
        except OSError as exc:
            raise SandboxError(
                f"could not run 'asb-agent purge' for {binding.workspace}: "
                f"{exc}") from exc
        if result.returncode != 0:
            lines = (result.stderr or "").strip().splitlines()
            detail = (": " + _CONTROL.sub("?", lines[-1])[:_REASON_LIMIT]
                      if lines else "")
            raise SandboxError(
                f"'asb-agent purge' failed for {binding.workspace} (code "
                f"{result.returncode}){detail}")
        if not self.sandbox_absent(binding):
            raise SandboxError(
                f"'asb-agent purge' exited 0 but {binding.workspace} still "
                "exists")
        return True

    def _unexported_work(self, binding: CheckoutBinding, target_commit: str,
                         exported: str | None) -> list[str]:
        """O que um purge perderia. O status roda DENTRO do sandbox: um
        `git status` do host num clone gravavel pelo agente executaria o
        `core.fsmonitor` ou um filtro que o agente configurasse. As demais
        leituras (refs, HEAD, worktrees) nao executam nada da config."""
        connection = self._connection(binding)
        root = connection.project_root
        argv = ("git", "-C", str(root), "status", "--porcelain=v1", "-z",
                "--untracked-files=all")
        try:
            status = self.remote(connection, argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxError(
                f"could not read the sandbox status: {exc}") from exc
        if status.returncode != 0:
            raise SandboxError(
                f"git status failed in the sandbox (code {status.returncode})")
        problems = []
        if status.stdout:
            problems.append(f"uncommitted changes in {root}")
        sandbox = self.repository(root)
        operator = self._operator(binding)
        try:
            head = sandbox.commit("HEAD")
            if head is None:
                raise SandboxError(f"could not read HEAD in {root}")
            if exported is not None and head != exported:
                problems.append(f"sandbox HEAD moved to {head[:12]} after "
                                f"the export of {exported[:12]}")
            tips = [(head, "HEAD"), *sandbox.refs("refs/heads", "refs/stash")]
            if any(ref == "refs/stash" for _, ref in tips):
                # `for-each-ref` so ve a entrada mais nova do stash.
                older = sandbox.reflog_commits("refs/stash")[1:]
                tips += [(commit, f"stash@{{{index}}}")
                         for index, commit in enumerate(older, start=1)]
            for commit, ref in tips:
                if operator.commit(commit) is None:
                    problems.append(f"{ref} ({commit[:12]}) was never "
                                    "exported")
                elif not operator.is_ancestor(commit, target_commit):
                    problems.append(f"{ref} ({commit[:12]}) is not "
                                    "integrated into the target")
            extra = sandbox.worktrees()[1:]
            if extra:
                problems.append(f"{len(extra)} extra worktree(s) in the "
                                "sandbox clone")
        except GitError as exc:
            raise SandboxError(str(exc)) from exc
        return problems

    def _connection(self, binding: CheckoutBinding) -> ConnectionInfo:
        try:
            return resolve_connection(binding.workspace)
        except (podman.PodmanError, OSError,
                subprocess.SubprocessError) as exc:
            raise SandboxError(
                f"sandbox {binding.workspace} is not reachable: "
                f"{_short_reason(exc)}") from exc

    def _operator(self, binding: CheckoutBinding) -> GitRepository:
        return self.repository(self.registry.get(binding.project_id).primary)
