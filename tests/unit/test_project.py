from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_PY = REPO_ROOT / ".graphify" / "project.py"
spec = importlib.util.spec_from_file_location("project", PROJECT_PY)
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)


class ProjectDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write(self, relative: str, content: str = "content\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_full_detection_adds_sandbox_configuration_and_excludes_sensitive(self) -> None:
        self._write("Containerfile", "FROM debian:bookworm-slim\n")
        self._write("recipes/create.sh", "#!/usr/bin/env bash\necho 1\n")
        self._write("profiles/provision.toml", "[agent]\nname = 'test'\n")
        self._write("image/squid/squid.conf.tmpl", "http_port 3128\n")
        self._write(".env", "SECRET=do-not-index\n")
        self._write("graphify-out/generated.toml", "generated=true\n")
        self._write(".agent-sandbox.toml", "local_token='secret'\n")
        self._write("id_ed25519", "OPENSSH PRIVATE KEY\n")
        self._write("keyring.pass", "secret-pass\n")
        self._write("state/run.json", "{}\n")
        self._write("scratch/test.sh", "#!/bin/bash\n")
        self._write(".superpowers/plan.md", "# Plan\n")
        self._write("large_file.toml", "x" * 1_000_001)

        subprocess.run(
            ["git", "-C", str(self.root), "add", "-f", "."],
            check=True,
        )

        native = {
            "files": {"code": [], "document": []},
            "total_files": 0,
            "total_words": 0,
        }
        with patch.object(project, "detect", return_value=native):
            result = project.detect_project(self.root)

        documents = {Path(path).name for path in result["files"]["document"]}
        self.assertEqual(
            {"Containerfile", "create.sh", "provision.toml", "squid.conf.tmpl"},
            documents,
        )
        self.assertEqual(4, result["total_files"])
        all_docs_str = "\n".join(result["files"]["document"])
        self.assertNotIn(".env", all_docs_str)
        self.assertNotIn("graphify-out", all_docs_str)
        self.assertNotIn(".agent-sandbox.toml", all_docs_str)
        self.assertNotIn("id_ed25519", all_docs_str)
        self.assertNotIn("keyring.pass", all_docs_str)
        self.assertNotIn("state", all_docs_str)
        self.assertNotIn("scratch", all_docs_str)
        self.assertNotIn(".superpowers", all_docs_str)
        self.assertNotIn("large_file.toml", all_docs_str)

    def test_incremental_detection(self) -> None:
        containerfile = self._write("Containerfile", "FROM debian:bookworm-slim\n").resolve()
        recipe = self._write("recipes/create.sh", "#!/usr/bin/env bash\necho 1\n").resolve()
        self._write(".env", "SECRET=do-not-index\n")
        self._write("graphify-out/generated.toml", "generated=true\n")

        subprocess.run(
            ["git", "-C", str(self.root), "add", "-f", "."],
            check=True,
        )

        native = {
            "files": {"code": [], "document": []},
            "new_files": {
                "code": [],
                "document": [str(self.root / "graphify-out" / "memory.md")],
            },
            "unchanged_files": {"code": [], "document": []},
            "deleted_files": [str(containerfile), str(self.root / ".env")],
            "excluded_files": [str(containerfile), str(self.root / ".env")],
            "new_total": 0,
            "total_files": 0,
            "total_words": 0,
        }
        manifest = {
            str(containerfile): {
                "mtime": containerfile.stat().st_mtime,
                "ast_hash": "",
                "semantic_hash": project._md5_file(containerfile),
            },
            str(recipe): {
                "mtime": recipe.stat().st_mtime,
                "ast_hash": "",
                "semantic_hash": "stale_hash",
            },
        }

        with (
            patch.object(project, "detect_incremental", return_value=native),
            patch.object(project, "load_manifest", return_value=manifest),
        ):
            result = project.detect_incremental_project(self.root)

        self.assertIn(str(recipe), result["new_files"]["document"])
        self.assertNotIn(str(containerfile), result["new_files"]["document"])
        self.assertIn(str(containerfile), result["unchanged_files"]["document"])
        self.assertNotIn(str(containerfile), result["deleted_files"])
        self.assertNotIn(str(containerfile), result["excluded_files"])
        self.assertNotIn(str(self.root / ".env"), result["deleted_files"])
        self.assertNotIn(str(self.root / ".env"), result["excluded_files"])

        new_docs_str = "\n".join(result["new_files"]["document"])
        self.assertNotIn("graphify-out", new_docs_str)
        self.assertNotIn(".env", new_docs_str)

    def test_project_config_filtering_and_names(self) -> None:
        files = [
            "Containerfile",
            "Containerfile.proxy",
            "allowlist-base.txt",
            "cli/asb-guard",
            "cli/asb-agent",
            "broker/asb-docker-broker.service.tmpl",
            ".gitignore",
            ".gitattributes",
            ".graphifyignore",
            "recipes/custom.sh",
            "profiles/custom.toml",
            "squid.conf",
            "config.yaml",
            ".env",
            ".env.production",
            ".agent-sandbox.toml",
            "id_ed25519",
            "keyring.pass",
            "secret.pass",
            "graphify-out/graph.json",
            ".superpowers/spec.toml",
            "scratch/test.sh",
            "state/run.toml",
        ]
        for rel in files:
            self._write(rel, "dummy content\n")

        self.assertTrue(project._is_project_config(self.root / "Containerfile", self.root))
        self.assertTrue(project._is_project_config(self.root / "Containerfile.proxy", self.root))
        self.assertTrue(project._is_project_config(self.root / "allowlist-base.txt", self.root))
        self.assertTrue(project._is_project_config(self.root / "cli" / "asb-guard", self.root))
        self.assertTrue(project._is_project_config(self.root / "cli" / "asb-agent", self.root))
        self.assertTrue(project._is_project_config(self.root / "broker" / "asb-docker-broker.service.tmpl", self.root))
        self.assertTrue(project._is_project_config(self.root / ".gitignore", self.root))
        self.assertTrue(project._is_project_config(self.root / ".gitattributes", self.root))
        self.assertTrue(project._is_project_config(self.root / ".graphifyignore", self.root))
        self.assertTrue(project._is_project_config(self.root / "recipes" / "custom.sh", self.root))
        self.assertTrue(project._is_project_config(self.root / "profiles" / "custom.toml", self.root))
        self.assertTrue(project._is_project_config(self.root / "squid.conf", self.root))
        self.assertTrue(project._is_project_config(self.root / "config.yaml", self.root))

        self.assertFalse(project._is_project_config(self.root / ".env", self.root))
        self.assertFalse(project._is_project_config(self.root / ".env.production", self.root))
        self.assertFalse(project._is_project_config(self.root / ".agent-sandbox.toml", self.root))
        self.assertFalse(project._is_project_config(self.root / "id_ed25519", self.root))
        self.assertFalse(project._is_project_config(self.root / "keyring.pass", self.root))
        self.assertFalse(project._is_project_config(self.root / "secret.pass", self.root))
        self.assertFalse(project._is_project_config(self.root / "graphify-out" / "graph.json", self.root))
        self.assertFalse(project._is_project_config(self.root / ".superpowers" / "spec.toml", self.root))
        self.assertFalse(project._is_project_config(self.root / "scratch" / "test.sh", self.root))
        self.assertFalse(project._is_project_config(self.root / "state" / "run.toml", self.root))

    def test_sanitize_native_result_moves_code_to_document(self) -> None:
        sh_path = self._write("recipes/create.sh", "#!/usr/bin/env bash\necho 1\n").resolve()
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "."], check=True)

        native = {
            "files": {
                "code": [str(sh_path)],
                "document": [],
            },
            "total_files": 1,
            "total_words": 5,
        }
        with patch.object(project, "detect", return_value=native):
            result = project.detect_project(self.root)

        self.assertNotIn(str(sh_path), result["files"].get("code", []))
        self.assertIn(str(sh_path), result["files"]["document"])

    def test_tracked_files_fallback(self) -> None:
        file_path = self._write("Containerfile", "FROM alpine\n").resolve()
        with patch("subprocess.run", side_effect=OSError("git not found")):
            tracked = project._tracked_files(self.root)
        self.assertIn(file_path, tracked)

    def test_word_count(self) -> None:
        f1 = self._write("f1.txt", "one two three\n")
        f2 = self._write("f2.txt", "four five\n")
        missing = self.root / "missing.txt"
        self.assertEqual(5, project._word_count([f1, f2, missing]))

    def test_untracked_working_tree_configs_detected(self) -> None:
        self._write(".gitignore", "ignored.sh\n")
        subprocess.run(["git", "-C", str(self.root), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "init"], check=True)

        # Create untracked working-tree assets
        untracked_cfg = self._write("recipes/create.sh", "#!/usr/bin/env bash\necho untracked\n").resolve()
        ignored_file = self._write("ignored.sh", "#!/bin/bash\n").resolve()

        tracked = project._tracked_files(self.root)
        self.assertIn(untracked_cfg, tracked)
        self.assertNotIn(ignored_file, tracked)

    def test_word_count_not_double_counted_for_rerouted_code(self) -> None:
        sh_path = self._write("recipes/create.sh", "one two three four five\n").resolve()
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "."], check=True)

        native = {
            "files": {
                "code": [str(sh_path)],
                "document": [],
            },
            "total_files": 1,
            "total_words": 5,
        }
        with patch.object(project, "detect", return_value=native):
            result = project.detect_project(self.root)

        self.assertIn(str(sh_path), result["files"]["document"])
        self.assertEqual(5, result["total_words"])


if __name__ == "__main__":
    unittest.main()
