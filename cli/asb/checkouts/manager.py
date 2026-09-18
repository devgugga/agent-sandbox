"""cli/asb/checkouts/manager.py — listar, inspecionar e criar checkouts.

`CheckoutManager` e dono da validacao Git e da criacao segura de worktrees
(spec §5.1, §9). A criacao e uma transacao:

1. `preview` valida sem escrever nada: o projeto e o mesmo repositorio (Git
   common dir), o nome do branch e valido e novo, a base resolve para um
   commit (nunca adivinhada), e o caminho, com o pai resolvido, fica dentro
   da raiz de worktrees e fora do mount gravavel pelo agente;
2. `create` repete a validacao, cria a raiz (0700) se faltar, registra que o
   branch e o caminho NAO existiam e roda o `git worktree add -b` do
   contrato;
3. so depois de o Git sair com zero E a inspecao achar o worktree novo no
   branch novo e no commit da base, o checkout e registrado.

Rollback so toca o que esta transacao provou ter criado: um branch que nao
existia antes e aponta para o commit da base; um worktree removido sem
`--force`. Qualquer outra sobra e relatada ao operador, nunca forcada.

`list` le o Git e o registro sem nunca escrever. O runtime continua
preguicoso: o primeiro `session start` do checkout chama `ensure()`.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..projects.model import Project, ProjectId
from ..projects.registry import (
    CheckoutBinding, ProjectRegistry, _project_id_for,
)
from .git import GitError, GitRepository, Worktree
from .model import Checkout, CheckoutId, CheckoutKind, CheckoutState


class CheckoutError(Exception):
    """Operacao de checkout recusada ou falha, com o que sobrou dela."""


@dataclass(frozen=True)
class CreateCheckout:
    """`base_commit` e o commit que a previa mostrou e o operador
    confirmou; `create` recusa se a base nao aponta mais para ele."""

    project_id: ProjectId
    branch: str
    base: str
    path: Path
    base_commit: str | None = None


@dataclass(frozen=True)
class CreatePreview:
    """O que `create` faria: base por nome E commit, caminho absoluto."""

    project: Project
    branch: str
    base: str
    base_commit: str
    path: Path
    creates_branch: bool = True


@dataclass(frozen=True)
class ListedCheckout:
    """Um worktree que o Git lista (`worktree`) e o vinculo do registro
    (`binding`, `None` quando criado fora da TUI), ou um vinculo que o Git
    nao lista mais (`worktree=None`). `missing`: o caminho nao existe ou o
    Git nao o conhece."""

    path: Path
    binding: CheckoutBinding | None
    worktree: Worktree | None
    missing: bool


def checkout_kind(project: Project, path: Path) -> CheckoutKind:
    """`PRIMARY` quando `path` e o checkout primario, comparando caminhos
    RESOLVIDOS: a TUI e `inspect` usam esta mesma regra."""
    return (CheckoutKind.PRIMARY if path.resolve() == project.primary.resolve()
            else CheckoutKind.WORKTREE)


class CheckoutManager:
    def __init__(self, registry: ProjectRegistry, *,
                 repository: Callable[[Path], GitRepository] = GitRepository,
                 agent_root: Path | None = None) -> None:
        self._registry = registry
        self._repository = repository
        self._agent_root = (agent_root if agent_root is not None
                            else Path.home() / "asb-agent")

    # -- leitura ------------------------------------------------------------------

    def default_path(self, project: Project, branch: str) -> Path:
        return project.worktree_root / branch.replace("/", "-")

    def list(self, project_id: ProjectId) -> list[ListedCheckout]:
        project = self._registry.get(project_id)
        worktrees = self._repository(project.primary).worktrees()
        unmatched = {binding.source_path.resolve(): binding
                     for binding in self._registry.bindings(project_id)}
        listed = [ListedCheckout(
            path=wt.path, binding=unmatched.pop(wt.path.resolve(), None),
            worktree=wt, missing=not wt.path.exists())
            for wt in worktrees]
        listed.extend(ListedCheckout(binding.source_path, binding, None, True)
                      for binding in unmatched.values())
        return listed

    def inspect(self, checkout_id: CheckoutId) -> Checkout:
        """O checkout como o Git o ve agora. Levanta se o caminho sumiu,
        se o Git nao o lista no projeto, ou se nao da para ler seu estado."""
        binding = self._registry.checkout(checkout_id)
        project = self._registry.get(binding.project_id)
        path = binding.source_path
        if not path.is_dir():
            raise CheckoutError(f"checkout {checkout_id} is missing: {path}")
        try:
            listed = [wt for wt in self._repository(project.primary).worktrees()
                      if wt.path.resolve() == path.resolve()]
            if not listed or listed[0].prunable:
                raise CheckoutError(
                    f"{path} is not a worktree of project {project.id}")
            git = self._repository(path)
            branch = git.branch()
            if branch is None:
                raise CheckoutError(f"could not read the branch of {path}")
            state = git.status()
        except GitError as exc:
            raise CheckoutError(str(exc)) from exc
        if state is CheckoutState.CLEAN and branch.detached:
            state = CheckoutState.DETACHED
        return Checkout(
            id=binding.checkout_id, project_id=project.id, path=path,
            kind=checkout_kind(project, path),
            branch=branch.name, state=state, workspace=binding.workspace)

    # -- criacao ------------------------------------------------------------------

    def preview(self, request: CreateCheckout) -> CreatePreview:
        """Valida o pedido inteiro sem escrever nada."""
        project = self._registry.get(request.project_id)
        git = self._repository(project.primary)
        try:
            return self._preview(project, git, request)
        except GitError as exc:
            raise CheckoutError(str(exc)) from exc

    def _preview(self, project: Project, git: GitRepository,
                 request: CreateCheckout) -> CreatePreview:
        actual = git.common_dir()
        # Um registro antigo sem `gitCommonDir` confere pela identidade,
        # que o registro deriva do mesmo common dir.
        same = (actual.resolve() == project.git_common_dir.resolve()
                if project.git_common_dir is not None
                else _project_id_for(actual) == project.id)
        if not same:
            raise CheckoutError(
                f"{project.primary} belongs to another repository "
                f"({actual}), not to project {project.id}")
        if not git.valid_branch_name(request.branch):
            raise CheckoutError(f"invalid branch name {request.branch!r}")
        if git.branch_commit(request.branch) is not None:
            raise CheckoutError(f"branch {request.branch} already exists")
        base_commit = (git.commit(request.base)
                       if request.base and not request.base.startswith("-")
                       else None)
        if base_commit is None:
            raise CheckoutError(
                f"base {request.base!r} does not resolve to a commit in "
                f"{project.primary}; choose a base explicitly")
        return CreatePreview(project=project, branch=request.branch,
                             base=request.base, base_commit=base_commit,
                             path=self._target(project, request.path))

    def _target(self, project: Project, requested: Path) -> Path:
        """Caminho absoluto com o pai resolvido, contido na raiz resolvida."""
        requested = Path(requested)
        if not requested.is_absolute():
            raise CheckoutError(f"worktree path must be absolute: {requested}")
        if requested.name in ("", ".", ".."):
            raise CheckoutError(f"invalid worktree path: {requested}")
        root = project.worktree_root.resolve()
        agent_root = self._agent_root.resolve()
        if root.is_relative_to(agent_root):
            raise CheckoutError(
                f"worktree root {root} is inside the agent-writable mount "
                f"{agent_root}")
        target = requested.parent.resolve() / requested.name
        if target == root or not target.is_relative_to(root):
            raise CheckoutError(
                f"{target} is outside the worktree root {root}")
        if target.is_relative_to(agent_root):
            raise CheckoutError(
                f"{target} is inside the agent-writable mount {agent_root}")
        if os.path.lexists(target):
            raise CheckoutError(f"path {target} already exists")
        return target

    def create(self, request: CreateCheckout) -> Checkout:
        preview = self.preview(request)
        project, branch, target = preview.project, preview.branch, preview.path
        git = self._repository(project.primary)

        root = project.worktree_root.resolve()
        if not root.exists():
            root.mkdir(parents=True, mode=0o700)
            os.chmod(root, 0o700)

        try:
            # Estado ANTES do comando: a prova de dono do rollback.
            branch_before = git.branch_commit(branch)
            path_before = os.path.lexists(target)
            if branch_before is not None or path_before:
                raise CheckoutError(
                    f"branch {branch} or path {target} appeared before "
                    "creation; nothing was created")
            # A base resolvida de novo, logo antes do comando, tem de ser o
            # commit que o operador confirmou na previa.
            confirmed = request.base_commit or preview.base_commit
            current = git.commit(preview.base)
            if current != confirmed:
                raise CheckoutError(
                    f"base {preview.base} moved from {confirmed} to "
                    f"{current} since the preview; nothing was created, "
                    "preview again")
            result = git.worktree_add(branch, target, preview.base)
        except GitError as exc:
            raise CheckoutError(str(exc)) from exc

        if not result.ok:
            note = self._after_failed_add(git, preview)
            raise CheckoutError(
                f"git worktree add failed: {result.reason()}; {note}")

        try:
            self._confirm(git, preview)
            binding = self._registry.register_checkout(project.id, target)
        except Exception as exc:  # inspecao ou registro: desfaz o que e nosso
            note = self._undo_created(git, preview)
            raise CheckoutError(f"{exc}; {note}") from exc

        return Checkout(id=binding.checkout_id, project_id=project.id,
                        path=binding.source_path, kind=CheckoutKind.WORKTREE,
                        branch=branch, state=CheckoutState.CLEAN,
                        workspace=binding.workspace)

    def _confirm(self, git: GitRepository, preview: CreatePreview) -> None:
        """O Git saiu com zero; a inspecao tem de achar o worktree novo."""
        if not preview.path.is_dir():
            raise CheckoutError(f"{preview.path} was not created")
        found = [wt for wt in git.worktrees()
                 if wt.path.resolve() == preview.path]
        if not found:
            raise CheckoutError(f"{preview.path} is not listed by git")
        wt = found[0]
        if (wt.branch != preview.branch or wt.head != preview.base_commit
                or wt.prunable):
            raise CheckoutError(
                f"{preview.path} is on {wt.branch} at {wt.head}, expected "
                f"{preview.branch} at {preview.base_commit}")

    # -- rollback -----------------------------------------------------------------

    def _after_failed_add(self, git: GitRepository,
                          preview: CreatePreview) -> str:
        if os.path.lexists(preview.path):
            return (f"left {preview.path} and branch {preview.branch} "
                    "untouched for manual inspection")
        return self._delete_own_branch(git, preview)

    def _undo_created(self, git: GitRepository, preview: CreatePreview) -> str:
        try:
            removed = git.worktree_remove(preview.path)
        except GitError as exc:
            removed = None
            reason = str(exc)
        else:
            reason = removed.reason()
        if removed is None or not removed.ok:
            return (f"could not remove it ({reason}); left worktree "
                    f"{preview.path} and branch {preview.branch} for manual "
                    "recovery")
        return f"removed worktree {preview.path}; " + self._delete_own_branch(
            git, preview)

    def _delete_own_branch(self, git: GitRepository,
                           preview: CreatePreview) -> str:
        """Apaga o branch so com prova: ele nao existia antes (validado e
        registrado antes do comando) e aponta para o commit da base."""
        try:
            commit = git.branch_commit(preview.branch)
            if commit is None:
                return "nothing was left behind"
            if commit != preview.base_commit:
                return (f"branch {preview.branch} is at {commit}, not at the "
                        "base; left untouched")
            deleted = git.delete_branch(preview.branch)
        except GitError as exc:
            return f"could not check branch {preview.branch}: {exc}"
        if not deleted.ok:
            return (f"could not remove branch {preview.branch}: "
                    f"{deleted.reason()}")
        return f"removed branch {preview.branch}"
