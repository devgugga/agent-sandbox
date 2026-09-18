"""Testes de `CheckoutManager.finish/cleanup/merged` (Tarefa 12): a matriz
de operacoes destrutivas contra repositorios Git REAIS.

Cada caso monta um projeto temporario (primario em `main`), um worktree
`topic` criado pelo proprio `CheckoutManager` e um "sandbox" que e um clone
temporario desse worktree. A conexao do sandbox e falsa (aponta para o
clone), o `status` "remoto" roda o Git localmente no clone, o `purge` e um
runner falso que apaga o clone, e a liveness das sessoes e injetada. Nada
aqui toca Podman, SSH, tmux, este repositorio ou `~/.local/state`.

Todo argv de Git passa por um runner que o registra; nenhum pode conter
`--force`, `-f`, `-D`, `push` ou um remoto. Em todo caso BLOCKED, CONFLICT
ou CLEANUP_PENDING o caminho e o branch de origem continuam existindo; em
toda limpeza bem-sucedida o commit de origem e alcancavel pelo alvo.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from test_checkout_git import git, init_repo, isolate_git  # noqa: E402

from asb import podman  # noqa: E402
from asb.checkouts.git import GitRepository  # noqa: E402
from asb.checkouts.manager import (  # noqa: E402
    CheckoutError, CheckoutManager, CreateCheckout, FinishPreview,
)
from asb.checkouts.model import (  # noqa: E402
    CheckoutId, FinishCheckout, FinishResult, FinishState,
)
from asb.projects.registry import (  # noqa: E402
    ProjectRegistry, ProjectRegistryError,
)
from asb.runtime.connection import ConnectionInfo  # noqa: E402
from asb.runtime.sandbox import SandboxRuntime  # noqa: E402
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, SessionState, TerminalId,
)
from asb.sessions.terminal import Liveness  # noqa: E402

_FORBIDDEN = ("--force", "-f", "-D", "push")


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        isolate_git(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = init_repo(self.tmp / "repo")
        self.registry = ProjectRegistry(self.tmp / "state" / "projects.json")
        self.project = self.registry.add(self.repo, "main", self.tmp / "wts")
        self.primary = self.registry.register_checkout(self.project.id,
                                                       self.repo)
        self.calls: list[list[str]] = []
        # prefixo do argv (depois de `git -C <path>`) -> acao.
        self.faults: dict[tuple[str, ...], object] = {}
        self.before: dict[tuple[str, ...], object] = {}
        self.after: dict[tuple[str, ...], object] = {}
        self.addCleanup(self._assert_never_forced)

        checkout = self.manager().create(CreateCheckout(
            self.project.id, "topic", "main", self.tmp / "wts" / "topic"))
        self.worktree = checkout.path
        self.checkout_id = checkout.id
        self.binding = self.registry.checkout(checkout.id)
        self.ws = self.binding.workspace

        self.sandbox = self.tmp / "sandbox" / "repo"
        self.sandbox.parent.mkdir()
        git(self.tmp, "clone", "-q", str(self.worktree), str(self.sandbox))
        git(self.sandbox, "config", "user.name", "Agent")
        git(self.sandbox, "config", "user.email", "agent@example.com")

        self.absent = False
        self.purge_code = 0
        self.purge_argv: list[list[str]] = []
        self.remote_calls: list[list[str]] = []
        self.sessions: list[AgentSession] = []
        self.liveness: dict[str, Liveness] = {}
        self.connection = ConnectionInfo(
            workspace=self.ws, host="127.0.0.1", port=2222, username="v",
            identity_file=self.tmp / "key", project_root=self.sandbox)
        self.resolve = mock.patch("asb.runtime.sandbox.resolve_connection",
                                  side_effect=self._resolve)
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.unreachable = False

    # -- colaboradores falsos ---------------------------------------------------

    def _resolve(self, workspace):
        self.assertEqual(workspace, self.ws)
        if self.unreachable:
            raise podman.PodmanError("container ausente")
        return self.connection

    def _assert_never_forced(self) -> None:
        for argv in self.calls:
            for word in _FORBIDDEN:
                self.assertNotIn(word, argv)
            self.assertNotIn("origin", argv)

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.assertIs(kwargs["shell"], False)
        self.assertGreater(kwargs["timeout"], 0)
        args = tuple(argv[3:])
        for key, hook in self.before.items():
            if args[:len(key)] == key:
                hook()
        for key, fault in self.faults.items():
            if args[:len(key)] == key:
                if fault is OSError:
                    raise OSError("injected")
                return subprocess.CompletedProcess(argv, fault, b"",
                                                   b"error: injected")
        result = subprocess.run(argv, **kwargs)
        for key, hook in self.after.items():
            if args[:len(key)] == key:
                hook()
        return result

    def repository(self, path: Path) -> GitRepository:
        return GitRepository(path, runner=self.runner)

    def remote(self, connection, argv):
        self.remote_calls.append(list(argv))
        self.on_remote()
        if self.remote_fault is OSError:
            raise OSError("ssh failed")
        if self.remote_fault is not None:
            return subprocess.CompletedProcess(argv, self.remote_fault, "",
                                               "boom")
        return subprocess.run(list(argv), capture_output=True, text=True,
                              check=False)

    remote_fault = None

    def on_remote(self) -> None:
        pass

    def purge_runner(self, argv):
        self.purge_argv.append(list(argv))
        if self.purge_code is OSError:
            raise OSError("asb-agent missing")
        if self.purge_code == 0 and not self.purge_leaves_sandbox:
            shutil.rmtree(self.sandbox.parent)
            self.absent = True
        return subprocess.CompletedProcess(argv, self.purge_code, "",
                                           "purge refused\n")

    purge_leaves_sandbox = False

    def runtime(self) -> SandboxRuntime:
        runtime = SandboxRuntime(root=self.tmp / "asb", registry=self.registry,
                                 runner=self.purge_runner,
                                 repository=self.repository,
                                 remote=self.remote)
        runtime.sandbox_absent = lambda binding: self.absent
        return runtime

    def manager(self, **kwargs) -> CheckoutManager:
        return CheckoutManager(
            self.registry, repository=self.repository,
            agent_root=self.tmp / "home" / "asb-agent",
            runtime=kwargs.pop("runtime", None) or self.runtime(),
            sessions=lambda checkout_id: [
                s for s in self.sessions if s.checkout_id == checkout_id],
            liveness=lambda binding, session: self.liveness[session.id],
            **kwargs)

    # -- cenario --------------------------------------------------------------

    def commit_on(self, where: Path, name: str, text: str | None = None) -> str:
        (where / name).write_text(text or name, encoding="utf-8")
        git(where, "add", name)
        git(where, "commit", "-q", "-m", name)
        return git(where, "rev-parse", "HEAD")

    def session(self, state=SessionState.RUNNING, terminal=True):
        record = AgentSession.new(self.checkout_id, AgentKind.CODEX,
                                  self.sandbox, "work")
        record = record.with_state(
            state, terminal_id=(TerminalId(f"asb-{record.id}") if terminal
                                else None))
        self.sessions.append(record)
        return record

    def finish(self, target="main", cleanup=False, delete=False,
               **kwargs) -> FinishResult:
        return self.manager(**kwargs).finish(FinishCheckout(
            self.checkout_id, target, cleanup_after_merge=cleanup,
            delete_merged_branch=delete))

    def main_head(self) -> str:
        return git(self.repo, "rev-parse", "main")

    def branches(self) -> set[str]:
        return set(git(self.repo, "branch", "--format=%(refname:short)")
                   .splitlines())

    def reachable(self, commit: str) -> bool:
        return subprocess.run(
            ["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
             commit, "main"], capture_output=True).returncode == 0

    def assert_preserved(self, result: FinishResult, state: FinishState,
                         *, path=True) -> None:
        self.assertIs(result.state, state, result.message)
        if path:
            self.assertTrue(self.worktree.is_dir())
        self.assertIn("topic", self.branches())
        self.assertEqual(self.registry.checkout(self.checkout_id),
                         self.binding)
        self.assertEqual(self.purge_argv, [])

    def assert_cleaned(self, result: FinishResult, source: str) -> None:
        self.assertIs(result.state, FinishState.CLEANED, result.message)
        self.assertFalse(self.worktree.exists())
        with self.assertRaises(ProjectRegistryError):
            self.registry.checkout(self.checkout_id)
        self.assertTrue(self.reachable(source))


# -- evidencia antes de qualquer mutacao --------------------------------------------


class TestFinishRefusesBeforeMutation(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.agent_commit = self.commit_on(self.sandbox, "agent.txt")
        self.main_before = self.main_head()

    def assert_untouched(self, result: FinishResult, **kwargs) -> None:
        self.assert_preserved(result, FinishState.BLOCKED, **kwargs)
        self.assertEqual(self.main_head(), self.main_before)
        self.assertFalse([c for c in self.calls if "merge" in c[3:4]])

    def test_primary_checkout_is_refused(self):
        result = self.manager().finish(FinishCheckout(
            self.primary.checkout_id, "main"))
        self.assert_untouched(result)
        self.assertIn("primary", result.message)

    def test_dirty_source_is_refused(self):
        (self.worktree / "scratch.txt").write_text("x", encoding="utf-8")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("uncommitted", result.message)

    def test_detached_source_is_refused(self):
        git(self.worktree, "switch", "-q", "--detach")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("detached", result.message)

    def test_missing_source_path_is_refused(self):
        shutil.rmtree(self.worktree)
        result = self.finish()
        self.assert_untouched(result, path=False)
        self.assertIn("missing", result.message)

    def test_active_session_is_refused_and_never_stopped(self):
        session = self.session()
        self.liveness[session.id] = Liveness.ALIVE
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("active session", result.message)

    def test_unknown_liveness_is_refused(self):
        session = self.session(SessionState.DETACHED)
        self.liveness[session.id] = Liveness.UNKNOWN
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("liveness unknown", result.message)

    def test_session_without_a_terminal_cannot_be_proven_dead(self):
        self.session(SessionState.RECOVERY_REQUIRED, terminal=False)
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("liveness unknown", result.message)

    def test_invalid_target_branch_name_is_refused(self):
        result = self.finish(target="bad..name")
        self.assert_untouched(result)
        self.assertIn("invalid target branch", result.message)

    def test_missing_target_branch_is_refused(self):
        result = self.finish(target="nope")
        self.assert_untouched(result)
        self.assertIn("does not exist", result.message)

    def test_target_branch_without_a_checkout_is_refused(self):
        git(self.repo, "branch", "release")
        result = self.finish(target="release")
        self.assert_untouched(result)
        self.assertIn("no checkout has release", result.message)
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"),
                         "main")

    def test_dirty_target_checkout_is_refused(self):
        (self.repo / "wip.txt").write_text("wip", encoding="utf-8")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("target checkout", result.message)

    def test_target_equal_to_the_source_is_refused(self):
        result = self.finish(target="topic")
        self.assert_untouched(result)
        self.assertIn("itself on topic", result.message)

    def test_detached_sandbox_head_is_not_exported(self):
        git(self.sandbox, "switch", "-q", "--detach")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("detached", result.message)
        self.assertEqual(git(self.repo, "for-each-ref", "refs/asb"), "")

    def test_sandbox_branch_failing_validation_is_not_exported(self):
        git(self.sandbox, "update-ref", "refs/heads/-bad", "HEAD")
        git(self.sandbox, "symbolic-ref", "HEAD", "refs/heads/-bad")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("not a valid branch name", result.message)
        self.assertFalse([c for c in self.calls if "fetch" in c])

    def test_export_fetch_failure_blocks(self):
        self.faults[("fetch",)] = 1
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("fetch from the sandbox failed", result.message)

    def test_export_of_a_moving_branch_is_refused(self):
        self.before[("fetch",)] = lambda: self.commit_on(self.sandbox, "late")
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("moved during the export", result.message)

    def test_unreachable_sandbox_blocks(self):
        self.unreachable = True
        result = self.finish()
        self.assert_untouched(result)
        self.assertIn("not reachable", result.message)

    def test_finish_without_runtime_and_liveness_is_refused(self):
        manager = CheckoutManager(self.registry, repository=self.repository)
        result = manager.finish(FinishCheckout(self.checkout_id, "main"))
        self.assert_untouched(result)
        self.assertIn("needs the sandbox runtime", result.message)


# -- export ----------------------------------------------------------------------


class TestExport(_Case):
    def test_exports_the_exact_head_of_a_differently_named_sandbox_branch(self):
        git(self.sandbox, "switch", "-q", "-c", "agent/work")
        head = self.commit_on(self.sandbox, "agent.txt")
        commit, ref = self.runtime().export_head(self.binding)
        self.assertEqual((commit, ref), (head, f"refs/asb/{self.ws}/agent/work"))
        self.assertEqual(git(self.repo, "rev-parse", ref), head)
        # O branch do operador nunca e escrito pelo export.
        self.assertEqual(git(self.repo, "rev-parse", "topic"),
                         git(self.worktree, "rev-parse", "HEAD"))
        [fetch] = [c for c in self.calls if "fetch" in c]
        self.assertEqual(fetch[3:], [
            "fetch", "--no-tags", "--no-write-fetch-head", "--",
            str(self.sandbox),
            f"+refs/heads/agent/work:refs/asb/{self.ws}/agent/work"])

    def test_successful_export_followed_by_merge(self):
        git(self.sandbox, "switch", "-q", "-c", "agent-work")
        head = self.commit_on(self.sandbox, "agent.txt")
        result = self.finish()
        self.assertIs(result.state, FinishState.MERGED, result.message)
        self.assertEqual(result.source_commit, head)
        self.assertEqual(result.target_commit, self.main_head())
        self.assertTrue(self.reachable(head))
        [merge] = [c for c in self.calls if c[3:4] == ["merge"]]
        self.assertEqual(merge, ["git", "-C", str(self.repo), "merge",
                                 "--no-edit", f"refs/asb/{self.ws}/agent-work"])
        # MERGED nao remove nada.
        self.assert_preserved(result, FinishState.MERGED)
        self.assertTrue(self.sandbox.is_dir())


# -- merge ---------------------------------------------------------------------


class TestMerge(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.agent_commit = self.commit_on(self.sandbox, "agent.txt")

    def test_conflict_keeps_git_conflict_state_and_removes_nothing(self):
        for index in range(6):
            name = f"file{index}.txt"
            self.commit_on(self.sandbox, name, "agent\n")
            self.commit_on(self.repo, name, "operator\n")
        result = self.finish(cleanup=True, delete=True)
        self.assert_preserved(result, FinishState.CONFLICT)
        self.assertIn("(+1 more)", result.message)
        self.assertIn("merge --abort", result.message)
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())
        self.assertNotEqual(git(self.repo, "ls-files", "-u"), "")
        self.assertTrue(self.sandbox.is_dir())

    def test_merge_failure_without_conflict_blocks(self):
        self.faults[("merge",)] = 1
        result = self.finish(cleanup=True)
        self.assert_preserved(result, FinishState.BLOCKED)
        self.assertIn("nothing was removed", result.message)

    def test_merge_exit_zero_without_ancestry_is_cleanup_pending(self):
        self.faults[("merge",)] = 0
        result = self.finish(cleanup=True, delete=True)
        self.assert_preserved(result, FinishState.CLEANUP_PENDING)
        self.assertIn("integration is not proven", result.message)
        self.assertFalse(self.reachable(self.agent_commit))

    def test_unreadable_ancestry_after_merge_is_cleanup_pending(self):
        self.faults[("merge-base",)] = 128
        result = self.finish(cleanup=True)
        self.assert_preserved(result, FinishState.CLEANUP_PENDING)
        self.assertIn("integration is not proven", result.message)

    def test_operator_commit_in_the_worktree_must_also_be_integrated(self):
        own = self.commit_on(self.worktree, "operator.txt")
        result = self.finish(cleanup=True)
        self.assert_preserved(result, FinishState.CLEANUP_PENDING)
        self.assertFalse(self.reachable(own))

    def test_ancestry_proven_without_cleanup_is_merged(self):
        result = self.finish()
        self.assert_preserved(result, FinishState.MERGED)
        self.assertTrue(self.reachable(self.agent_commit))
        self.assertIn("cleanup available", result.message)

    def test_dead_and_final_sessions_do_not_block(self):
        dead = self.session()
        self.liveness[dead.id] = Liveness.DEAD
        self.session(SessionState.COMPLETED, terminal=False)
        result = self.finish()
        self.assertIs(result.state, FinishState.MERGED, result.message)

    def test_sessions_of_an_absent_sandbox_do_not_block(self):
        self.session()  # sem liveness: a sonda levantaria KeyError
        runtime = self.runtime()
        runtime.sandbox_absent = lambda binding: True
        result = self.finish(runtime=runtime)
        # O export ainda exige o sandbox vivo: ausente de verdade bloquearia
        # ali; aqui so a checagem de sessoes olha a ausencia.
        self.assertIs(result.state, FinishState.MERGED, result.message)


# -- limpeza depois da prova --------------------------------------------------------


class TestCleanupAfterProof(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.agent_commit = self.commit_on(self.sandbox, "agent.txt")

    def test_success_purges_removes_and_keeps_the_branch_by_default(self):
        result = self.finish(cleanup=True)
        self.assert_cleaned(result, self.agent_commit)
        self.assertEqual(self.purge_argv, [[
            str(self.tmp / "asb" / "cli" / "asb-agent"), "purge",
            "--workspace", self.ws, "--yes"]])
        self.assertIn("topic", self.branches())
        self.assertEqual(self.registry.checkout(self.primary.checkout_id),
                         self.primary)
        [remove] = [c for c in self.calls if c[3:5] == ["worktree", "remove"]]
        self.assertEqual(remove[3:], ["worktree", "remove", str(self.worktree)])

    def test_branch_deletion_enabled_uses_lowercase_d_and_keeps_remotes(self):
        topic = git(self.repo, "rev-parse", "topic")
        git(self.repo, "update-ref", "refs/remotes/origin/topic", topic)
        result = self.finish(cleanup=True, delete=True)
        self.assert_cleaned(result, self.agent_commit)
        self.assertNotIn("topic", self.branches())
        self.assertIn("deleted branch topic", result.message)
        self.assertEqual(git(self.repo, "rev-parse", "refs/remotes/origin/topic"),
                         topic)
        deletes = [c[3:] for c in self.calls if c[3:4] == ["branch"]]
        self.assertEqual(deletes, [["branch", "-d", "topic"]])

    def test_branch_deletion_refused_by_git_is_reported_not_failed(self):
        self.faults[("branch", "-d")] = 1
        result = self.finish(cleanup=True, delete=True)
        self.assert_cleaned(result, self.agent_commit)
        self.assertIn("git refused to delete branch topic", result.message)
        self.assertIn("topic", self.branches())

    def test_branch_that_moved_after_the_proof_is_kept(self):
        self.before[("worktree", "remove")] = lambda: self.commit_on(
            self.worktree, "late.txt")
        result = self.finish(cleanup=True, delete=True)
        self.assertIs(result.state, FinishState.CLEANED, result.message)
        self.assertIn("not integrated; kept", result.message)
        self.assertIn("topic", self.branches())

    def test_branch_already_deleted_is_skipped(self):
        self.after[("worktree", "remove")] = lambda: git(
            self.repo, "update-ref", "-d", "refs/heads/topic")
        result = self.finish(cleanup=True, delete=True)
        self.assertIs(result.state, FinishState.CLEANED, result.message)
        self.assertIn("branch topic already deleted", result.message)

    def test_branch_that_cannot_be_read_is_kept(self):
        # O export tambem le `refs/heads/topic` (no clone): a falha so vale
        # depois da remocao do worktree.
        self.after[("worktree", "remove")] = lambda: self.faults.__setitem__(
            ("rev-parse", "--verify", "--quiet",
             "refs/heads/topic^{commit}"), OSError)
        result = self.finish(cleanup=True, delete=True)
        self.assertIs(result.state, FinishState.CLEANED, result.message)
        self.assertIn("branch topic kept", result.message)
        self.assertIn("topic", self.branches())

    def test_absent_sandbox_skips_the_purge(self):
        self.absent = True
        result = self.finish(cleanup=True)
        self.assert_cleaned(result, self.agent_commit)
        self.assertEqual(self.purge_argv, [])
        self.assertIn("already absent", result.message)

    def _pending_on_guard(self, fragment: str) -> None:
        result = self.finish(cleanup=True, delete=True)
        self.assert_preserved(result, FinishState.CLEANUP_PENDING)
        self.assertTrue(self.reachable(self.agent_commit))
        self.assertRegex(result.message, fragment)
        self.assertTrue(self.sandbox.is_dir())

    def test_dirty_sandbox_is_not_purged(self):
        (self.sandbox / "untracked.txt").write_text("x", encoding="utf-8")
        self._pending_on_guard("uncommitted changes")
        [status] = self.remote_calls
        self.assertEqual(status, ["git", "-C", str(self.sandbox), "status",
                                  "--porcelain=v1", "-z",
                                  "--untracked-files=all"])

    def test_sandbox_head_moved_after_export_is_not_purged(self):
        self.before[("merge",)] = lambda: self.commit_on(self.sandbox, "late")
        self._pending_on_guard("moved to")

    def test_unexported_sandbox_branch_is_not_purged(self):
        git(self.sandbox, "switch", "-q", "-c", "side")
        self.commit_on(self.sandbox, "side.txt")
        git(self.sandbox, "switch", "-q", "topic")
        self._pending_on_guard(r"refs/heads/side \(\w+\) was never exported")

    def test_sandbox_branch_exported_but_not_integrated_is_not_purged(self):
        # Um commit que o operador conhece (branch `other`) mas que nao
        # esta em `main`, trazido para um branch do sandbox.
        other = git(self.repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD",
                    "-m", "other")
        git(self.repo, "update-ref", "refs/heads/other", other)
        git(self.sandbox, "fetch", "-q", str(self.repo),
            "refs/heads/other:refs/heads/foreign")
        self._pending_on_guard(
            r"refs/heads/foreign \(\w+\) is not integrated into the target")

    def test_sandbox_stash_is_not_purged(self):
        (self.sandbox / "agent.txt").write_text("edited", encoding="utf-8")
        git(self.sandbox, "stash", "push", "-q", "-m", "asb-test-stash")
        self._pending_on_guard(r"refs/stash \(\w+\) was never exported")

    def test_sandbox_with_an_extra_worktree_is_not_purged(self):
        git(self.sandbox, "worktree", "add", "-q", "--detach",
            str(self.tmp / "sandbox" / "extra"))
        self._pending_on_guard("extra worktree")

    def test_sandbox_status_that_fails_is_not_purged(self):
        self.remote_fault = 255
        self._pending_on_guard("git status failed in the sandbox")

    def test_sandbox_status_that_cannot_run_is_not_purged(self):
        self.remote_fault = OSError
        self._pending_on_guard("could not read the sandbox status")

    def test_sandbox_unreachable_at_purge_time_is_not_purged(self):
        self.before[("merge",)] = lambda: setattr(self, "unreachable", True)
        self._pending_on_guard("not reachable")

    def test_sandbox_head_that_cannot_be_read_is_not_purged(self):
        # Depois da prova (no status remoto), o HEAD do clone fica ilegivel.
        self.on_remote = lambda: self.faults.__setitem__(
            ("rev-parse", "--verify", "--quiet", "HEAD^{commit}"), 1)
        self._pending_on_guard("could not read HEAD")

    def test_sandbox_refs_that_cannot_be_listed_are_not_purged(self):
        self.faults[("for-each-ref",)] = 1
        self._pending_on_guard("for-each-ref failed")

    def test_purge_failure_is_cleanup_pending(self):
        self.purge_code = 1
        result = self.finish(cleanup=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("purge refused", result.message)
        self.assertTrue(self.worktree.is_dir())
        self.assertEqual(self.registry.checkout(self.checkout_id),
                         self.binding)
        self.assertTrue(self.reachable(self.agent_commit))

    def test_purge_that_cannot_run_is_cleanup_pending(self):
        self.purge_code = OSError
        result = self.finish(cleanup=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("could not run 'asb-agent purge'", result.message)
        self.assertTrue(self.worktree.is_dir())

    def test_purge_exit_zero_without_absence_is_cleanup_pending(self):
        self.purge_leaves_sandbox = True
        result = self.finish(cleanup=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("still exists", result.message)
        self.assertTrue(self.worktree.is_dir())

    def test_worktree_removal_failure_then_retry_resumes(self):
        self.faults[("worktree", "remove")] = 1
        result = self.finish(cleanup=True, delete=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("git refused to remove", result.message)
        self.assertTrue(self.worktree.is_dir())
        self.assertIn("topic", self.branches())
        self.assertTrue(self.absent)  # o purge ja aconteceu

        del self.faults[("worktree", "remove")]
        retry = self.manager().cleanup(self.checkout_id,
                                       delete_merged_branch=True)
        self.assert_cleaned(retry, self.agent_commit)
        self.assertEqual(len(self.purge_argv), 1)  # nunca repetido
        self.assertIn("already absent", retry.message)
        self.assertNotIn("topic", self.branches())

    def test_worktree_removal_that_cannot_run_is_cleanup_pending(self):
        self.faults[("worktree", "remove")] = OSError
        result = self.finish(cleanup=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("could not remove", result.message)
        self.assertTrue(self.worktree.is_dir())

    def test_retry_after_git_removed_the_worktree_reconciles_the_record(self):
        with mock.patch.object(ProjectRegistry, "unbind_checkout",
                               side_effect=ProjectRegistryError("disk full")):
            result = self.finish(cleanup=True)
        self.assertIs(result.state, FinishState.CLEANUP_PENDING)
        self.assertIn("could not remove the registry binding", result.message)
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.registry.checkout(self.checkout_id),
                         self.binding)

        retry = self.manager().cleanup(self.checkout_id,
                                       delete_merged_branch=True)
        self.assert_cleaned(retry, self.agent_commit)
        self.assertIn("local branch unknown", retry.message)
        self.assertIn("topic", self.branches())
        self.assertEqual(len(self.purge_argv), 1)


# -- cleanup sem merge (merge externo e recuperacao) --------------------------------


class TestCleanupWithoutMerge(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.agent_commit = self.commit_on(self.sandbox, "agent.txt")

    def external_merge(self) -> None:
        """O operador integra por fora: `pull` + `merge` manuais."""
        ref = f"refs/asb/{self.ws}/topic"
        git(self.repo, "fetch", "-q", str(self.sandbox),
            f"refs/heads/topic:{ref}")
        git(self.repo, "merge", "-q", "--no-edit", ref)

    def test_external_merge_is_labelled_and_cleaned(self):
        manager = self.manager()
        self.assertFalse(manager.merged(self.checkout_id))
        self.external_merge()
        self.assertTrue(manager.merged(self.checkout_id))
        result = manager.cleanup(self.checkout_id)
        self.assert_cleaned(result, self.agent_commit)
        self.assertEqual(len(self.purge_argv), 1)

    def test_finish_after_an_external_merge_is_merged(self):
        self.external_merge()
        result = self.finish()
        self.assertIs(result.state, FinishState.MERGED, result.message)

    def test_merged_label_needs_every_export_ref_integrated(self):
        self.external_merge()
        git(self.sandbox, "switch", "-q", "-c", "more")
        self.commit_on(self.sandbox, "more.txt")
        self.runtime().export_head(self.binding)
        self.assertFalse(self.manager().merged(self.checkout_id))

    def test_merged_label_is_false_for_the_primary_and_unknown_ids(self):
        manager = self.manager()
        self.assertFalse(manager.merged(self.primary.checkout_id))
        from asb.checkouts.model import CheckoutId
        self.assertFalse(manager.merged(CheckoutId("c-unknown")))

    def test_cleanup_of_an_unintegrated_worktree_is_blocked(self):
        own = self.commit_on(self.worktree, "operator.txt")
        result = self.manager().cleanup(self.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED)
        self.assertIn("not integrated", result.message)
        self.assertEqual(result.source_commit, own)

    def test_cleanup_of_the_primary_is_blocked(self):
        result = self.manager().cleanup(self.primary.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED)
        self.assertIn("primary", result.message)

    def test_cleanup_with_an_active_session_is_blocked(self):
        self.external_merge()
        session = self.session()
        self.liveness[session.id] = Liveness.ALIVE
        result = self.manager().cleanup(self.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED)
        self.assertIn("active session", result.message)

    def test_missing_path_without_evidence_is_blocked(self):
        git(self.repo, "worktree", "remove", str(self.worktree))
        result = self.manager().cleanup(self.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED, path=False)
        self.assertIn("manual recovery", result.message)

    def test_missing_path_with_an_unintegrated_export_is_blocked(self):
        self.runtime().export_head(self.binding)
        git(self.repo, "worktree", "remove", str(self.worktree))
        result = self.manager().cleanup(self.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED, path=False)
        self.assertIn("is not integrated", result.message)

    def test_path_listed_by_git_but_gone_is_blocked(self):
        self.external_merge()
        shutil.rmtree(self.worktree)
        result = self.manager().cleanup(self.checkout_id)
        self.assert_preserved(result, FinishState.BLOCKED, path=False)
        self.assertIn("missing", result.message)

    def test_cleanup_to_an_invalid_target_is_blocked(self):
        result = self.manager().cleanup(self.checkout_id, "bad..name")
        self.assert_preserved(result, FinishState.BLOCKED)


# -- previa da confirmacao da TUI -------------------------------------------------


class TestFinishPreview(_Case):
    def test_preview_names_the_source_commit_and_the_clean_target(self):
        before = list(self.calls)
        preview = self.manager().finish_preview(self.checkout_id, "main")
        self.assertEqual(preview, FinishPreview(
            self.worktree, "topic", git(self.worktree, "rev-parse", "HEAD"),
            self.ws, "main", self.repo))
        written = [c for c in self.calls[len(before):]
                   if c[3] in ("merge", "fetch", "worktree", "branch")
                   and c[3:5] != ["worktree", "list"]]
        self.assertEqual(written, [])

    def test_cleanup_preview_needs_no_clean_target_checkout(self):
        git(self.repo, "branch", "release")
        preview = self.manager().finish_preview(self.checkout_id, "release",
                                                merge=False)
        self.assertIsNone(preview.target_path)
        (self.repo / "wip.txt").write_text("wip", encoding="utf-8")
        preview = self.manager().finish_preview(self.checkout_id, "main",
                                                merge=False)
        self.assertEqual(preview.target_path, self.repo)

    def test_preview_refuses_what_finish_refuses(self):
        (self.worktree / "scratch.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(CheckoutError, "uncommitted"):
            self.manager().finish_preview(self.checkout_id, "main")

    def test_preview_of_an_unknown_checkout_is_a_checkout_error(self):
        with self.assertRaisesRegex(CheckoutError, "unknown checkout"):
            self.manager().finish_preview(CheckoutId("c-unknown"), "main")

    def test_preview_with_an_unreadable_head_is_a_checkout_error(self):
        self.faults[("rev-parse", "--verify", "--quiet", "HEAD^{commit}")] = 1
        with self.assertRaisesRegex(CheckoutError, "could not read HEAD"):
            self.manager().finish_preview(self.checkout_id, "main")


if __name__ == "__main__":
    unittest.main()
