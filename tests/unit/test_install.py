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


if __name__ == "__main__":
    unittest.main()

