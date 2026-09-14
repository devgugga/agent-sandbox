import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import tempfile
import unittest
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
        mock_run.assert_called()
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
            f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n",
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

    def test_check_project_dropin_detects_legacy_and_header(self):
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)

        # 1. Absent file
        self.assertEqual(install.check_project_dropin(target_dir), (False, False))

        # 2. Modern dropin with PROJECT_DROPIN_HEADER
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n", encoding="utf-8")
        self.assertEqual(install.check_project_dropin(target_dir), (True, True))

        # 3. Canonical legacy dropin without header
        dropin.write_text("[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n", encoding="utf-8")
        self.assertEqual(install.check_project_dropin(target_dir), (True, True))

        # 4. Third-party foreign dropin
        dropin.write_text("[Service]\n# Third party custom\nExecStartPre=/usr/bin/custom-netns\n", encoding="utf-8")
        self.assertEqual(install.check_project_dropin(target_dir), (True, False))

    def test_remove_project_dropin_concurrency_and_foreign_guard(self):
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)

        # 1. Absent file
        self.assertFalse(install.remove_project_dropin(target_dir))

        # 2. Foreign file - refused
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text("[Service]\n# Third party\n", encoding="utf-8")
        self.assertFalse(install.remove_project_dropin(target_dir))
        self.assertTrue(dropin.is_file())

        # 3. Owned file, but expected_content mismatched
        dropin.write_text(f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n", encoding="utf-8")
        with self.assertRaises(RuntimeError) as cm:
            install.remove_project_dropin(target_dir, expected_content="mismatched content")
        self.assertIn("drop-in alterado externamente", str(cm.exception))
        self.assertTrue(dropin.is_file())

        # 4. Owned file with matching expected_content - removed and daemon reloaded
        with mock.patch("subprocess.run") as mock_run:
            res = install.remove_project_dropin(
                target_dir, expected_content=f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n"
            )
            self.assertTrue(res)
            self.assertFalse(dropin.exists())
            mock_run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)

    def test_restore_project_dropin_preexisting_conflict_and_mode_restoration(self):
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)

        # 1. Existing dropin with conflicting content
        dropin.write_text("existing content", encoding="utf-8")
        with self.assertRaises(RuntimeError) as cm:
            install.restore_project_dropin(target_dir, content="different expected content")
        self.assertIn("drop-in criado/modificado externamente", str(cm.exception))

        # 2. Existing dropin with matching content but divergent mode
        dropin.write_text("matching content", encoding="utf-8")
        dropin.chmod(0o600)
        res = install.restore_project_dropin(target_dir, content="matching content", mode=0o644)
        self.assertTrue(res)
        self.assertEqual(dropin.stat().st_mode & 0o777, 0o644)

        # 3. Absent dropin with content=None (synthesizes default dropin)
        dropin.unlink()
        with mock.patch("subprocess.run") as mock_run:
            res_synth = install.restore_project_dropin(target_dir, content=None, mode=0o640)
            self.assertTrue(res_synth)
            self.assertTrue(dropin.is_file())
            content = dropin.read_text(encoding="utf-8")
            self.assertIn(install.PROJECT_DROPIN_HEADER, content)
            self.assertEqual(dropin.stat().st_mode & 0o777, 0o640)
            mock_run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)

    def test_check_project_dropin_rejects_header_not_at_start(self):
        """I2: Header must be at the very start of the file, not matched as substring."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        # Header placed after other content (substring injection)
        dropin.write_text(f"[Service]\n# Injected\n{install.PROJECT_DROPIN_HEADER}\n", encoding="utf-8")
        self.assertEqual(install.check_project_dropin(target_dir), (True, False))

    def test_remove_project_dropin_checks_expected_mode(self):
        """I2: remove_project_dropin must verify mode before unlink."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        dropin.chmod(0o600)

        with self.assertRaises(RuntimeError) as cm:
            install.remove_project_dropin(target_dir, expected_content=content, expected_mode=0o644)
        self.assertIn("modo do drop-in alterado", str(cm.exception))
        self.assertTrue(dropin.is_file())

    def test_swap_between_validation_and_removal_keeps_the_foreign_file(self):
        """I4: a entrada trocada depois da ultima validacao nao e removida.

        O gancho troca o arquivo pelo de terceiro (inode novo) no instante em
        que a remocao vai agir sobre o nome, isto e, depois de toda leitura e
        comparacao. O arquivo alheio tem de continuar no nome original, com o
        mesmo inode, e nenhum resto de quarentena pode ficar no diretorio.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        foreign = "# drop-in de terceiro\n[Service]\nEnvironment=X=1\n"
        swapped: list[int] = []

        def swap_then(real):
            def hook(src, *args, **kwargs):
                if not swapped and os.fspath(src) in (dropin.name, str(dropin)):
                    tmp = dropin.parent / ".swap"
                    tmp.write_text(foreign, encoding="utf-8")
                    os.replace(tmp, dropin)
                    swapped.append(dropin.stat().st_ino)
                return real(src, *args, **kwargs)
            return hook

        with mock.patch("os.rename", side_effect=swap_then(os.rename)) as ren, \
                mock.patch("os.unlink", side_effect=swap_then(os.unlink)) as unl, \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.remove_project_dropin(target_dir, expected_content=content)
        self.assertTrue(ren.called or unl.called)
        run.assert_not_called()
        self.assertIn("substitu", str(cm.exception))
        self.assertEqual(swapped and dropin.read_text(encoding="utf-8"), foreign)
        self.assertEqual(dropin.stat().st_ino, swapped[0])
        self.assertEqual(sorted(p.name for p in dropin.parent.iterdir()), [dropin.name])

    def test_successful_removal_leaves_no_quarantine_behind(self):
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        (dropin.parent / "outro.conf").write_text("[Service]\n", encoding="utf-8")
        with mock.patch("subprocess.run") as run:
            self.assertTrue(install.remove_project_dropin(target_dir, expected_content=content))
        run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)
        self.assertEqual(sorted(p.name for p in dropin.parent.iterdir()), ["outro.conf"])

    def _staged_dropin(self, foreign: str):
        """Drop-in do projeto pronto para remocao, mais o gancho de reapontamento.

        Devolve (target_dir, dropin, content, repoint) — `repoint` troca a
        quarentena: devolve o validado ao nome original e poe `foreign` no nome
        que a remocao ainda vai usar.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = f"{install.PROJECT_DROPIN_HEADER}[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")

        def repoint(name: str) -> None:
            quarantine = dropin.parent / name
            os.replace(quarantine, dropin)
            quarantine.write_text(foreign, encoding="utf-8")

        return target_dir, dropin, content, repoint

    def test_quarantine_repointed_before_the_unlink_is_caught_and_spares_the_foreign_file(self):
        """Segunda janela TOCTOU, lado observavel: o inode e reconferido antes do unlink.

        O nome da quarentena e visivel no diretorio, entao quem observa pode
        reaponta-lo depois da validacao. Enquanto a troca acontecer ANTES do
        stat(2) final, ela e detectavel: nada e removido e o arquivo alheio
        continua onde estava.
        """
        foreign = "# arquivo de terceiro\n[Service]\nEnvironment=X=1\n"
        target_dir, dropin, content, repoint = self._staged_dropin(foreign)
        repointed: list[str] = []
        real_stat = os.stat

        def repoint_then_stat(path, *a, **kw):
            name = os.fspath(path)
            if not repointed and "asb-remove-" in name:
                repoint(name)
                repointed.append(name)
            return real_stat(path, *a, **kw)

        with mock.patch("os.stat", side_effect=repoint_then_stat), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.remove_project_dropin(target_dir, expected_content=content)
        self.assertTrue(repointed, "a quarentena nao foi reapontada")
        self.assertIn("reapontado", str(cm.exception))
        run.assert_not_called()
        alheio = dropin.parent / repointed[0]
        self.assertTrue(alheio.is_file(), "o arquivo alheio foi removido apesar da divergencia de inode")
        self.assertEqual(alheio.read_text(encoding="utf-8"), foreign)

    def test_quarantine_repointed_inside_the_unlink_still_refuses_by_postcondition(self):
        """Segunda janela TOCTOU, lado irredutivel: a troca cai DENTRO da syscall.

        Entre stat(2) e unlink(2) nao ha como interpor verificacao: o Linux nao
        tem funlinkat(2) para remover "este inode". Se a troca acontecer nesse
        intervalo, o arquivo alheio ja e o alvo e se perde — isso o codigo nao
        evita, e o teste nao finge que evita. O que ele exige e que o desfecho
        nao seja sucesso silencioso: a pos-condicao ve o drop-in do projeto de
        volta no nome original, recusa fail-closed e nao dispara daemon-reload.
        """
        foreign = "# arquivo de terceiro\n[Service]\nEnvironment=X=1\n"
        target_dir, dropin, content, repoint = self._staged_dropin(foreign)
        repointed: list[str] = []
        real_unlink = os.unlink

        def repoint_then_unlink(path, *a, **kw):
            name = os.fspath(path)
            if not repointed and "asb-remove-" in name:
                repoint(name)
                repointed.append(name)
            return real_unlink(path, *a, **kw)

        with mock.patch("os.unlink", side_effect=repoint_then_unlink), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.remove_project_dropin(target_dir, expected_content=content)
        self.assertTrue(repointed, "a quarentena nao foi reapontada")
        self.assertIn("reapareceu", str(cm.exception))
        run.assert_not_called()
        self.assertTrue(dropin.is_file(), "o drop-in validado deveria seguir no nome original")
        self.assertEqual(dropin.read_text(encoding="utf-8"), content)

    def test_install_runtime_manifest_covers_all_asb_files_and_modes(self):
        """I3: Manifest must cover all files in asb/ package with sha256 and mode."""
        import json
        dest = install.install_runtime(
            self.fake_checkout,
            revision="rev-test-manifest",
            target_base=self.target_base,
        )
        manifest_path = dest / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("schemaVersion"), 1)
        self.assertEqual(manifest.get("revision"), "rev-test-manifest")
        files = manifest.get("files", {})
        self.assertIn("launcher.sh", files)
        self.assertIn("runtime_check.py", files)
        self.assertIn("asb/__init__.py", files)
        self.assertIn("asb/readiness.py", files)
        self.assertEqual(files["launcher.sh"]["mode"], 0o755)
        self.assertEqual(files["asb/__init__.py"]["mode"], (dest / "asb" / "__init__.py").stat().st_mode & 0o777)

    def test_check_and_remove_project_dropin_non_regular_file_rejected(self):
        """I4: Non-regular file (e.g. directory) as drop-in must return (False, False) and not be removed."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.mkdir(parents=True, exist_ok=True)

        exists, is_ours = install.check_project_dropin(target_dir)
        self.assertFalse(exists)
        self.assertFalse(is_ours)

        removed = install.remove_project_dropin(target_dir)
        self.assertFalse(removed)
        self.assertTrue(dropin.is_dir())

    def test_remove_project_dropin_parent_exists_but_file_absent(self):
        """I4: remove_project_dropin returns False when parent directory exists but drop-in file is absent."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        # Parent exists, but dropin file does not exist

        removed = install.remove_project_dropin(target_dir)
        self.assertFalse(removed)

    def test_unreadable_dropin_is_not_reported_as_absent(self):
        """R6: EACCES no drop-in nao e ausencia — ausencia faria a adocao seguir com ele ativo."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n", encoding="utf-8")
        # EACCES INJETADO, nao provocado por `chmod(0o000)`: o bit de permissao
        # nao se aplica a root, e sob root este teste falharia alto por motivo
        # de ambiente. Injetar cobre o ramo em qualquer euid.
        real_open = os.open

        def open_eacces(path, flags, *a, **kw):
            # Casamento QUALIFICADO pelo diretorio, nao pelo basename. Com so o
            # nome, um segundo `os.open(name, ..., O_NOFOLLOW, dir_fd=...)` que a
            # producao venha a fazer sobre outro diretorio com arquivo de mesmo
            # nome receberia este EACCES no lugar, e o teste passaria pelo motivo
            # errado — seguro apenas por coincidencia do codigo de hoje.
            # `/proc/self/fd/<n>` resolve o dir_fd para o caminho real.
            if os.fspath(path) == dropin.name and flags & os.O_NOFOLLOW:
                fd = kw.get("dir_fd")
                alvo = (fd is not None
                        and os.readlink(f"/proc/self/fd/{fd}") == os.fspath(dropin.parent))
                if alvo:
                    raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, flags, *a, **kw)

        with mock.patch("os.open", side_effect=open_eacces) as aberto, \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.check_project_dropin(target_dir)
            self.assertIn("ilegivel", str(cm.exception))
            with self.assertRaises(RuntimeError):
                install.remove_project_dropin(target_dir)
        run.assert_not_called()
        self.assertEqual(sorted(p.name for p in dropin.parent.iterdir()), [dropin.name])
        # Injecao observada: o EACCES tem de ter sido entregue pelo open DO
        # DROP-IN, e nao por acaso noutro caminho.
        self.assertTrue(
            [c for c in aberto.call_args_list
             if os.fspath(c.args[0]) == dropin.name and c.args[1] & os.O_NOFOLLOW],
            aberto.call_args_list)

    def test_unreadable_dropin_directory_is_not_reported_as_absent(self):
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        # Mesmo motivo: EACCES injetado no open do DIRETORIO.
        real_open = os.open

        def open_eacces(path, flags, *a, **kw):
            if os.fspath(path) == os.fspath(dropin.parent) and flags & os.O_DIRECTORY:
                raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, flags, *a, **kw)

        with mock.patch("os.open", side_effect=open_eacces) as aberto, \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.check_project_dropin(target_dir)
            self.assertIn("ilegivel", str(cm.exception))
            with self.assertRaises(RuntimeError):
                install.remove_project_dropin(target_dir)
        run.assert_not_called()
        # Injecao observada: o EACCES veio do open do DIRETORIO.
        self.assertTrue(
            [c for c in aberto.call_args_list
             if os.fspath(c.args[0]) == os.fspath(dropin.parent) and c.args[1] & os.O_DIRECTORY],
            aberto.call_args_list)

    def test_unreadable_quarantine_restores_the_dropin_and_fails_closed(self):
        """O ramo de recuperacao: se a releitura da quarentena levanta, o arquivo volta ao nome original."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        real = install._read_regular_at
        calls = []

        def flaky(dir_fd, name):
            calls.append(name)
            if len(calls) > 1:  # a segunda leitura e a da quarentena
                raise RuntimeError("quarentena ilegivel")
            return real(dir_fd, name)

        with mock.patch.object(install, "_read_regular_at", side_effect=flaky), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.remove_project_dropin(target_dir, expected_content=content)
        # O diagnostico tem de nomear a causa real. Dizer "substituido" aqui
        # mandaria o operador cacar uma troca que nao houve (R6 no diagnostico).
        self.assertIn("ilegivel", str(cm.exception))
        self.assertNotIn("substitu", str(cm.exception))
        run.assert_not_called()
        self.assertEqual(dropin.read_text(encoding="utf-8"), content)
        self.assertEqual(sorted(p.name for p in dropin.parent.iterdir()), [dropin.name])

    def test_symlinked_dropin_is_neither_followed_nor_removed(self):
        """ELOOP com O_NOFOLLOW: um symlink no lugar do drop-in nao e drop-in do projeto."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        pointed = self.tmp_path / "alheio.conf"
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        pointed.write_text(content, encoding="utf-8")
        dropin.symlink_to(pointed)
        with mock.patch("subprocess.run") as run:
            self.assertEqual(install.check_project_dropin(target_dir), (False, False))
            self.assertFalse(install.remove_project_dropin(target_dir))
        run.assert_not_called()
        self.assertTrue(dropin.is_symlink())
        self.assertEqual(pointed.read_text(encoding="utf-8"), content)


    # --- Gate r13: preservacao de arquivo alheio e revalidacao de identidade ---
    #
    # Os tres prisoner tests abaixo cobrem os dois bloqueadores que o controller
    # reproduziu isoladamente: `restore_project_dropin` mudando arquivo alheio
    # atraves de symlink, e mutacao acontecendo antes da primeira revalidacao de
    # identidade.

    def test_restore_refuses_a_symlink_and_leaves_the_foreign_target_untouched(self):
        """Bloqueador 1: `is_file`/`read_text`/`stat`/`chmod` seguem symlink.

        Com um symlink no nome do drop-in, a restauracao lia, media e mudava o
        modo do ARQUIVO APONTADO — arquivo de terceiro, fora do `.d` do
        projeto. O invariante 6 do brief ("preserva drop-ins alheios") nao
        admite mudar modo nem conteudo de arquivo que a adocao nao criou.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        foreign = self.tmp_path / "alheio.conf"
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        foreign.write_text(content, encoding="utf-8")
        foreign.chmod(0o600)
        dropin.symlink_to(foreign)

        with mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.restore_project_dropin(target_dir, content=content, mode=0o644)
        self.assertIn("symlink", str(cm.exception))
        run.assert_not_called()
        # O modo do alvo estrangeiro e a evidencia exata que o controller mediu.
        self.assertEqual(foreign.stat().st_mode & 0o777, 0o600)
        self.assertEqual(foreign.read_text(encoding="utf-8"), content)
        self.assertTrue(dropin.is_symlink())

    def test_restore_refuses_a_dangling_symlink_instead_of_creating_the_target(self):
        """O mesmo defeito no ramo de criacao, com desfecho pior.

        Num symlink pendurado `is_file()` e False, entao a restauracao caia no
        ramo de criacao — e `write_text` segue o link e CRIA o arquivo
        apontado, num caminho escolhido por quem plantou o link.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        foreign = self.tmp_path / "alvo-inexistente.conf"
        dropin.symlink_to(foreign)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"

        with mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.restore_project_dropin(target_dir, content=content, mode=0o644)
        self.assertIn("symlink", str(cm.exception))
        run.assert_not_called()
        self.assertFalse(foreign.exists(), "o alvo do symlink pendurado foi criado")
        self.assertTrue(dropin.is_symlink())

    def test_removal_revalidates_identity_before_the_rename(self):
        """Bloqueador 2, remocao: o rename(2) e a PRIMEIRA mutacao.

        O `verify` so era chamado depois do rename, e o rename ja tirou o
        drop-in do nome original — desarmando o podman-restart sob uma
        identidade que pode ter deixado de valer. Entre a autorizacao do
        chamador e o rename correm a leitura do arquivo, a classificacao de
        autoria e as comparacoes de conteudo e modo.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        dropin.chmod(0o644)
        ino = dropin.stat().st_ino

        def divergent():
            raise ValueError("ID divergente")

        with mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError) as cm:
                install.remove_project_dropin(
                    target_dir, expected_content=content, expected_mode=0o644,
                    verify=divergent)
        self.assertIn("ID divergente", str(cm.exception))
        run.assert_not_called()
        # O drop-in continua no nome original, mesmo inode, e o diretorio nao
        # guarda quarentena orfa: nenhuma mutacao aconteceu.
        self.assertEqual(sorted(q.name for q in dropin.parent.iterdir()), [dropin.name])
        self.assertEqual(dropin.stat().st_ino, ino)
        self.assertEqual(dropin.read_text(encoding="utf-8"), content)

    def test_restore_revalidates_identity_before_every_mutation(self):
        """Bloqueador 2, restauracao: mkdir, escrita, chmod e reload vem DEPOIS.

        Uma unica validacao no chamador autoriza a entrada e mais nada. Cada
        uma das quatro mutacoes desta funcao precisa do gancho imediatamente
        antes de si.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"

        def divergent():
            raise ValueError("ID divergente")

        # (a) criacao: levantar no gancho nao deixa diretorio, arquivo nem reload
        with mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError):
                install.restore_project_dropin(
                    target_dir, content=content, mode=0o644, verify=divergent)
        run.assert_not_called()
        self.assertFalse(dropin.exists())
        self.assertFalse(dropin.parent.exists(), "o diretorio foi criado sob identidade obsoleta")

        # (b) criacao autorizada: o gancho roda antes da escrita E antes do reload
        calls: list[str] = []
        with mock.patch("subprocess.run") as run:
            self.assertTrue(install.restore_project_dropin(
                target_dir, content=content, mode=0o644, verify=lambda: calls.append("v")))
        # Contagem EXATA. Com `>= 2` um mutante que apagasse o gancho de antes
        # do fchmod ou o de antes do daemon-reload deixaria 2 e passaria: o
        # caminho de criacao com `mode` tem tres (antes do O_EXCL open, antes do
        # fchmod, antes do reload) mais um antes do mkdir = 4.
        self.assertEqual(len(calls), 4, f"gancho chamado {len(calls)}x, esperado 4")
        run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)
        self.assertEqual(dropin.read_text(encoding="utf-8"), content)
        self.assertEqual(dropin.stat().st_mode & 0o777, 0o644)

        # (c) correcao de modo num drop-in presente tambem e mutacao
        dropin.chmod(0o600)
        with mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError):
                install.restore_project_dropin(
                    target_dir, content=content, mode=0o644, verify=divergent)
        self.assertEqual(dropin.stat().st_mode & 0o777, 0o600)
        run.assert_not_called()


    # --- Lacunas de ramo apontadas pelo Test Shape Auditor da rodada 8 -------

    def test_fifo_at_the_dropin_name_does_not_hang_and_fails_closed(self):
        """Critical da rodada 8: `O_NOFOLLOW` nao protege contra FIFO.

        Num FIFO o `open(2)` para leitura bloqueia no kernel enquanto nao houver
        escritor — antes do `fstat` e portanto antes do `S_ISREG` que rejeitaria
        a entrada. As duas chamadas de producao rodam dentro do `_AdoptionLock`,
        que segura um `flock` exclusivo durante todo o `with`: travar ali levaria
        o lock consigo e nenhuma adocao de keyring voltaria a rodar no host,
        contra o invariante 3 do brief ("sem travar indefinidamente").

        O alarme e a asserção: sem `O_NONBLOCK` este teste nao falha, ele pendura
        — e o alarme o converte em falha visivel.
        """
        import signal
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(dropin)

        def bloqueou(*_):
            raise AssertionError("bloqueou no FIFO: falta O_NONBLOCK no open")

        antigo = signal.signal(signal.SIGALRM, bloqueou)
        signal.alarm(5)
        try:
            with mock.patch("subprocess.run") as run:
                # Leitura: FIFO nao e arquivo regular, entao "nao ha drop-in".
                self.assertEqual(install.check_project_dropin(target_dir), (False, False))
                self.assertEqual(install.read_project_dropin(target_dir),
                                 (False, False, None, None))
                # Remocao: nada a remover, e nada removido.
                self.assertFalse(install.remove_project_dropin(target_dir))
                # Restauracao: entrada nao-regular recusa fechado.
                with self.assertRaises(RuntimeError) as cm:
                    install.restore_project_dropin(target_dir, content="x", mode=0o644)
            self.assertIn("symlink", str(cm.exception))
            run.assert_not_called()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, antigo)
        # O FIFO sobreviveu: nenhuma das tres funcoes mexeu nele.
        self.assertTrue(stat.S_ISFIFO(os.stat(dropin, follow_symlinks=False).st_mode))

    def test_entry_replaced_between_the_lstat_and_the_read_fails_closed(self):
        """Ramo `found is None` depois de um lstat bem-sucedido, em restore.

        Guarda fail-closed contra TOCTOU: o lstat viu arquivo regular e a
        leitura seguinte nao encontrou um. Seguir adiante restauraria sob uma
        identidade que deixou de valer.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")

        with mock.patch.object(install, "_read_regular_at", return_value=None) as leitura, \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.restore_project_dropin(target_dir, content=content, mode=0o644)
        self.assertIn("deixou de ser arquivo regular", str(cm.exception))
        run.assert_not_called()
        # O patch tem de ser OBSERVADO (test-shape.md, "Unasserted mocks"): sem
        # isto, apagar a chamada a `_read_regular_at` na producao deixaria o
        # teste verde e o mock esconderia o call site removido (R7).
        leitura.assert_called_once()
        self.assertEqual(leitura.call_args.args[1], dropin.name)
        self.assertEqual(dropin.read_text(encoding="utf-8"), content)

    def test_entry_appearing_between_the_check_and_the_create_is_not_overwritten(self):
        """Ramo `FileExistsError` do `O_CREAT|O_EXCL`.

        E a garantia que o docstring destaca: quem aparecer no nome entre a
        checagem e a criacao NAO e sobrescrito. O gancho `verify` roda
        imediatamente antes do open, entao plantar o arquivo ali reproduz a
        corrida exata sem depender de temporizacao.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        alheio = "# de terceiro\n[Service]\nEnvironment=X=1\n"

        def planta():
            dropin.parent.mkdir(parents=True, exist_ok=True)
            if not dropin.exists():
                dropin.write_text(alheio, encoding="utf-8")

        with mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.restore_project_dropin(
                    target_dir, content="nosso conteudo", mode=0o644, verify=planta)
        self.assertIn("nao foi sobrescrito", str(cm.exception))
        run.assert_not_called()
        self.assertEqual(dropin.read_text(encoding="utf-8"), alheio)

    def test_inode_swapped_between_validation_and_chmod_is_refused(self):
        """Recheque de inode do `_fchmod_regular_at`.

        E a ultima guarda antes de o `fchmod` executar. O gancho roda
        imediatamente antes dela, entao trocar o arquivo por outro regular ali
        entrega um `st` obsoleto para a funcao conferir.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        dropin.chmod(0o600)

        outro = self.tmp_path / "outro.conf"
        outro.write_text(content, encoding="utf-8")
        outro.chmod(0o600)
        ino_outro = outro.stat().st_ino

        def troca():
            os.replace(outro, dropin)

        with mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as cm:
                install.restore_project_dropin(
                    target_dir, content=content, mode=0o644, verify=troca)
        self.assertIn("deixou de ser o arquivo validado", str(cm.exception))
        run.assert_not_called()
        # O arquivo trocado ficou com o modo original: nenhum fchmod aconteceu.
        st = os.stat(dropin, follow_symlinks=False)
        self.assertEqual((st.st_ino, st.st_mode & 0o777), (ino_outro, 0o600))

    def test_no_mutation_when_the_existing_dropin_already_matches(self):
        """Modo e conteudo ja corretos: nenhuma mutacao, nenhum gancho."""
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        dropin.chmod(0o644)
        calls: list[str] = []

        with mock.patch("subprocess.run") as run:
            self.assertTrue(install.restore_project_dropin(
                target_dir, content=content, mode=0o644, verify=lambda: calls.append("v")))
            # E tambem com mode=None, que nao pode inventar mutacao.
            self.assertTrue(install.restore_project_dropin(
                target_dir, content=content, mode=None, verify=lambda: calls.append("v")))
        self.assertEqual(calls, [], "gancho chamado sem haver mutacao")
        run.assert_not_called()
        self.assertEqual(dropin.stat().st_mode & 0o777, 0o644)

    def test_read_project_dropin_returns_content_and_mode_of_the_entry_read(self):
        """As quatro posicoes da tupla, afirmadas diretamente.

        `check_project_dropin` descarta conteudo e modo, e o unico consumidor
        deles grava no diario. Sem este teste, um mutante devolvendo
        `(exists, ours, None, None)` — ou trocando conteudo por modo — passava a
        suite inteira.
        """
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)

        # Ausente
        self.assertEqual(install.read_project_dropin(target_dir), (False, False, None, None))

        # Presente e do projeto
        nosso = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(nosso, encoding="utf-8")
        dropin.chmod(0o640)
        self.assertEqual(install.read_project_dropin(target_dir), (True, True, nosso, 0o640))

        # Presente e alheio: conteudo e modo continuam sendo os do arquivo lido
        alheio = "[Service]\nEnvironment=ALHEIO=1\n"
        dropin.write_text(alheio, encoding="utf-8")
        dropin.chmod(0o604)
        self.assertEqual(install.read_project_dropin(target_dir), (True, False, alheio, 0o604))

        # E a delegacao de check_project_dropin concorda com as duas primeiras
        self.assertEqual(install.check_project_dropin(target_dir), (True, False))


    def test_fifo_substituted_before_the_chmod_is_refused_without_hanging(self):
        """Important da rodada 9: o `S_ISREG` e o `O_NONBLOCK` de `_fchmod_regular_at`.

        O teste de troca de inode substitui por outro arquivo REGULAR, entao so
        exercita o disjunto de inode. Trocar por um FIFO alcanca o outro
        disjunto — e, mais importante, e o unico input que faria o `O_NONBLOCK`
        desta funcao valer: sem ele o `os.open` penduraria aqui dentro, com o
        `_AdoptionLock` seguro, que e exatamente o Critical da rodada 8 numa
        segunda funcao.

        O alarme e a asserção: sem `O_NONBLOCK` isto nao falha, pendura.
        """
        import signal
        target_dir = self.tmp_path / "systemd_user"
        dropin = install.get_dropin_path(target_dir)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        content = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content, encoding="utf-8")
        dropin.chmod(0o600)

        modo_fifo: list[int] = []

        def troca_por_fifo():
            dropin.unlink()
            os.mkfifo(dropin)
            # Modo MEDIDO, nao presumido: `mkfifo` cria com 0o666 & ~umask e nao
            # herda o modo do arquivo que estava ali. A primeira versao deste
            # teste assertou 0o600 e falhou contra producao correta (420 != 384).
            modo_fifo.append(os.stat(dropin, follow_symlinks=False).st_mode & 0o777)

        def bloqueou(*_):
            raise AssertionError("bloqueou no FIFO: falta O_NONBLOCK em _fchmod_regular_at")

        antigo = signal.signal(signal.SIGALRM, bloqueou)
        signal.alarm(5)
        try:
            with mock.patch("subprocess.run") as run:
                with self.assertRaises(RuntimeError) as cm:
                    install.restore_project_dropin(
                        target_dir, content=content, mode=0o644, verify=troca_por_fifo)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, antigo)
        self.assertIn("deixou de ser o arquivo validado", str(cm.exception))
        run.assert_not_called()
        # O FIFO sobreviveu intacto: nenhum fchmod foi aplicado nele.
        st = os.stat(dropin, follow_symlinks=False)
        self.assertTrue(stat.S_ISFIFO(st.st_mode))
        self.assertEqual(st.st_mode & 0o777, modo_fifo[0],
                         "o modo do FIFO mudou: houve fchmod numa entrada nao-regular")


if __name__ == "__main__":
    unittest.main()

