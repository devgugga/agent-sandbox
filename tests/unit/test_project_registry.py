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

    def test_concurrent_bind_checkout_does_not_lose_updates(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)

        worker_count = 20
        barrier = threading.Barrier(worker_count)
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=5)
                ProjectRegistry(self.registry_path).bind_checkout(
                    project.id, self.repo, f"ws-{index}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                  for i in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        bindings = registry.bindings(project.id)
        self.assertEqual(len(bindings), worker_count)
        self.assertEqual(len({b.checkout_id for b in bindings}), worker_count)


class LookupAndIdempotencyTests(ProjectRegistryTestCase):
    def test_get_missing_project_id_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.get(ProjectId("p-0000000000000000"))

    def test_add_with_no_integration_branch_defaults_to_main(self):
        registry = self.registry()
        project = registry.add(self.repo, None, self.worktree_root)
        self.assertEqual(project.integration_branch, "main")

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
    def test_bind_and_unbind_checkout(self):
        registry = self.registry()
        project = registry.add(self.repo, "main", self.worktree_root)

        binding = registry.bind_checkout(project.id, self.repo, "repo-a1b2c3d4")
        self.assertIsInstance(binding, CheckoutBinding)
        self.assertIsInstance(binding.checkout_id, CheckoutId)
        self.assertEqual(binding.project_id, project.id)
        self.assertEqual(binding.source_path, self.repo.resolve())
        self.assertEqual(binding.workspace, "repo-a1b2c3d4")

        self.assertEqual(registry.bindings(project.id), [binding])

        registry.unbind_checkout(binding.checkout_id)
        self.assertEqual(registry.bindings(project.id), [])

    def test_bind_checkout_unknown_project_raises(self):
        registry = self.registry()
        with self.assertRaises(ProjectRegistryError):
            registry.bind_checkout(ProjectId("p-0000000000000000"),
                                   self.repo, "ws")

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
