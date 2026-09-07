import os
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

    def test_reload_allowlist_ignora_o_perfil_editavel_pelo_agente(self):
        """A politica de egresso e do operador, nunca do agente.

        `layout.project_root` fica DENTRO do mount gravavel — o proprio
        workspace.py documenta a invariante ao colocar `state/` fora dele:
        "Nunca dentro do mount (o agente editaria a propria allowlist)".

        Se o reload preferisse a copia do clone, um agente acrescentaria um
        dominio ao proprio `.agent-sandbox.toml` e o operador o aplicaria sem
        saber, ao rodar `reload-allowlist` por qualquer outro motivo. O
        operador vira o carteiro da politica do agente.
        """
        from unittest import mock
        from cli.asb.lifecycle import reload_allowlist
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin = base / "origin"
            clone = base / "mount" / "proj"
            state = base / "state"
            for d in (origin, clone, state):
                d.mkdir(parents=True)
            (base / "image" / "squid").mkdir(parents=True)
            (base / "image" / "squid" / "allowlist-base.txt").touch()
            (base / "image" / "squid" / "squid.conf.tmpl").touch()

            (origin / ".agent-sandbox.toml").write_text(
                '[network]\nallow = ["registry.npmjs.org"]\n')
            # O clone precisa ser COMPROVADAMENTE mais novo: e essa a
            # condicao sob a qual a heuristica de mtime preferia a copia do
            # agente. Fixar os dois mtimes torna o teste deterministico.
            clone_toml = clone / ".agent-sandbox.toml"
            clone_toml.write_text('[network]\nallow = ["exfil.example"]\n')
            os.utime(origin / ".agent-sandbox.toml", (10**9, 10**9))
            os.utime(clone_toml, (10**9 + 500, 10**9 + 500))
            assert (clone_toml.stat().st_mtime
                    > (origin / ".agent-sandbox.toml").stat().st_mtime)

            layout = Layout(ws="ws", project="proj", mount=base / "mount",
                            project_root=clone, state=state)

            with mock.patch("cli.asb.lifecycle._require_workspace",
                            return_value=({"proxy": "p"}, base, origin)), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=layout), \
                 mock.patch("cli.asb.lifecycle.load_profile") as mock_load, \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl x"), \
                 mock.patch("cli.asb.podman.exists", return_value=True), \
                 mock.patch("cli.asb.podman.run"):
                reload_allowlist(base, "ws")

            mock_load.assert_called_once_with(origin)


class TestLifecycleOrdering(unittest.TestCase):
    def test_up_ensures_rootless_netns_before_proxy_run(self):
        from unittest import mock
        from cli.asb.lifecycle import _up
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        events: list[str] = []

        def fake_run(*args, **kwargs):
            if len(args) >= 4 and args[0] == "run" and "--name" in args:
                idx = args.index("--name") + 1
                if args[idx] == "asb-test-ws-proxy":
                    events.append("podman run proxy")
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            fake_layout = Layout(
                ws="test-ws",
                project="proj",
                mount=fake_mount,
                project_root=fake_mount / "proj",
                state=fake_state,
            )
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
            fake_pass = tmp / "keyring.pass"
            fake_pass.write_text("secret")

            fake_profile = Profile(
                services=[],
                host_ports=[],
                publish_ports=[],
                host_api="none",
                container_mode="standard",
                allow=[],
            )

            def fake_exists(kind: str, name: str) -> bool:
                if kind == "container" and name == "asb-test-ws-agent":
                    return False
                return True

            with mock.patch("cli.asb.lifecycle.podman.exists", side_effect=fake_exists), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns", side_effect=lambda: events.append("ensure_rootless_netns")), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="run-vol"), \
                 mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl allow ..."), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_pass", return_value=fake_pass), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="cred-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="tool-vol"), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0), \
                 mock.patch("cli.asb.install.podman_restart"):
                rc = _up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            self.assertIn("ensure_rootless_netns", events)
            self.assertIn("podman run proxy", events)
            self.assertLess(
                events.index("ensure_rootless_netns"),
                events.index("podman run proxy"),
            )

    def test_resume_ensures_rootless_netns_before_proxy_start(self):
        from unittest import mock
        from cli.asb.lifecycle import resume
        from cli.asb.workspace import Layout

        events: list[str] = []

        def fake_run(*args, **kwargs):
            if len(args) >= 2 and args[0] == "start" and args[1] == "asb-test-ws-proxy":
                events.append("podman start proxy")
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_origin = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_origin):
                d.mkdir(parents=True)
            fake_layout = Layout(
                ws="test-ws",
                project="proj",
                mount=fake_mount,
                project_root=fake_mount / "proj",
                state=fake_state,
            )
            fake_names = {
                "net": "asb-test-ws",
                "out": "asb-test-ws-out",
                "agent": "asb-test-ws-agent",
                "proxy": "asb-test-ws-proxy",
            }

            with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_names, tmp / "home", fake_origin)), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns", side_effect=lambda: events.append("ensure_rootless_netns")), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
                 mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.lifecycle.podman.out", return_value=""), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0):
                rc = resume(fake_root, "test-ws")
                self.assertEqual(rc, 0)

            self.assertIn("ensure_rootless_netns", events)
            self.assertIn("podman start proxy", events)
            self.assertLess(
                events.index("ensure_rootless_netns"),
                events.index("podman start proxy"),
            )

    def test_up_ensures_keyring_service_and_mounts_runtime_without_pass(self):
        from unittest import mock
        from cli.asb.lifecycle import _up
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        events: list[str] = []
        agent_args_captured = []

        def fake_run(*args, **kwargs):
            if len(args) >= 4 and args[0] == "run" and "--name" in args:
                idx = args.index("--name") + 1
                if args[idx] == "asb-test-ws-agent":
                    events.append("podman run agent")
                    agent_args_captured.extend(args)
                elif args[idx] == "asb-test-ws-proxy":
                    events.append("podman run proxy")
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            fake_layout = Layout(
                ws="test-ws",
                project="proj",
                mount=fake_mount,
                project_root=fake_mount / "proj",
                state=fake_state,
            )
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")

            fake_profile = Profile(
                services=[],
                host_ports=[],
                publish_ports=[],
                host_api="none",
                container_mode="standard",
                allow=[],
            )

            def fake_exists(kind: str, name: str) -> bool:
                if kind == "container" and name == "asb-test-ws-agent":
                    return False
                return True

            with mock.patch("cli.asb.lifecycle.podman.exists", side_effect=fake_exists), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service", side_effect=lambda: events.append("ensure_keyring_service")), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
                 mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl allow ..."), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="tool-vol"), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0), \
                 mock.patch("cli.asb.install.podman_restart"):
                rc = _up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            self.assertIn("ensure_keyring_service", events)
            self.assertIn("podman run agent", events)
            self.assertLess(
                events.index("ensure_keyring_service"),
                events.index("podman run agent"),
            )

            # Contract checks on agent args:
            self.assertIn("asb-keyring-runtime:/run/asb-keyring:ro,z", agent_args_captured)
            self.assertIn("asb-credentials:/run/asb-credentials:z", agent_args_captured)
            self.assertIn("type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000", agent_args_captured)
            self.assertFalse(any("asb-keyring-data" in str(arg) for arg in agent_args_captured))
            self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus", agent_args_captured)
            self.assertFalse(any("ASB_KEYRING_PASS" in str(arg) for arg in agent_args_captured))

    def test_resume_ensures_keyring_service_before_starting_containers(self):
        from unittest import mock
        from cli.asb.lifecycle import resume
        from cli.asb.workspace import Layout

        events: list[str] = []

        def fake_run(*args, **kwargs):
            if len(args) >= 2 and args[0] == "start":
                events.append(f"podman start {args[1]}")
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_origin = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_origin):
                d.mkdir(parents=True)
            fake_layout = Layout(
                ws="test-ws",
                project="proj",
                mount=fake_mount,
                project_root=fake_mount / "proj",
                state=fake_state,
            )
            fake_names = {
                "net": "asb-test-ws",
                "out": "asb-test-ws-out",
                "agent": "asb-test-ws-agent",
                "proxy": "asb-test-ws-proxy",
            }

            with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_names, tmp / "home", fake_origin)), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service", side_effect=lambda: events.append("ensure_keyring_service")), \
                 mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
                 mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.lifecycle.podman.out", return_value=""), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0):
                rc = resume(fake_root, "test-ws")
                self.assertEqual(rc, 0)

            self.assertIn("ensure_keyring_service", events)
            self.assertIn("podman start asb-test-ws-proxy", events)
            self.assertIn("podman start asb-test-ws-agent", events)
            self.assertLess(
                events.index("ensure_keyring_service"),
                events.index("podman start asb-test-ws-proxy"),
            )


class TestKeyringPreservation(unittest.TestCase):
    def test_down_preserves_keyring_container_and_volumes(self):
        from unittest import mock
        from cli.asb.lifecycle import down

        run_calls = []
        def fake_run(*args, **kwargs):
            run_calls.append(args)
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle.podman.out", return_value=""), \
             mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            down("demo")

        for call in run_calls:
            self.assertNotIn("asb-keyring", call)
            self.assertNotIn("asb-keyring-runtime", call)
            self.assertNotIn("asb-keyring-data", call)
            self.assertNotIn("asb-credentials", call)

    def test_suspend_preserves_keyring_container(self):
        from unittest import mock
        from cli.asb.lifecycle import suspend

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        stop_calls = []
        def fake_run(*args, **kwargs):
            if args and args[0] == "stop":
                stop_calls.append(args)
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle.podman.out", return_value=""), \
             mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("cli.asb.lifecycle.podman.running", return_value=True), \
             mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run):
            suspend("demo")

        for call in stop_calls:
            self.assertNotIn("asb-keyring", call)

    def test_purge_preserves_keyring_container_and_volumes(self):
        from unittest import mock
        from cli.asb.lifecycle import purge

        with mock.patch("cli.asb.lifecycle._origin_of", return_value=Path("/origin")), \
             mock.patch("cli.asb.lifecycle.layout_for"), \
             mock.patch("cli.asb.lifecycle.down") as mock_down, \
             mock.patch("cli.asb.lifecycle.remove_workspace"):
            purge("demo", confirmed=True)
            mock_down.assert_called_once_with("demo")


class TestStartForwarder(unittest.TestCase):
    def test_start_forwarder_no_ports_is_noop(self):
        from unittest import mock
        from cli.asb.lifecycle import start_forwarder
        from cli.asb.profile import Profile

        profile = Profile(host_ports=())
        with mock.patch("cli.asb.lifecycle.podman.run") as mock_run:
            start_forwarder("demo", profile)
            mock_run.assert_not_called()

    def test_start_forwarder_invokes_podman_with_sysctl_and_entrypoint(self):
        from unittest import mock
        from cli.asb.lifecycle import start_forwarder
        from cli.asb.profile import Profile

        profile = Profile(host_ports=(80, 5432))
        with mock.patch("cli.asb.lifecycle.podman.run") as mock_run:
            start_forwarder("demo", profile)
            mock_run.assert_called_once()
            args = mock_run.call_args[0]
            self.assertEqual(args[0], "run")
            self.assertIn("--sysctl", args)
            idx = args.index("--sysctl")
            self.assertEqual(args[idx + 1], "net.ipv4.ip_unprivileged_port_start=0")
            self.assertIn("--entrypoint", args)
            e_idx = args.index("--entrypoint")
            self.assertEqual(args[e_idx + 1], "/usr/local/bin/asb-forwarder")
            self.assertEqual(args[-2:], ("80", "5432"))

    def test_start_forwarder_invalid_ports_raise_value_error(self):
        from cli.asb.lifecycle import start_forwarder
        from cli.asb.profile import Profile

        for invalid_port in (0, 70000, -1, "80"):
            profile = Profile(host_ports=(invalid_port,))  # type: ignore
            with self.assertRaises(ValueError):
                start_forwarder("demo", profile)


if __name__ == "__main__":
    unittest.main()
