"""Testes de cli/asb/install.py — instaladores do host."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import install  # noqa: E402


class TestInstallGuards(unittest.TestCase):
    def test_guards_creates_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            guard_bin = fake_root / "cli" / "asb-guard"
            guard_bin.parent.mkdir(parents=True)
            guard_bin.write_text("#!/bin/sh\n")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            local_bin = fake_home / ".local" / "bin"
            for agent in ("claude", "codex", "agy"):
                link = local_bin / f"asb-{agent}"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), guard_bin.resolve())

    def test_guards_instala_o_proprio_asb_agent_no_path(self):
        """O CLI precisa rodar de qualquer diretorio, nao so do checkout.

        Ele ja funciona por symlink — Path(__file__).resolve() segue o link —
        entao o que faltava era so instalar o link.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            (fake_root / "cli").mkdir(parents=True)
            (fake_root / "cli" / "asb-guard").write_text("#!/bin/sh\n")
            cli = fake_root / "cli" / "asb-agent"
            cli.write_text("#!/usr/bin/env python3\n")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            link = fake_home / ".local" / "bin" / "asb-agent"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), cli.resolve())

    def test_guards_substitui_asb_agent_de_checkout_antigo(self):
        """Modo de falha da §16.1: a pasta muda de lugar e o link fica orfao."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            (fake_root / "cli").mkdir(parents=True)
            (fake_root / "cli" / "asb-guard").write_text("#!/bin/sh\n")
            cli = fake_root / "cli" / "asb-agent"
            cli.write_text("#!/usr/bin/env python3\n")

            local_bin = fake_home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            (local_bin / "asb-agent").symlink_to(Path(tmp) / "checkout-velho"
                                                 / "cli" / "asb-agent")

            with mock.patch.object(Path, "home", return_value=fake_home):
                install.guards(fake_root)

            self.assertEqual((local_bin / "asb-agent").resolve(), cli.resolve())

    def test_guards_is_idempotent_and_replaces_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            fake_root = Path(tmp) / "checkout"
            guard_bin = fake_root / "cli" / "asb-guard"
            guard_bin.parent.mkdir(parents=True)
            guard_bin.write_text("#!/bin/sh\n")

            local_bin = fake_home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            # Existing regular file
            (local_bin / "asb-claude").write_text("old file")
            # Existing broken symlink
            (local_bin / "asb-codex").symlink_to(Path(tmp) / "nonexistent")

            with mock.patch.object(Path, "home", return_value=fake_home):
                code = install.guards(fake_root)

            self.assertEqual(code, 0)
            for agent in ("claude", "codex", "agy"):
                link = local_bin / f"asb-{agent}"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), guard_bin.resolve())


class TestPodmanRestart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake_home = Path(self.tmp.name) / "home"
        self.fake_home.mkdir()
        self.fake_unit = Path(self.tmp.name) / "dist" / "podman-restart.service"
        self.fake_unit.parent.mkdir(parents=True)
        self.fake_unit.write_text("[Unit]\nDescription=podman-restart\n")
        self.dropin_file = (
            self.fake_home
            / ".config"
            / "systemd"
            / "user"
            / "podman-restart.service.d"
            / "agent-sandbox.conf"
        )

    def test_creates_dropin_with_service_section_and_exec_start_pre(self):
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", self.fake_unit), \
             mock.patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"), \
             mock.patch("subprocess.run") as mock_run:
            code = install.podman_restart()

        self.assertEqual(code, 0)
        self.assertTrue(self.dropin_file.is_file())
        content = self.dropin_file.read_text()
        self.assertIn("[Service]", content)
        self.assertIn(
            "ExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true",
            content,
        )
        self.assertEqual(content.count("ExecStartPre="), 1)

    def test_calls_daemon_reload_before_enable(self):
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", self.fake_unit), \
             mock.patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"), \
             mock.patch("subprocess.run") as mock_run:
            code = install.podman_restart()

        self.assertEqual(code, 0)
        self.assertEqual(
            mock_run.call_args_list,
            [
                mock.call(["systemctl", "--user", "daemon-reload"], check=True),
                mock.call(["systemctl", "--user", "enable", "podman-restart.service"], check=True),
            ],
        )

    def test_idempotent_when_called_twice(self):
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", self.fake_unit), \
             mock.patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"), \
             mock.patch("subprocess.run") as mock_run:
            code1 = install.podman_restart()
            code2 = install.podman_restart()

        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertTrue(self.dropin_file.is_file())
        content = self.dropin_file.read_text()
        self.assertEqual(
            content,
            "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n",
        )
        self.assertEqual(
            mock_run.call_args_list,
            [
                mock.call(["systemctl", "--user", "daemon-reload"], check=True),
                mock.call(["systemctl", "--user", "enable", "podman-restart.service"], check=True),
                mock.call(["systemctl", "--user", "daemon-reload"], check=True),
                mock.call(["systemctl", "--user", "enable", "podman-restart.service"], check=True),
            ],
        )

    def test_returns_1_without_writing_dropin_if_dist_unit_missing(self):
        missing_unit = Path(self.tmp.name) / "nonexistent" / "podman-restart.service"
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", missing_unit), \
             mock.patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"), \
             mock.patch("subprocess.run") as mock_run:
            code = install.podman_restart()

        self.assertEqual(code, 1)
        self.assertFalse(self.dropin_file.exists())
        mock_run.assert_not_called()

    def test_returns_1_without_writing_dropin_if_podman_missing(self):
        def fake_which(cmd):
            return None if cmd == "podman" else f"/usr/bin/{cmd}"

        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", self.fake_unit), \
             mock.patch("shutil.which", side_effect=fake_which), \
             mock.patch("subprocess.run") as mock_run:
            code = install.podman_restart()

        self.assertEqual(code, 1)
        self.assertFalse(self.dropin_file.exists())
        mock_run.assert_not_called()

    def test_returns_1_without_writing_dropin_if_true_missing(self):
        def fake_which(cmd):
            return None if cmd == "true" else f"/usr/bin/{cmd}"

        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch.object(install, "PODMAN_RESTART_UNIT", self.fake_unit), \
             mock.patch("shutil.which", side_effect=fake_which), \
             mock.patch("subprocess.run") as mock_run:
            code = install.podman_restart()

        self.assertEqual(code, 1)
        self.assertFalse(self.dropin_file.exists())
        mock_run.assert_not_called()


class TestInstallRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.fake_checkout = self.tmp_path / "checkout"
        self.fake_checkout.mkdir(parents=True)
        # Create minimal asb package in checkout
        asb_pkg = self.fake_checkout / "cli" / "asb"
        asb_pkg.mkdir(parents=True)
        (asb_pkg / "__init__.py").write_text("# asb init\n")
        (asb_pkg / "readiness.py").write_text("# readiness\n")
        (asb_pkg / "runtime_check.py").write_text("# runtime_check\n")
        self.target_base = self.tmp_path / "runtime_lib"

    def test_install_runtime_copies_asb_and_scripts_without_symlinks(self):
        dest = install.install_runtime(
            self.fake_checkout,
            revision="rev-test-1",
            target_base=self.target_base,
        )

        self.assertEqual(dest, self.target_base / "rev-test-1")
        self.assertTrue(dest.is_dir())
        self.assertTrue((dest / "asb" / "__init__.py").is_file())
        self.assertTrue((dest / "asb" / "readiness.py").is_file())
        self.assertTrue((dest / "launcher.sh").is_file())
        self.assertTrue((dest / "runtime_check.py").is_file())

        # Mode executable on scripts
        launcher_mode = (dest / "launcher.sh").stat().st_mode
        self.assertTrue(launcher_mode & 0o111)
        check_mode = (dest / "runtime_check.py").stat().st_mode
        self.assertTrue(check_mode & 0o111)

        # Strictly NO symlinks in installed runtime
        for p in dest.rglob("*"):
            self.assertFalse(p.is_symlink(), f"Found symlink in installed runtime: {p}")

    def test_install_runtime_idempotent_when_called_twice(self):
        dest1 = install.install_runtime(
            self.fake_checkout,
            revision="rev-test-1",
            target_base=self.target_base,
        )
        dest2 = install.install_runtime(
            self.fake_checkout,
            revision="rev-test-1",
            target_base=self.target_base,
        )
        self.assertEqual(dest1, dest2)
        self.assertTrue((dest2 / "asb" / "__init__.py").is_file())

    def test_install_runtime_functional_when_checkout_moves(self):
        dest = install.install_runtime(
            self.fake_checkout,
            revision="rev-test-1",
            target_base=self.target_base,
        )
        # Move checkout away
        moved_checkout = self.tmp_path / "moved_checkout"
        self.fake_checkout.rename(moved_checkout)

        # Dest must still have all files and be functional
        self.assertTrue((dest / "asb" / "__init__.py").is_file())
        self.assertTrue((dest / "launcher.sh").is_file())
        self.assertTrue((dest / "runtime_check.py").is_file())

    def test_install_runtime_rejects_unsafe_revisions(self):
        unsafe_revisions = [
            "",
            "../escape",
            "rev/slash",
            "rev\\backslash",
            "rev\nnewline",
            "rev with spaces",
        ]
        for rev in unsafe_revisions:
            with self.assertRaises(ValueError, msg=f"Should reject revision {rev!r}"):
                install.install_runtime(
                    self.fake_checkout,
                    revision=rev,
                    target_base=self.target_base,
                )


if __name__ == "__main__":
    unittest.main()


