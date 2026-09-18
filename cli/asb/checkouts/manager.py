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
    CheckoutBinding, ProjectRegistry, ProjectRegistryError, _project_id_for,
)
from ..runtime.sandbox import SandboxError, SandboxRuntime
from ..sessions.model import AgentSession, SessionState
from ..sessions.terminal import Liveness
from .git import GitError, GitRepository, Worktree
from .model import (
    Checkout, CheckoutId, CheckoutKind, CheckoutState, FinishCheckout,
    FinishResult, FinishState,
)

# Sessoes que nunca mais rodam: nao precisam de sonda.
_FINAL_SESSIONS = frozenset({SessionState.COMPLETED, SessionState.FAILED})
_EXPORT_NAMESPACE = "refs/asb"

SessionLister = Callable[[CheckoutId], "list[AgentSession]"]
LivenessProbe = Callable[[CheckoutBinding, AgentSession], Liveness]


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
                 agent_root: Path | None = None,
                 runtime: SandboxRuntime | None = None,
                 sessions: SessionLister | None = None,
                 liveness: LivenessProbe | None = None) -> None:
        self._registry = registry
        self._repository = repository
        self._agent_root = (agent_root if agent_root is not None
                            else Path.home() / "asb-agent")
        # So `finish`/`cleanup` usam estes tres; sem eles, recusam.
        self._runtime = runtime
        self._sessions = sessions
        self._liveness = liveness

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

    # -- finish e cleanup ---------------------------------------------------------

    def finish(self, request: FinishCheckout) -> FinishResult:
        """Integra o worktree em `request.target_branch`. Toda a evidencia
        e coletada antes da primeira mutacao, na ordem fixa: checkout,
        sessoes, alvo, export; so entao o merge. Nada e removido sem a prova
        de ancestralidade. Nunca levanta: toda recusa vira `BLOCKED`."""
        try:
            return self._finish(request)
        except (CheckoutError, GitError, SandboxError,
                ProjectRegistryError) as exc:
            return FinishResult.blocked(str(exc))

    def cleanup(self, checkout_id: CheckoutId, target_branch: str | None = None,
                delete_merged_branch: bool = False) -> FinishResult:
        """Limpa um worktree ja integrado (merge externo, ou retomada de um
        `CLEANUP_PENDING`), sem merge: re-coleta checkout e sessoes e prova
        de novo a ancestralidade contra o alvo resolvido (default: o branch
        de integracao do projeto). Idempotente: retoma no primeiro passo
        que falta. Nunca levanta."""
        try:
            return self._cleanup(checkout_id, target_branch,
                                 delete_merged_branch)
        except (CheckoutError, GitError, SandboxError,
                ProjectRegistryError) as exc:
            return FinishResult.blocked(str(exc))

    def merged(self, checkout_id: CheckoutId,
               target_branch: str | None = None) -> bool:
        """Evidencia FRESCA de integracao externa, para o rotulo da TUI: o
        HEAD do worktree e toda ref exportada do sandbox
        (`refs/asb/<workspace>/...`, ao menos uma) sao ancestrais do alvo.
        Read-only; `False` em qualquer duvida."""
        try:
            binding = self._registry.checkout(checkout_id)
            project = self._registry.get(binding.project_id)
            path = binding.source_path
            if (checkout_kind(project, path) is CheckoutKind.PRIMARY
                    or not path.is_dir()):
                return False
            primary = self._repository(project.primary)
            target = primary.branch_commit(
                target_branch or project.integration_branch)
            head = self._repository(path).commit("HEAD")
            exported = primary.refs(self._export_prefix(binding))
            if target is None or head is None or not exported:
                return False
            commits = [head, *(commit for commit, _ in exported)]
            return all(primary.is_ancestor(c, target) for c in commits)
        except (GitError, ProjectRegistryError):
            return False

    def _finish(self, request: FinishCheckout) -> FinishResult:
        self._require_finish_services()
        binding = self._registry.checkout(request.checkout_id)
        project = self._registry.get(binding.project_id)
        # 1. O checkout de origem.
        source = self._finishable(binding)
        # 2. Sessoes: nenhuma viva, nenhuma incerta.
        busy = self._busy_sessions(binding)
        if busy is not None:
            return FinishResult.blocked(busy)
        # 3. Um checkout limpo JA no branch alvo.
        target_path = self._clean_target(project, request.target_branch,
                                         source.path)
        # 4. O commit exato do sandbox, numa ref namespaced nossa.
        sandbox_commit, ref = self._runtime.export_head(binding)
        # 5. O HEAD do worktree do operador tambem tem de ser integrado.
        operator_commit = self._repository(source.path).commit("HEAD")
        if operator_commit is None:
            raise CheckoutError(f"could not read HEAD of {source.path}")
        # 6. A primeira mutacao: o merge no checkout alvo.
        target = self._repository(target_path)
        merged = target.merge(ref)
        if not merged.ok:
            conflicts = target.unmerged_paths()
            if conflicts:
                shown = ", ".join(conflicts[:5])
                more = (f" (+{len(conflicts) - 5} more)"
                        if len(conflicts) > 5 else "")
                return FinishResult(
                    FinishState.CONFLICT, sandbox_commit, None,
                    f"merging {ref} into {request.target_branch} conflicts "
                    f"in {shown}{more}; nothing was removed. Resolve and "
                    f"commit in {target_path}, or run: git -C {target_path} "
                    "merge --abort")
            return FinishResult.blocked(
                f"git merge {ref} failed in {target_path}: "
                f"{merged.reason()}; nothing was removed", sandbox_commit)
        # 7. A prova: os DOIS commits sao ancestrais do novo HEAD do alvo.
        try:
            target_commit = target.commit("HEAD")
            proven = (target_commit is not None
                      and target.is_ancestor(sandbox_commit, target_commit)
                      and target.is_ancestor(operator_commit, target_commit))
        except GitError as exc:
            return FinishResult.cleanup_pending(
                sandbox_commit, None, f"integration is not proven: {exc}")
        if not proven:
            return FinishResult.cleanup_pending(
                sandbox_commit, target_commit, "integration is not proven")
        done = f"merged {ref} into {request.target_branch} at {target_path}"
        if not request.cleanup_after_merge:
            return FinishResult(FinishState.MERGED, sandbox_commit,
                                target_commit, f"{done}; cleanup available")
        return self._cleanup_after_proof(
            binding, project, source.path, source.branch, target_commit,
            sandbox_commit, sandbox_commit, request.delete_merged_branch,
            target_path, done)

    def _cleanup(self, checkout_id: CheckoutId, target_branch: str | None,
                 delete_merged_branch: bool) -> FinishResult:
        self._require_finish_services()
        binding = self._registry.checkout(checkout_id)
        project = self._registry.get(binding.project_id)
        branch_name = target_branch or project.integration_branch
        primary = self._repository(project.primary)
        target_commit = self._target_commit(primary, branch_name)
        path = binding.source_path
        if checkout_kind(project, path) is CheckoutKind.PRIMARY:
            raise CheckoutError("the primary checkout is never cleaned up")
        listed = any(wt.path.resolve() == path.resolve()
                     for wt in primary.worktrees())
        if path.is_dir() or listed:
            source = self._finishable(binding)
            source_commit = self._repository(path).commit("HEAD")
            if source_commit is None:
                raise CheckoutError(f"could not read HEAD of {path}")
            if not primary.is_ancestor(source_commit, target_commit):
                return FinishResult.blocked(
                    f"{path} at {source_commit[:12]} is not integrated into "
                    f"{branch_name}; finish it first", source_commit,
                    target_commit)
            source_path: Path | None = path
            branch: str | None = source.branch
        else:
            # O Git ja removeu o worktree (uma limpeza interrompida): a
            # prova vem das refs exportadas do sandbox.
            prefix = self._export_prefix(binding)
            exported = primary.refs(prefix)
            if not exported:
                return FinishResult.blocked(
                    f"{path} is gone and no export ref under {prefix} "
                    "proves its work was integrated; manual recovery "
                    "required")
            for commit, ref in exported:
                if not primary.is_ancestor(commit, target_commit):
                    return FinishResult.blocked(
                        f"{path} is gone and {ref} is not integrated into "
                        f"{branch_name}; manual recovery required", commit,
                        target_commit)
            source_commit = exported[0][0]
            source_path, branch = None, None
        busy = self._busy_sessions(binding)
        if busy is not None:
            return FinishResult.blocked(busy, source_commit, target_commit)
        location = self._checkout_on(primary, branch_name) or project.primary
        return self._cleanup_after_proof(
            binding, project, source_path, branch, target_commit,
            source_commit, None, delete_merged_branch, location,
            f"{branch_name} contains {source_commit[:12]}")

    def _cleanup_after_proof(
            self, binding: CheckoutBinding, project: Project,
            source_path: Path | None, branch: str | None, target_commit: str,
            source_commit: str, exported: str | None, delete_branch: bool,
            location: Path, done: str) -> FinishResult:
        """So depois da prova. Cada passo se re-checa; uma falha devolve
        `CLEANUP_PENDING` com o que ja foi feito e o que sobrou."""
        notes = [done]

        def pending(problem: str) -> FinishResult:
            return FinishResult.cleanup_pending(
                source_commit, target_commit,
                "; ".join([*notes, problem]) + "; retry cleanup when fixed")

        # 1-2. O sandbox, com a sua propria prova de que nada se perde.
        try:
            purged = self._runtime.purge_integrated(binding, target_commit,
                                                    exported)
        except SandboxError as exc:
            return pending(f"sandbox {binding.workspace} kept: {exc}")
        notes.append(f"purged sandbox {binding.workspace}" if purged
                     else f"sandbox {binding.workspace} already absent")
        # 3. O worktree do operador, sem --force.
        if source_path is not None:
            try:
                removed = self._repository(project.primary).worktree_remove(
                    source_path)
            except GitError as exc:
                return pending(f"could not remove {source_path}: {exc}")
            if not removed.ok:
                return pending(f"git refused to remove {source_path}: "
                               f"{removed.reason()}")
            notes.append(f"removed worktree {source_path}")
        # 4. O branch local, so com escolha explicita e so com `-d`.
        if delete_branch:
            notes.append(self._delete_merged(project, branch, target_commit,
                                             location))
        # 5. O vinculo do registro, por ultimo.
        try:
            self._registry.unbind_checkout(binding.checkout_id)
        except (ProjectRegistryError, OSError) as exc:
            return pending(f"could not remove the registry binding: {exc}")
        return FinishResult(FinishState.CLEANED, source_commit, target_commit,
                            "; ".join(notes))

    def _delete_merged(self, project: Project, branch: str | None,
                       target_commit: str, location: Path) -> str:
        """Uma recusa e relatada, nunca e falha do finish. Branches remotos
        nunca sao tocados."""
        if branch is None:
            return "local branch unknown; not deleted"
        primary = self._repository(project.primary)
        try:
            commit = primary.branch_commit(branch)
            if commit is None:
                return f"branch {branch} already deleted"
            if not primary.is_ancestor(commit, target_commit):
                return (f"branch {branch} moved to {commit[:12]}, which is "
                        "not integrated; kept")
            deleted = self._repository(location).delete_merged_branch(branch)
        except GitError as exc:
            return f"branch {branch} kept: {exc}"
        if not deleted.ok:
            return f"git refused to delete branch {branch}: {deleted.reason()}"
        return f"deleted branch {branch}"

    def _require_finish_services(self) -> None:
        if (self._runtime is None or self._sessions is None
                or self._liveness is None):
            raise CheckoutError(
                "finish needs the sandbox runtime and session liveness")

    def _finishable(self, binding: CheckoutBinding) -> Checkout:
        """O checkout de origem, como o Git o ve: nao primario, limpo e num
        branch. `inspect` ja recusa um caminho ausente ou nao listado."""
        source = self.inspect(binding.checkout_id)
        if source.kind is CheckoutKind.PRIMARY:
            raise CheckoutError("the primary checkout is never finished")
        if source.state is CheckoutState.DIRTY:
            raise CheckoutError(f"{source.path} has uncommitted changes; "
                                "commit or stash them first")
        if source.state is CheckoutState.DETACHED:
            raise CheckoutError(f"{source.path} is on a detached HEAD; "
                                "switch it to its branch first")
        return source

    def _busy_sessions(self, binding: CheckoutBinding) -> str | None:
        """Motivo de recusa se alguma sessao do checkout pode estar viva.
        Sem sandbox (prova positiva de ausencia) nao ha processo algum.
        Nunca para uma sessao."""
        pending = [s for s in self._sessions(binding.checkout_id)
                   if s.state not in _FINAL_SESSIONS]
        if not pending or self._runtime.sandbox_absent(binding):
            return None
        for session in pending:
            liveness = (Liveness.UNKNOWN if session.terminal_id is None
                        else self._liveness(binding, session))
            if liveness is Liveness.ALIVE:
                return (f"active session {session.id}; stop it before "
                        "finishing")
            if liveness is not Liveness.DEAD:
                return (f"liveness unknown for session {session.id}; stop "
                        "it (asb-agent session stop) or resume the "
                        "workspace, then retry")
        return None

    def _target_commit(self, primary: GitRepository, branch: str) -> str:
        if not primary.valid_branch_name(branch):
            raise CheckoutError(f"invalid target branch {branch!r}")
        commit = primary.branch_commit(branch)
        if commit is None:
            raise CheckoutError(f"target branch {branch} does not exist "
                                "locally")
        return commit

    def _clean_target(self, project: Project, branch: str,
                      source_path: Path) -> Path:
        """O checkout do projeto que JA esta em `branch`, limpo. Nunca troca
        o branch de checkout algum."""
        primary = self._repository(project.primary)
        self._target_commit(primary, branch)
        found = self._checkout_on(primary, branch)
        if found is None:
            raise CheckoutError(
                f"no checkout has {branch} checked out; check it out in a "
                "clean checkout (the primary, for example) and retry")
        if found.resolve() == source_path.resolve():
            raise CheckoutError(f"{source_path} is itself on {branch}; "
                                "choose another target branch")
        if self._repository(found).status() is not CheckoutState.CLEAN:
            raise CheckoutError(
                f"target checkout {found} has uncommitted changes; commit or "
                "stash them and retry")
        return found

    def _checkout_on(self, primary: GitRepository, branch: str) -> Path | None:
        for wt in primary.worktrees():
            if (wt.branch == branch and not wt.bare and not wt.prunable
                    and wt.path.is_dir()):
                return wt.path
        return None

    def _export_prefix(self, binding: CheckoutBinding) -> str:
        return f"{_EXPORT_NAMESPACE}/{binding.workspace}"
