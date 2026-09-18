"""Testes do registro atomico de projetos (`asb.projects.registry`).

Cobre descoberta de identidade via git (dedup entre checkout primario e
worktree vinculado), leitura/escrita atomica sob lock exclusivo, rejeicao de
JSON invalido/schema desconhecido sem reescrever o arquivo, permissoes de
arquivo/diretorio, e o ciclo de vida de `CheckoutBinding`.

Nenhum teste toca Podman, systemd, tmux ou credenciais: repositorios git
temporarios sao criados de verdade com `subprocess.run`, o que o guarda de
isolamento da suite permite (ele so proibe nomear volumes reais do Podman).
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.model import CheckoutId  # noqa: E402
from asb.projects.model import Project, ProjectId  # noqa: E402
from asb.projects.registry import (  # noqa: E402
    CheckoutBinding, ProjectRegistry, ProjectRegistryError,
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    result = subprocess.run(["git", *args], cwd=str(cwd), env=env,
                            capture_output=True, text=True, shell=False)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-q"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "README.md"], path)
    _run_git(["commit", "-q", "-m", "init"], path)
    return path


def _linked_worktree(repo: Path, path: Path) -> Path:
    """Um worktree vinculado REAL de `repo`, num branch novo."""
    _run_git(["worktree", "add", "-q", "-b", path.name, str(path)], repo)
    return path


class ProjectRegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.tmp = Path(self._tempdir.name)
        self.registry_path = self.tmp / "state" / "projects.json"
        self.repo = _init_repo(self.tmp / "repo")
        self.worktree_root = self.tmp / "worktrees"

    def registry(self) -> ProjectRegistry:
        return ProjectRegistry(self.registry_path)


class DiscoveryAndDeduplicationTests(ProjectRegistryTestCase):
    def test_add_discovers_primary_checkout(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        self.assertIsInstance(project, Project)
        self.assertTrue(str(project.id).startswith("p-"))
        self.assertEqual(project.primary, self.repo.resolve())
        self.assertEqual(project.integration_branch, "main")
        self.assertEqual(project.worktree_root, self.worktree_root.resolve())
        self.assertIsNotNone(project.git_common_dir)
        self.assertTrue(str(project.git_common_dir).endswith(".git"))

    def test_linked_worktree_deduplicates_to_same_project_id(self):
        registry = self.registry()
        linked = self.tmp / "linked-worktree"
        _run_git(["worktree", "add", "-b", "feature", str(linked)], self.repo)

        first = registry.add(self.repo, "main", self.worktree_root)
        second = registry.add(linked, "main", self.worktree_root)

        self.assertEqual(first.id, second.id)
        self.assertEqual(registry.list(), [first])

    def test_add_missing_git_repo_raises(self):
        registry = self.registry()
        not_a_repo = self.tmp / "plain-dir"
        not_a_repo.mkdir()
        with self.assertRaises(ProjectRegistryError):
            registry.add(not_a_repo, "main", self.worktree_root)
        self.assertFalse(self.registry_path.exists())

    def test_add_nonexistent_path_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.tmp / "does-not-exist", "main", self.worktree_root)


class IntegrationBranchDiscoveryTests(ProjectRegistryTestCase):
    """§4.2: an unconfigured branch is discovered narrowly or refused —
    never silently guessed."""

    def _set_unambiguous_origin_head(self, repo: Path, branch: str) -> None:
        # No network needed: fabricate a remote-tracking ref and point
        # origin/HEAD at it, exactly as `git remote set-head` would leave
        # things after a real clone.
        _run_git(["update-ref", f"refs/remotes/origin/{branch}", "HEAD"], repo)
        _run_git(["symbolic-ref", "refs/remotes/origin/HEAD",
                 f"refs/remotes/origin/{branch}"], repo)

    def test_explicit_branch_is_stored_verbatim_without_discovery(self):
        registry = self.registry()
        with patch("asb.projects.registry.subprocess.run",
                   wraps=subprocess.run) as run:
            project = registry.add(self.repo, "release", self.worktree_root)
        self.assertEqual(project.integration_branch, "release")

        def argv_of(call):
            return call.args[0] if call.args else call.kwargs.get("args", [])

        symbolic_ref_calls = [call for call in run.call_args_list
                              if "symbolic-ref" in argv_of(call)]
        self.assertEqual(symbolic_ref_calls, [])

    def test_discovers_unambiguous_origin_head_branch(self):
        # A distinctive name: a silent "main" default would fail this.
        self._set_unambiguous_origin_head(self.repo, "trunk")
        registry = self.registry()
        project = registry.add(self.repo, None, self.worktree_root)
        self.assertEqual(project.integration_branch, "trunk")

    def test_missing_origin_head_raises_and_writes_nothing(self):
        # self.repo has no `origin` remote at all: refs/remotes/origin/HEAD
        # cannot resolve.
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, None, self.worktree_root)
        self.assertFalse(self.registry_path.exists())

    def test_origin_head_pointing_outside_origin_raises_and_writes_nothing(self):
        # `symbolic-ref --short` succeeds but resolves to a ref that is not
        # under `refs/remotes/origin/`, so the "origin/" prefix strip yields
        # an empty branch name: must raise, not silently accept it.
        _run_git(["symbolic-ref", "refs/remotes/origin/HEAD",
                 "refs/heads/master"], self.repo)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, None, self.worktree_root)
        self.assertFalse(self.registry_path.exists())


class PersistenceShapeTests(ProjectRegistryTestCase):
    def test_json_schema_version_and_modes(self):
        registry = self.registry()
        registry.add(self.repo, "main", self.worktree_root)

        self.assertEqual(registry.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(registry.path.parent.stat().st_mode & 0o777, 0o700)
        on_disk = json.loads(registry.path.read_text())
        self.assertEqual(on_disk["schemaVersion"], 1)
        self.assertEqual(len(on_disk["projects"]), 1)
        entry = on_disk["projects"][0]
        self.assertEqual(entry["primary"], str(self.repo.resolve()))
        self.assertTrue(entry["gitCommonDir"].endswith(".git"))
        self.assertEqual(entry["integrationBranch"], "main")
        self.assertEqual(entry["checkouts"], [])

    def test_lock_file_has_mode_0600(self):
        registry = self.registry()
        registry.add(self.repo, "main", self.worktree_root)
        lock_path = registry.path.with_name(registry.path.name + ".lock")
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)


class CorruptionAndSchemaRejectionTests(ProjectRegistryTestCase):
    def _seed(self, content: str) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(content, encoding="utf-8")

    def test_corrupt_json_raises_and_leaves_file_untouched(self):
        self._seed("{not json")
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        # Route through the write path (add()) too: list() alone never opens
        # _transact, so it cannot prove the file survives a write attempt.
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), "{not json")

    def test_non_object_root_raises_and_leaves_file_untouched(self):
        self._seed("[]")
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), "[]")

    def test_unknown_schema_version_raises_and_leaves_file_untouched(self):
        payload = json.dumps({"schemaVersion": 2, "projects": []})
        self._seed(payload)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), payload)

    def test_project_missing_required_key_raises_and_leaves_file_untouched(self):
        payload = json.dumps({
            "schemaVersion": 1,
            "projects": [{
                "id": "p-missing-branch",
                "primary": "/tmp/repo",
                "gitCommonDir": "/tmp/repo/.git",
                # "integrationBranch" deliberately omitted.
                "worktreeRoot": "/tmp/worktrees",
                "checkouts": [],
            }],
        })
        self._seed(payload)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), payload)

    def test_checkout_missing_required_key_raises_and_leaves_file_untouched(self):
        payload = json.dumps({
            "schemaVersion": 1,
            "projects": [{
                "id": "p-1",
                "primary": "/tmp/repo",
                "gitCommonDir": "/tmp/repo/.git",
                "integrationBranch": "main",
                "worktreeRoot": "/tmp/worktrees",
                "checkouts": [{
                    "id": "c-1",
                    "sourcePath": "/tmp/repo",
                    # "workspace" deliberately omitted.
                }],
            }],
        })
        self._seed(payload)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), payload)

    def test_non_object_project_entry_raises_and_leaves_file_untouched(self):
        payload = json.dumps({"schemaVersion": 1, "projects": ["not-an-object"]})
        self._seed(payload)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), payload)

    def test_non_object_checkout_entry_raises_and_leaves_file_untouched(self):
        payload = json.dumps({
            "schemaVersion": 1,
            "projects": [{
                "id": "p-1",
                "primary": "/tmp/repo",
                "gitCommonDir": "/tmp/repo/.git",
                "integrationBranch": "main",
                "worktreeRoot": "/tmp/worktrees",
                "checkouts": ["not-an-object"],
            }],
        })
        self._seed(payload)
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.list()
        with self.assertRaises(ProjectRegistryError):
            registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(self.registry_path.read_text(), payload)


class ConcurrencyAndIsolationTests(ProjectRegistryTestCase):
    def test_two_registry_instances_see_each_others_writes(self):
        registry_a = self.registry()
        registry_b = self.registry()

        other_repo = _init_repo(self.tmp / "other-repo")

        project_a = registry_a.add(self.repo, "main", self.worktree_root)
        project_b = registry_b.add(other_repo, "main", self.worktree_root)

        ids_from_a = {p.id for p in registry_a.list()}
        ids_from_b = {p.id for p in registry_b.list()}
        self.assertEqual(ids_from_a, ids_from_b)
        self.assertEqual(ids_from_a, {project_a.id, project_b.id})

    def _register_concurrently(self, project_id, paths) -> list:
        barrier = threading.Barrier(len(paths))
        errors: list[BaseException] = []
        results: list[CheckoutBinding] = []

        def worker(path: Path) -> None:
            try:
                barrier.wait(timeout=5)
                results.append(ProjectRegistry(self.registry_path)
                               .register_checkout(project_id, path))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(p,)) for p in paths]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        return results

    def test_concurrent_registration_of_one_path_mints_one_identity(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)

        results = self._register_concurrently(project.id, [self.repo] * 20)

        bindings = registry.bindings(project.id)
        self.assertEqual(len(bindings), 1)
        self.assertEqual({b.checkout_id for b in results},
                         {bindings[0].checkout_id})

    def test_concurrent_registration_of_distinct_paths_loses_no_update(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        paths = [_linked_worktree(self.repo, self.tmp / f"checkout-{i}")
                 for i in range(20)]

        self._register_concurrently(project.id, paths)

        bindings = registry.bindings(project.id)
        self.assertEqual(len(bindings), 20)
        self.assertEqual(len({b.checkout_id for b in bindings}), 20)


class LookupAndIdempotencyTests(ProjectRegistryTestCase):
    def test_get_missing_project_id_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.get(ProjectId("p-0000000000000000"))

    def test_add_is_idempotent_for_the_same_project(self):
        registry = self.registry()
        first = registry.add(self.repo, "main", self.worktree_root)
        second = registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(first, second)
        self.assertEqual(len(registry.list()), 1)

    def test_get_returns_added_project(self):
        registry = self.registry()
        added = registry.add(self.repo, "main", self.worktree_root)
        self.assertEqual(registry.get(added.id), added)

    def test_remove_deletes_project_and_is_idempotent(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        registry.remove(project.id)
        self.assertEqual(registry.list(), [])
        # Removing again must not raise (idempotent).
        registry.remove(project.id)


class CheckoutBindingTests(ProjectRegistryTestCase):
    def test_register_and_unbind_checkout(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)

        binding = registry.register_checkout(project.id, self.repo)
        self.assertIsInstance(binding, CheckoutBinding)
        self.assertIsInstance(binding.checkout_id, CheckoutId)
        self.assertTrue(str(binding.checkout_id).startswith("c-"))
        self.assertEqual(binding.project_id, project.id)
        self.assertEqual(binding.source_path, self.repo.resolve())

        self.assertEqual(registry.bindings(project.id), [binding])

        registry.unbind_checkout(binding.checkout_id)
        self.assertEqual(registry.bindings(project.id), [])

    def test_workspace_is_the_deterministic_orca_free_name_of_the_path(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        orca = {"ORCA_VM_INSTANCE_ID": "orca-vm-1",
                "ORCA_WORKSPACE_ID": "orca-ws-1"}

        with patch.dict(os.environ, orca):
            binding = registry.register_checkout(project.id, self.repo)

        # Literal esperado: `workspace_id` com env VAZIO — basename + 8 hex do
        # sha256 do caminho resolvido; nunca as variaveis do Orca.
        import hashlib
        digest = hashlib.sha256(
            str(self.repo.resolve()).encode()).hexdigest()[:8]
        self.assertEqual(binding.workspace, f"repo-{digest}")

    def test_registering_twice_returns_the_same_identity_and_writes_one_entry(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)

        first = registry.register_checkout(project.id, self.repo)
        # Mesmo checkout por outra grafia do caminho: resolve() antes de casar.
        second = registry.register_checkout(
            project.id, self.repo / ".." / self.repo.name)

        self.assertEqual(first, second)
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(len(raw["projects"][0]["checkouts"]), 1)

    def test_two_paths_in_one_project_get_different_identities(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        other = _linked_worktree(self.repo, self.tmp / "other-checkout")

        first = registry.register_checkout(project.id, self.repo)
        second = registry.register_checkout(project.id, other)

        self.assertNotEqual(first.checkout_id, second.checkout_id)
        self.assertNotEqual(first.workspace, second.workspace)
        self.assertEqual(registry.bindings(project.id), [first, second])

    def test_unsafe_workspace_name_is_refused_and_nothing_is_written(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        before = self.registry_path.read_text(encoding="utf-8")

        # Um basename que so tem caracteres inseguros sanitiza para vazio,
        # e `workspace_id` devolve "-<hash>", que nao e a propria forma
        # sanitizada.
        with self.assertRaises(ProjectRegistryError):
            registry.register_checkout(project.id, self.tmp / "@@@")

        self.assertEqual(self.registry_path.read_text(encoding="utf-8"),
                         before)

    def test_checkout_looks_a_binding_up_by_its_stable_identity(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        registry.register_checkout(
            project.id, _linked_worktree(self.repo, self.tmp / "first"))
        wanted = registry.register_checkout(project.id, self.repo)

        self.assertEqual(registry.checkout(wanted.checkout_id), wanted)

    def test_a_path_of_another_repository_is_refused_before_any_write(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        registry.register_checkout(project.id, self.repo)
        before = self.registry_path.read_text(encoding="utf-8")
        foreign = _init_repo(self.tmp / "foreign")

        with self.assertRaises(ProjectRegistryError) as ctx:
            registry.register_checkout(project.id, foreign)

        self.assertIn("another repository", str(ctx.exception))
        self.assertEqual(self.registry_path.read_text(encoding="utf-8"),
                         before)

    def test_a_path_that_is_not_a_checkout_is_refused_before_any_write(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        before = self.registry_path.read_text(encoding="utf-8")

        for path in (self.tmp / "absent", self.tmp):
            with self.subTest(path=path), \
                    self.assertRaises(ProjectRegistryError):
                registry.register_checkout(project.id, path)

        self.assertEqual(self.registry_path.read_text(encoding="utf-8"),
                         before)

    def test_the_primary_and_a_linked_worktree_are_both_accepted(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        linked = _linked_worktree(self.repo, self.tmp / "linked")

        primary = registry.register_checkout(project.id, self.repo)
        worktree = registry.register_checkout(project.id, linked)

        self.assertEqual(registry.bindings(project.id), [primary, worktree])
        self.assertEqual(worktree.source_path, linked.resolve())

    def test_a_hung_git_is_a_registry_error_and_writes_nothing(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        before = self.registry_path.read_text(encoding="utf-8")
        with patch("asb.projects.registry.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("git", 10)) as run, \
                self.assertRaises(ProjectRegistryError):
            registry.register_checkout(project.id, self.repo)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["git", "-C", str(self.repo)])
        self.assertGreater(run.call_args.kwargs["timeout"], 0)
        self.assertEqual(self.registry_path.read_text(encoding="utf-8"),
                         before)

    def test_a_record_without_common_dir_is_checked_against_the_primary(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        raw["projects"][0]["gitCommonDir"] = None
        self.registry_path.write_text(json.dumps(raw), encoding="utf-8")
        foreign = _init_repo(self.tmp / "foreign")

        with self.assertRaises(ProjectRegistryError):
            registry.register_checkout(project.id, foreign)
        binding = registry.register_checkout(project.id, self.repo)

        self.assertEqual(registry.bindings(project.id), [binding])

    def test_checkout_unknown_identity_raises(self):
        registry = self.registry()
        registry.add(self.repo, "main", self.worktree_root)
        with self.assertRaises(ProjectRegistryError):
            registry.checkout(CheckoutId("c-0000000000000000"))

    def test_old_minting_bind_checkout_is_gone(self):
        self.assertFalse(hasattr(ProjectRegistry, "bind_checkout"))

    def test_register_checkout_unknown_project_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.register_checkout(ProjectId("p-0000000000000000"),
                                       self.repo)

    def test_bindings_unknown_project_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.bindings(ProjectId("p-0000000000000000"))

    def test_unbind_unknown_checkout_is_a_noop(self):
        registry = self.registry()
        registry.add(self.repo, "main", self.worktree_root)
        registry.unbind_checkout(CheckoutId("c-0000000000000000"))


if __name__ == "__main__":
    unittest.main()
