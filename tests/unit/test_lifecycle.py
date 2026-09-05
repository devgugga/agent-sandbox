import tempfile
import unittest
from pathlib import Path

from cli.asb.lifecycle import discover_mise_dirs


class TestDiscoverMiseDirs(unittest.TestCase):
    def test_nonexistent_directory_returns_empty(self):
        self.assertEqual(discover_mise_dirs(Path("/nonexistent/path/12345")), [])

    def test_empty_directory_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_mise_dirs(Path(tmp)), [])

    def test_root_mise_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mise.toml").touch()
            self.assertEqual(discover_mise_dirs(root), [root])

    def test_subdirectories_found_and_sorted_with_root_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mise.toml").touch()
            sub1 = root / "pacs" / "server"
            sub1.mkdir(parents=True)
            (sub1 / "mise.toml").touch()
            sub2 = root / "portal" / "front"
            sub2.mkdir(parents=True)
            (sub2 / "mise.toml").touch()

            dirs = discover_mise_dirs(root)
            self.assertEqual(dirs[0], root)
            self.assertEqual(set(dirs), {root, sub1, sub2})

    def test_pruned_directories_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mise.toml").touch()

            git_dir = root / ".git" / "hooks"
            git_dir.mkdir(parents=True)
            (git_dir / "mise.toml").touch()

            node_modules = root / "node_modules" / "some-pkg"
            node_modules.mkdir(parents=True)
            (node_modules / "mise.toml").touch()

            venv = root / ".venv" / "sub"
            venv.mkdir(parents=True)
            (venv / "mise.toml").touch()

            target = root / "target" / "classes"
            target.mkdir(parents=True)
            (target / "mise.toml").touch()

            valid = root / "apps" / "service"
            valid.mkdir(parents=True)
            (valid / "mise.toml").touch()

            dirs = discover_mise_dirs(root)
            self.assertEqual(dirs, [root, valid])


class TestReloadAllowlist(unittest.TestCase):
    def test_reload_allowlist_renders_squid_and_restarts_proxy(self):
        from unittest import mock
        from cli.asb.lifecycle import reload_allowlist
        from cli.asb.workspace import Layout

        fake_n = {"proxy": "asb-test-ws-proxy"}
        with tempfile.TemporaryDirectory() as tmp_root_dir, \
             tempfile.TemporaryDirectory() as tmp_state_dir:
            fake_root = Path(tmp_root_dir)
            fake_state = Path(tmp_state_dir)
            fake_layout = Layout(
                ws="test-ws",
                project="proj",
                mount=Path("/tmp/fake-mount"),
                project_root=Path("/tmp/fake-mount/proj"),
                state=fake_state,
            )
            (fake_root / "image" / "squid").mkdir(parents=True)
            (fake_root / "image" / "squid" / "allowlist-base.txt").touch()
            (fake_root / "image" / "squid" / "squid.conf.tmpl").touch()
            fake_profile = mock.MagicMock()

            with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp/home"), Path("/tmp/origin"))), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl allowlist ..."), \
                 mock.patch("cli.asb.podman.exists", return_value=True), \
                 mock.patch("cli.asb.podman.run") as mock_podman_run:
                rc = reload_allowlist(fake_root, "test-ws")
                self.assertEqual(rc, 0)
                mock_podman_run.assert_called_once_with("restart", "asb-test-ws-proxy")
                conf_content = (fake_state / "squid.conf").read_text()
                self.assertEqual(conf_content, "acl allowlist ...")


if __name__ == "__main__":
    unittest.main()

