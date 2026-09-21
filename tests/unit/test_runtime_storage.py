"""Testes de cli/asb/runtime/storage.py — volumes de credencial, sessao e
cache de ferramentas, e os argumentos de mount que os expoem ao agente
(Tarefa 3 da decomposicao de modulos).

Nenhum teste aqui toca Podman nem mountpoint reais: `podman.exists`,
`podman.run` e `podman.out` sao sempre mockados, e cada teste que precisa de
um "mountpoint" usa um diretorio temporario real, nunca o volume de
producao. Ver `tests/unit/asb_test_isolation.py` para a garantia imposta.
"""
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.asb import podman
from cli.asb.runtime.storage import (
    CREDENTIAL_DIRS,
    LEGACY_ROOT_CREDENTIAL_FILES,
    SESSION_STATE_DIRS,
    RuntimeStorage,
    _mkdir_private,
    _volume_mountpoint,
    credential_mount_args,
    ensure_credential_dirs,
    ensure_credentials_volume,
    ensure_session_volume,
    ensure_toolcache_volume,
    session_mount_args,
    warn_about_legacy_credential_layout,
)


class _FakeTransaction:
    """Duplo minimo de `runtime.transaction.WorkspaceTransaction`: so o que
    `ensure_session_volume` chama."""

    def __init__(self):
        self.recorded: list[str] = []

    def record_volume(self, volume_name: str) -> None:
        self.recorded.append(volume_name)


class TestEnsureCredentialsVolume(unittest.TestCase):
    def test_creates_the_volume_when_missing(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=False) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            vol = ensure_credentials_volume()
        self.assertEqual(vol, "asb-credentials")
        exists.assert_called_once_with("volume", "asb-credentials")
        run.assert_called_once_with("volume", "create", "asb-credentials")

    def test_does_not_recreate_an_existing_volume(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            vol = ensure_credentials_volume()
        self.assertEqual(vol, "asb-credentials")
        run.assert_not_called()

    def test_env_var_overrides_the_default_name(self):
        with mock.patch.dict(os.environ, {"ASB_CREDENTIALS_VOLUME": "asb-custom-creds"}), \
                mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run"):
            vol = ensure_credentials_volume()
        self.assertEqual(vol, "asb-custom-creds")
        exists.assert_called_once_with("volume", "asb-custom-creds")


class TestEnsureToolcacheVolume(unittest.TestCase):
    def test_creates_the_volume_when_missing(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=False) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            vol = ensure_toolcache_volume()
        self.assertEqual(vol, "asb-toolcache")
        exists.assert_called_once_with("volume", "asb-toolcache")
        run.assert_called_once_with("volume", "create", "asb-toolcache")

    def test_does_not_recreate_an_existing_volume(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            ensure_toolcache_volume()
        run.assert_not_called()

    def test_env_var_overrides_the_default_name(self):
        with mock.patch.dict(os.environ, {"ASB_TOOLCACHE_VOLUME": "asb-custom-tools"}), \
                mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run"):
            vol = ensure_toolcache_volume()
        self.assertEqual(vol, "asb-custom-tools")
        exists.assert_called_once_with("volume", "asb-custom-tools")


class TestVolumeMountpoint(unittest.TestCase):
    def test_a_relative_or_missing_mountpoint_is_an_actionable_error(self):
        with mock.patch("cli.asb.runtime.storage.podman.out", return_value="127.0.0.1:2222\n"):
            with self.assertRaises(podman.PodmanError) as ctx:
                _volume_mountpoint("asb-credentials")
        self.assertIn("asb-credentials", str(ctx.exception))
        self.assertIn("nao e um diretorio do host", str(ctx.exception))

    def test_an_absolute_directory_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("cli.asb.runtime.storage.podman.out", return_value=tmp):
                self.assertEqual(_volume_mountpoint("asb-credentials"), Path(tmp))


class TestMkdirPrivate(unittest.TestCase):
    def test_every_subpath_is_created_mode_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp)
            _mkdir_private(mountpoint, ["claude", "codex"], "asb-credentials")
            for sub in ("claude", "codex"):
                path = mountpoint / sub
                self.assertTrue(path.is_dir())
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_existing_directories_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp)
            existing = mountpoint / "claude"
            existing.mkdir()
            (existing / "marker.json").write_text("{}")
            _mkdir_private(mountpoint, ["claude"], "asb-credentials")
            self.assertEqual((existing / "marker.json").read_text(), "{}")

    def test_an_unwritable_mountpoint_becomes_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir(mode=0o500)
            try:
                with self.assertRaises(podman.PodmanError) as ctx:
                    _mkdir_private(mountpoint, ["claude"], "asb-credentials")
            finally:
                mountpoint.chmod(0o700)
        message = str(ctx.exception)
        self.assertIn(str(mountpoint / "claude"), message)
        self.assertIn("podman unshare chown", message)


class TestCredentialMountArgs(unittest.TestCase):
    """Ordem exata dos argumentos: claude antes de codex, cada par
    `--mount <spec>` na mesma posicao que `CREDENTIAL_DIRS` declara."""

    def test_mount_args_follow_credential_dirs_order_exactly(self):
        with mock.patch("cli.asb.runtime.storage.ensure_credentials_volume",
                        return_value="asb-credentials"), \
                mock.patch("cli.asb.runtime.storage.ensure_credential_dirs"):
            args = credential_mount_args(Path("/home/tester"))

        expected: list[str] = []
        for sub, rel in CREDENTIAL_DIRS.items():
            expected += ["--mount",
                        f"type=volume,src=asb-credentials,"
                        f"dst=/home/tester/{rel},"
                        f"volume-subpath={sub},relabel=shared"]
        self.assertEqual(args, expected)

    def test_delegates_credential_dir_creation_to_the_resolved_volume(self):
        with mock.patch("cli.asb.runtime.storage.ensure_credentials_volume",
                        return_value="asb-credentials"), \
                mock.patch("cli.asb.runtime.storage.ensure_credential_dirs") as dirs:
            credential_mount_args(Path("/home/tester"))
        dirs.assert_called_once_with("asb-credentials")

    def test_creates_provider_subdirectories_mode_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                    mock.patch("cli.asb.runtime.storage.podman.out", return_value=str(mountpoint)):
                credential_mount_args(Path("/home/tester"))
            for sub in ("claude", "codex"):
                path = mountpoint / sub
                self.assertTrue(path.is_dir())
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_an_invalid_mountpoint_propagates_as_podman_error(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                mock.patch("cli.asb.runtime.storage.podman.out", return_value="not-absolute"):
            with self.assertRaises(podman.PodmanError):
                credential_mount_args(Path("/home/tester"))


class TestEnsureCredentialDirs(unittest.TestCase):
    def test_warns_about_the_legacy_root_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            (mountpoint / "claude.json").write_text('{"legado": true}')
            with mock.patch("cli.asb.runtime.storage.podman.out", return_value=str(mountpoint)), \
                    mock.patch("sys.stderr") as stderr:
                ensure_credential_dirs("asb-credentials")
            joined = "".join(str(c.args[0]) for c in stderr.write.call_args_list)
            self.assertIn("layout ANTIGO", joined)
            self.assertIn("claude.json", joined)


class TestLegacyCredentialLayoutWarning(unittest.TestCase):
    def test_a_clean_volume_produces_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("sys.stderr") as stderr:
            warn_about_legacy_credential_layout(Path(tmp))
        stderr.write.assert_not_called()

    def test_every_legacy_filename_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp)
            for name in LEGACY_ROOT_CREDENTIAL_FILES:
                (mountpoint / name).write_text("{}")
            with mock.patch("sys.stderr") as stderr:
                warn_about_legacy_credential_layout(mountpoint)
            joined = "".join(str(c.args[0]) for c in stderr.write.call_args_list)
            for name in LEGACY_ROOT_CREDENTIAL_FILES:
                self.assertIn(name, joined)

    def test_never_deletes_or_moves_the_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp)
            legacy = mountpoint / "claude.json"
            legacy.write_text('{"legado": true}')
            warn_about_legacy_credential_layout(mountpoint)
            self.assertTrue(legacy.is_file())
            self.assertEqual(legacy.read_text(), '{"legado": true}')


class TestEnsureSessionVolume(unittest.TestCase):
    def test_creates_a_missing_volume_and_registers_it_with_the_transaction(self):
        tx = _FakeTransaction()
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=False) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run") as run, \
                mock.patch("cli.asb.runtime.storage.podman.out", return_value="/tmp"), \
                mock.patch("cli.asb.runtime.storage._mkdir_private"):
            vol = ensure_session_volume("demo", tx)
        self.assertEqual(vol, "asb-demo-session")
        exists.assert_called_once_with("volume", "asb-demo-session")
        run.assert_called_once_with("volume", "create", "asb-demo-session")
        self.assertEqual(tx.recorded, ["asb-demo-session"])

    def test_never_registers_a_preexisting_volume(self):
        """Ownership da transacao: `up` so pode desfazer o que ELE criou. Um
        volume de sessao que ja existia (workspace revivido) nunca pode ser
        removido no rollback de uma tentativa seguinte."""
        tx = _FakeTransaction()
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True) as exists, \
                mock.patch("cli.asb.runtime.storage.podman.run") as run, \
                mock.patch("cli.asb.runtime.storage.podman.out", return_value="/tmp"), \
                mock.patch("cli.asb.runtime.storage._mkdir_private"):
            ensure_session_volume("demo", tx)
        run.assert_not_called()
        self.assertEqual(tx.recorded, [])

    def test_works_without_a_transaction(self):
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=False), \
                mock.patch("cli.asb.runtime.storage.podman.run"), \
                mock.patch("cli.asb.runtime.storage.podman.out", return_value="/tmp"), \
                mock.patch("cli.asb.runtime.storage._mkdir_private"):
            vol = ensure_session_volume("demo")
        self.assertEqual(vol, "asb-demo-session")

    def test_creates_the_session_state_subdirectories_mode_0700(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                    mock.patch("cli.asb.runtime.storage.podman.out", return_value=str(mountpoint)):
                ensure_session_volume("demo")
            for sub in SESSION_STATE_DIRS:
                path = mountpoint / sub
                self.assertTrue(path.is_dir(), f"{sub} nao foi criado")
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)


class TestSessionMountArgs(unittest.TestCase):
    def test_mount_args_follow_session_state_dirs_order_exactly(self):
        args = session_mount_args("asb-demo-session", Path("/home/tester"))

        expected: list[str] = []
        for sub, rel in SESSION_STATE_DIRS.items():
            expected += ["--mount",
                        f"type=volume,src=asb-demo-session,"
                        f"dst=/home/tester/{rel},"
                        f"volume-subpath={sub},relabel=shared"]
        self.assertEqual(args, expected)


class TestRuntimeStorageInterface(unittest.TestCase):
    """`RuntimeStorage` e so a fronteira injetavel: cada metodo tem de
    devolver exatamente o que a funcao livre correspondente devolveria."""

    def test_ensure_credentials_delegates_to_the_free_function(self):
        storage = RuntimeStorage(Path("/home/tester"))
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            vol = storage.ensure_credentials()
        self.assertEqual(vol, "asb-credentials")
        run.assert_not_called()

    def test_credential_mounts_uses_the_home_given_at_construction(self):
        storage = RuntimeStorage(Path("/home/tester"))
        with mock.patch("cli.asb.runtime.storage.ensure_credentials_volume",
                        return_value="asb-credentials"), \
                mock.patch("cli.asb.runtime.storage.ensure_credential_dirs"):
            args = storage.credential_mounts()
        self.assertIn("dst=/home/tester/.claude", " ".join(args))
        self.assertIn("dst=/home/tester/.codex", " ".join(args))

    def test_ensure_sessions_creates_and_registers_with_the_given_transaction(self):
        storage = RuntimeStorage(Path("/home/tester"))
        tx = _FakeTransaction()
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=False), \
                mock.patch("cli.asb.runtime.storage.podman.run"), \
                mock.patch("cli.asb.runtime.storage.podman.out", return_value="/tmp"), \
                mock.patch("cli.asb.runtime.storage._mkdir_private"):
            vol = storage.ensure_sessions("demo", tx)
        self.assertEqual(vol, "asb-demo-session")
        self.assertEqual(tx.recorded, ["asb-demo-session"])

    def test_session_mounts_uses_the_home_given_at_construction_and_the_vol_argument(self):
        storage = RuntimeStorage(Path("/home/tester"))
        args = storage.session_mounts("asb-demo-session")
        joined = " ".join(args)
        self.assertIn("src=asb-demo-session", joined)
        self.assertIn("dst=/home/tester/.claude/projects", joined)

    def test_ensure_toolcache_delegates_to_the_free_function(self):
        storage = RuntimeStorage(Path("/home/tester"))
        with mock.patch("cli.asb.runtime.storage.podman.exists", return_value=True), \
                mock.patch("cli.asb.runtime.storage.podman.run") as run:
            vol = storage.ensure_toolcache()
        self.assertEqual(vol, "asb-toolcache")
        run.assert_not_called()

    def test_credential_and_session_mounts_never_collide_on_the_same_volume(self):
        """I6: a credencial e compartilhada, a sessao nao — as duas listas de
        mount nunca podem citar o mesmo volume como origem."""
        storage = RuntimeStorage(Path("/home/tester"))
        with mock.patch("cli.asb.runtime.storage.ensure_credentials_volume",
                        return_value="asb-credentials"), \
                mock.patch("cli.asb.runtime.storage.ensure_credential_dirs"):
            credential_args = storage.credential_mounts()
        session_args = storage.session_mounts("asb-demo-session")
        self.assertIn("src=asb-credentials", " ".join(credential_args))
        self.assertIn("src=asb-demo-session", " ".join(session_args))
        self.assertNotIn("src=asb-demo-session", " ".join(credential_args))
        self.assertNotIn("src=asb-credentials", " ".join(session_args))


if __name__ == "__main__":
    unittest.main()
