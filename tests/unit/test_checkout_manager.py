"""Testes de `asb.checkouts.manager` (Tarefa 11): listagem, inspecao e a
transacao de criacao de worktree, contra repositorios Git REAIS e um
`ProjectRegistry` real num diretorio temporario.

Configuracao global/de sistema do Git isolada. Todo argv de Git passa por
um runner que o registra (e que, so onde um Git real nao falha sob
demanda, injeta a falha); nenhum argv pode conter `--force`.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from test_checkout_git import git, init_repo, isolate_git  # noqa: E402

from asb.checkouts.git import GitRepository  # noqa: E402
from asb.checkouts.manager import (  # noqa: E402
    CheckoutError, CheckoutManager, CreateCheckout,
)
from asb.checkouts.model import CheckoutKind, CheckoutState  # noqa: E402
from asb.projects.registry import (  # noqa: E402
    ProjectRegistry, ProjectRegistryError,
)


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        isolate_git(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = init_repo(self.tmp / "repo")
        self.base_commit = git(self.repo, "rev-parse", "HEAD")
        self.root = self.tmp / "wts"
        self.agent_root = self.tmp / "home" / "asb-agent"
        self.registry = ProjectRegistry(self.tmp / "state" / "projects.json")
        self.project = self.registry.add(self.repo, "main", self.root)
        self.primary = self.registry.register_checkout(self.project.id,
                                                       self.repo)
        self.calls: list[list[str]] = []
        # argv -> (codigo, efeito) para simular uma falha pontual.
        self.faults: dict[tuple[str, ...], tuple[int, object]] = {}
        self.addCleanup(self._assert_never_forced)

    def _assert_never_forced(self) -> None:
        for argv in self.calls:
            self.assertNotIn("--force", argv)
            self.assertNotIn("-f", argv)

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.assertIs(kwargs["shell"], False)
        self.assertTrue(kwargs["capture_output"])
        self.assertGreater(kwargs["timeout"], 0)
        fault = self.faults.get(tuple(argv[3:]))
        if fault is not None:
            code, effect = fault
            if callable(effect):
                effect()
            return subprocess.CompletedProcess(argv, code, b"", b"injected")
        return subprocess.run(argv, **kwargs)

    def repository(self, path: Path) -> GitRepository:
        return GitRepository(path, runner=self.runner)

    def manager(self, **kwargs) -> CheckoutManager:
        return CheckoutManager(self.registry, repository=self.repository,
                               agent_root=self.agent_root, **kwargs)

    def request(self, branch="topic", base="main", path=None) -> CreateCheckout:
        return CreateCheckout(self.project.id, branch, base,
                              path if path is not None else self.root / branch)

    def registry_text(self) -> str:
        return self.registry.path.read_text(encoding="utf-8")

    def branches(self) -> set[str]:
        return set(git(self.repo, "branch", "--format=%(refname:short)")
                   .splitlines())

    def commit_on(self, where: Path, name: str) -> str:
        (where / name).write_text(name, encoding="utf-8")
        git(where, "add", name)
        git(where, "commit", "-q", "-m", name)
        return git(where, "rev-parse", "HEAD")


# -- criacao: caminho feliz --------------------------------------------------------


class TestCreate(_Case):
    def test_creates_from_the_configured_base_and_registers_after_git(self):
        manager = self.manager()
        preview = manager.preview(self.request())
        self.assertEqual(preview.base, "main")
        self.assertEqual(preview.base_commit, self.base_commit)
        self.assertEqual(preview.path, self.root / "topic")
        self.assertTrue(preview.creates_branch)
        self.assertFalse(self.root.exists())  # preview nao escreve nada

        checkout = manager.create(self.request())

        target = self.root / "topic"
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(git(target, "rev-parse", "HEAD"), self.base_commit)
        self.assertEqual(git(target, "symbolic-ref", "--short", "HEAD"),
                         "topic")
        binding = self.registry.checkout(checkout.id)
        self.assertEqual(binding.source_path, target)
        self.assertEqual(checkout.path, target)
        self.assertEqual(checkout.kind, CheckoutKind.WORKTREE)
        self.assertEqual(checkout.branch, "topic")
        self.assertEqual(checkout.state, CheckoutState.CLEAN)
        self.assertEqual(checkout.workspace, binding.workspace)

    def test_the_create_argv_is_exactly_the_contract(self):
        self.manager().create(self.request(branch="feat/x",
                                           path=self.root / "feat-x"))
        adds = [argv for argv in self.calls if argv[3:5] == ["worktree", "add"]]
        self.assertEqual(adds, [[
            "git", "-C", str(self.repo), "worktree", "add", "-b", "feat/x",
            str(self.root / "feat-x"), "main"]])

    def test_an_explicit_base_from_the_selected_checkout(self):
        other = self.tmp / "wts-other"
        git(self.repo, "worktree", "add", "-q", "-b", "stack", str(other))
        tip = self.commit_on(other, "stacked.txt")

        preview = self.manager().preview(self.request(base="stack"))
        checkout = self.manager().create(self.request(base="stack"))

        self.assertEqual(preview.base_commit, tip)
        self.assertEqual(git(checkout.path, "rev-parse", "HEAD"), tip)

    def test_a_path_with_spaces_is_created_and_registered(self):
        target = self.root / "with space"
        checkout = self.manager().create(self.request(path=target))
        self.assertEqual(self.registry.checkout(checkout.id).source_path,
                         target)

    def test_the_default_path_replaces_slashes(self):
        self.assertEqual(self.manager().default_path(self.project, "feat/a/b"),
                         self.project.worktree_root / "feat-a-b")


# -- criacao: recusas antes de qualquer escrita --------------------------------------


class TestRefusals(_Case):
    def assert_refused(self, request, needle, manager=None):
        manager = manager or self.manager()
        before = (self.registry_text(), self.branches())
        for action in (manager.preview, manager.create):
            with self.subTest(action=action.__name__), \
                    self.assertRaises(CheckoutError) as ctx:
                action(request)
            self.assertIn(needle, str(ctx.exception))
        self.assertEqual((self.registry_text(), self.branches()), before)
        self.assertFalse(any(argv[3:5] == ["worktree", "add"]
                             for argv in self.calls))

    def test_an_unresolvable_configured_base_demands_an_explicit_choice(self):
        for base in ("trunk", "-x", ""):
            with self.subTest(base=base):
                self.assert_refused(self.request(base=base), "choose a base")
        self.assertFalse(self.root.exists())

    def test_an_invalid_branch_name(self):
        for name in ("@{-1}", "a..b", "-x", "", "HEAD"):
            with self.subTest(name=name):
                self.assert_refused(self.request(branch=name,
                                                 path=self.root / "p"),
                                    "invalid branch")

    def test_an_existing_branch(self):
        git(self.repo, "branch", "topic")
        self.assert_refused(self.request(), "already exists")

    def test_an_existing_path(self):
        self.root.mkdir()
        (self.root / "topic").write_text("x", encoding="utf-8")
        self.assert_refused(self.request(), "already exists")

    def test_a_path_outside_the_root_even_through_a_symlink(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        self.root.mkdir()
        (self.root / "link").symlink_to(outside)
        for path in (outside / "topic", self.root / "link" / "topic",
                     self.root / ".." / "topic", self.root):
            with self.subTest(path=path):
                self.assert_refused(self.request(path=path), "outside")

    def test_a_relative_path(self):
        self.assert_refused(self.request(path=Path("wts/topic")), "absolute")

    def test_a_root_inside_the_agent_mount(self):
        manager = CheckoutManager(self.registry, repository=self.repository,
                                  agent_root=self.tmp)
        self.assert_refused(self.request(), "agent-writable", manager)

    def test_a_project_record_of_another_repository(self):
        foreign = init_repo(self.tmp / "foreign")
        raw = json.loads(self.registry_text())
        raw["projects"][0]["gitCommonDir"] = str(foreign / ".git")
        self.registry.path.write_text(json.dumps(raw), encoding="utf-8")
        self.assert_refused(self.request(), "another repository")


# -- criacao: falhas e rollback ------------------------------------------------------


class TestTransaction(_Case):
    def add_argv(self, request) -> tuple[str, ...]:
        return ("worktree", "add", "-b", request.branch, str(request.path),
                request.base)

    def assert_nothing_registered(self, before: str) -> None:
        self.assertEqual(self.registry_text(), before)

    def test_git_failing_before_creating_anything_rolls_nothing_back(self):
        request = self.request()
        self.faults[self.add_argv(request)] = (128, None)
        before = self.registry_text()

        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(request)

        self.assertIn("injected", str(ctx.exception))
        self.assertNotIn("topic", self.branches())
        self.assertFalse(any("-D" in argv for argv in self.calls))
        self.assert_nothing_registered(before)

    def test_git_failing_after_creating_the_branch_deletes_only_that_branch(self):
        # Git real: cria o branch e so depois falha ao criar o diretorio
        # (o pai e um arquivo); o caminho nunca chega a existir.
        self.root.mkdir(mode=0o700)
        (self.root / "file").write_text("x", encoding="utf-8")
        request = self.request(path=self.root / "file" / "topic")
        before = self.registry_text()

        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(request)

        self.assertNotIn("topic", self.branches())
        self.assertIn(["git", "-C", str(self.repo), "branch", "-D", "topic"],
                      self.calls)
        self.assertIn("removed branch topic", str(ctx.exception))
        self.assert_nothing_registered(before)

    def test_the_real_git_cause_reaches_the_operator(self):
        # Rodada 1: `worktree add` imprime "Preparing worktree" primeiro;
        # a causa e a linha `fatal:` que vem depois.
        self.root.mkdir(mode=0o700)
        (self.root / "file").write_text("x", encoding="utf-8")
        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(
                self.request(path=self.root / "file" / "topic"))
        message = str(ctx.exception)
        self.assertIn("fatal: could not create leading directories", message)
        self.assertNotIn("Preparing worktree", message)

    def test_a_failing_hook_message_reaches_the_operator(self):
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\necho 'hook: lint failed' >&2\nexit 3\n",
                        encoding="utf-8")
        hook.chmod(0o755)
        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())
        message = str(ctx.exception)
        self.assertIn("hook: lint failed", message)
        self.assertNotIn("Preparing worktree", message)
        self.assertIn(f"left {self.root / 'topic'}", message)

    def test_a_base_that_moved_after_the_preview_is_refused(self):
        manager = self.manager()
        preview = manager.preview(self.request())
        self.commit_on(self.repo, "moved.txt")  # main anda depois da previa
        before = self.registry_text()

        with self.assertRaises(CheckoutError) as ctx:
            manager.create(replace(self.request(),
                                   base_commit=preview.base_commit))

        self.assertIn("moved", str(ctx.exception))
        self.assertIn(preview.base_commit, str(ctx.exception))
        self.assertFalse((self.root / "topic").exists())
        self.assertNotIn("topic", self.branches())
        self.assertFalse(any(argv[3:5] == ["worktree", "add"]
                             for argv in self.calls))
        self.assert_nothing_registered(before)

    def test_the_confirmed_base_commit_is_used_when_it_still_matches(self):
        manager = self.manager()
        preview = manager.preview(self.request())
        checkout = manager.create(replace(self.request(),
                                          base_commit=preview.base_commit))
        self.assertEqual(git(checkout.path, "rev-parse", "HEAD"),
                         preview.base_commit)

    def test_a_branch_not_at_the_base_is_not_proven_ours_and_is_kept(self):
        other = self.commit_on(self.repo, "moved.txt")
        git(self.repo, "reset", "-q", "--hard", self.base_commit)
        request = self.request()
        self.faults[self.add_argv(request)] = (
            128, lambda: git(self.repo, "branch", "topic", other))

        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(request)

        self.assertIn("topic", self.branches())
        self.assertFalse(any("-D" in argv for argv in self.calls))
        self.assertIn("left untouched", str(ctx.exception))

    def test_git_failing_with_the_worktree_present_touches_nothing(self):
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        hook.chmod(0o755)
        before = self.registry_text()

        with self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())

        self.assertTrue((self.root / "topic").is_dir())
        self.assertIn("topic", self.branches())
        self.assertFalse(any(argv[3:5] == ["worktree", "remove"]
                             or "-D" in argv for argv in self.calls))
        self.assertIn(str(self.root / "topic"), str(ctx.exception))
        self.assert_nothing_registered(before)

    def test_a_failed_inspection_removes_the_worktree_and_the_branch(self):
        class Blind(GitRepository):
            def worktrees(self):
                return [wt for wt in super().worktrees() if wt.primary]

        manager = CheckoutManager(
            self.registry, agent_root=self.agent_root,
            repository=lambda path: Blind(path, runner=self.runner))
        before = self.registry_text()

        with self.assertRaises(CheckoutError) as ctx:
            manager.create(self.request())

        self.assertIn("not listed", str(ctx.exception))
        self.assertFalse((self.root / "topic").exists())
        self.assertNotIn("topic", self.branches())
        self.assertIn(["git", "-C", str(self.repo), "worktree", "remove",
                       str(self.root / "topic")], self.calls)
        self.assert_nothing_registered(before)

    def test_a_registry_failure_removes_the_worktree_and_the_branch(self):
        before = self.registry_text()
        with mock.patch.object(self.registry, "register_checkout",
                               side_effect=ProjectRegistryError("disk full")
                               ) as register, \
                self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())

        register.assert_called_once_with(self.project.id, self.root / "topic")
        self.assertIn("disk full", str(ctx.exception))
        self.assertFalse((self.root / "topic").exists())
        self.assertNotIn("topic", self.branches())
        self.assert_nothing_registered(before)

    def test_a_refused_removal_is_reported_and_never_forced(self):
        target = self.root / "topic"

        def scribble(*_args):
            (target / "agent-wrote-this.txt").write_text("x", encoding="utf-8")
            raise ProjectRegistryError("disk full")

        with mock.patch.object(self.registry, "register_checkout",
                               side_effect=scribble), \
                self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())

        message = str(ctx.exception)
        self.assertIn("disk full", message)
        self.assertIn(f"left worktree {target}", message)
        self.assertIn("branch topic", message)
        self.assertTrue((target / "agent-wrote-this.txt").exists())
        self.assertIn("topic", self.branches())
        self.assertFalse(any("-D" in argv for argv in self.calls))


class TestRollbackEdges(_Case):
    def test_a_branch_that_appears_after_the_preview_is_not_ours(self):
        manager = self.manager()
        real_preview = manager.preview

        def racing_preview(request):
            preview = real_preview(request)
            git(self.repo, "branch", "topic")
            return preview

        with mock.patch.object(manager, "preview", side_effect=racing_preview), \
                self.assertRaises(CheckoutError) as ctx:
            manager.create(self.request())

        self.assertIn("nothing was created", str(ctx.exception))
        self.assertFalse(any(argv[3:5] == ["worktree", "add"]
                             or "-D" in argv for argv in self.calls))
        self.assertIn("topic", self.branches())

    def test_a_worktree_on_the_wrong_commit_is_rolled_back(self):
        class Shifted(GitRepository):
            def worktrees(self):
                return [replace(wt, head="0" * 40) if not wt.primary else wt
                        for wt in super().worktrees()]

        manager = CheckoutManager(
            self.registry, agent_root=self.agent_root,
            repository=lambda path: Shifted(path, runner=self.runner))

        with self.assertRaises(CheckoutError) as ctx:
            manager.create(self.request())

        self.assertIn("expected topic", str(ctx.exception))
        self.assertFalse((self.root / "topic").exists())
        self.assertNotIn("topic", self.branches())

    def test_a_removal_git_cannot_run_is_reported(self):
        target = self.root / "topic"

        def unavailable():
            raise OSError("git vanished")

        self.faults[("worktree", "remove", str(target))] = (0, unavailable)
        with mock.patch.object(self.registry, "register_checkout",
                               side_effect=ProjectRegistryError("disk full")), \
                self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())

        self.assertIn("git vanished", str(ctx.exception))
        self.assertIn(f"left worktree {target}", str(ctx.exception))
        self.assertTrue(target.is_dir())
        self.assertIn("topic", self.branches())

    def test_a_branch_deletion_git_refuses_is_reported(self):
        self.faults[("branch", "-D", "topic")] = (1, None)
        with mock.patch.object(self.registry, "register_checkout",
                               side_effect=ProjectRegistryError("disk full")), \
                self.assertRaises(CheckoutError) as ctx:
            self.manager().create(self.request())

        self.assertIn("could not remove branch topic", str(ctx.exception))
        self.assertFalse((self.root / "topic").exists())

    def test_a_branch_check_git_cannot_run_is_reported(self):
        def unavailable():
            raise OSError("git vanished")

        request = self.request()
        manager = self.manager()
        real_preview = manager.preview

        def then_break(req):
            preview = real_preview(req)
            # So a verificacao do rollback (depois do add) quebra: a leitura
            # de "antes" ja passou quando o add roda.
            key = ("rev-parse", "--verify", "--quiet",
                   "refs/heads/topic^{commit}")

            def arm():
                self.faults[key] = (0, unavailable)

            self.faults[("worktree", "add", "-b", "topic", str(request.path),
                         "main")] = (128, arm)
            return preview

        with mock.patch.object(manager, "preview", side_effect=then_break), \
                self.assertRaises(CheckoutError) as ctx:
            manager.create(request)

        self.assertIn("git vanished", str(ctx.exception))


# -- listagem e inspecao ------------------------------------------------------------------


class TestList(_Case):
    def test_annotates_registered_unregistered_and_missing_without_writing(self):
        manager = self.manager()
        created = manager.create(self.request())
        outside = self.root / "external"
        git(self.repo, "worktree", "add", "-q", "-b", "external", str(outside))
        gone = manager.create(self.request(branch="gone"))
        shutil.rmtree(gone.path)
        before = self.registry_text()
        mtime = self.registry.path.stat().st_mtime_ns

        with mock.patch.object(self.registry, "register_checkout",
                               side_effect=AssertionError("list wrote")):
            listed = {entry.path: entry for entry in manager.list(self.project.id)}

        self.assertEqual(self.registry_text(), before)
        self.assertEqual(self.registry.path.stat().st_mtime_ns, mtime)
        self.assertEqual(set(listed), {self.repo, created.path, outside,
                                       gone.path})
        self.assertEqual(listed[self.repo].binding, self.primary)
        self.assertTrue(listed[self.repo].worktree.primary)
        self.assertEqual(listed[created.path].binding.checkout_id, created.id)
        self.assertIsNone(listed[outside].binding)
        self.assertEqual(listed[outside].worktree.branch, "external")
        self.assertFalse(listed[outside].missing)
        self.assertTrue(listed[gone.path].missing)
        self.assertTrue(listed[gone.path].worktree.prunable)

    def test_a_binding_git_no_longer_lists_is_missing(self):
        manager = self.manager()
        created = manager.create(self.request())
        git(self.repo, "worktree", "remove", str(created.path))

        [entry] = [e for e in manager.list(self.project.id)
                   if e.path == created.path]

        self.assertTrue(entry.missing)
        self.assertIsNone(entry.worktree)
        self.assertEqual(entry.binding.checkout_id, created.id)


class TestInspect(_Case):
    def test_clean_dirty_and_detached(self):
        manager = self.manager()
        created = manager.create(self.request())
        self.assertEqual(manager.inspect(created.id), created)
        self.assertEqual(manager.inspect(self.primary.checkout_id).kind,
                         CheckoutKind.PRIMARY)

        (created.path / "new.txt").write_text("x", encoding="utf-8")
        self.assertIs(manager.inspect(created.id).state, CheckoutState.DIRTY)
        (created.path / "new.txt").unlink()

        git(created.path, "checkout", "-q", "--detach")
        inspected = manager.inspect(created.id)
        self.assertIs(inspected.state, CheckoutState.DETACHED)
        self.assertEqual(inspected.branch,
                         git(created.path, "rev-parse", "--short", "HEAD"))

    def test_the_primary_kind_survives_an_unresolved_recorded_primary(self):
        raw = json.loads(self.registry_text())
        raw["projects"][0]["primary"] = str(self.repo / ".." / "repo")
        self.registry.path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(self.manager().inspect(self.primary.checkout_id).kind,
                         CheckoutKind.PRIMARY)

    def test_a_registered_path_git_does_not_list_is_an_error(self):
        sub = self.repo / "sub"
        sub.mkdir()
        binding = self.registry.register_checkout(self.project.id, sub)
        with self.assertRaises(CheckoutError) as ctx:
            self.manager().inspect(binding.checkout_id)
        self.assertIn("not a worktree", str(ctx.exception))

    def test_an_unreadable_branch_is_an_error(self):
        with mock.patch.object(GitRepository, "branch", return_value=None), \
                self.assertRaises(CheckoutError) as ctx:
            self.manager().inspect(self.primary.checkout_id)
        self.assertIn("could not read the branch", str(ctx.exception))

    def test_a_missing_checkout_is_an_error_not_a_state(self):
        manager = self.manager()
        created = manager.create(self.request())
        shutil.rmtree(created.path)
        with self.assertRaises(CheckoutError):
            manager.inspect(created.id)


if __name__ == "__main__":
    unittest.main()
