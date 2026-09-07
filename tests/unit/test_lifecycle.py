import os
import tempfile
import unittest
from pathlib import Path

from cli.asb.lifecycle import discover_mise_dirs
from cli.asb.readiness import ProbeResult

_HEALTHY_PROBE = ProbeResult("workspace", "healthy", "ok", 0, "")


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
                 mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
                 mock.patch("cli.asb.podman.out", return_value="127.0.0.1:2222"), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0), \
                 mock.patch("cli.asb.install.podman_restart") as mock_restart:
                rc = _up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            # S2: o ramo legacy (default) volta a chamar podman_restart();
            # so o ramo systemd fica isento (politica Podman `no` la).
            mock_restart.assert_called_once()

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
                 mock.patch("cli.asb.readiness.wait_until", return_value=_HEALTHY_PROBE), \
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
                 mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
                 mock.patch("cli.asb.podman.out", return_value="127.0.0.1:2222"), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0), \
                 mock.patch("cli.asb.install.podman_restart") as mock_restart:
                rc = _up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            mock_restart.assert_called_once()

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
                 mock.patch("cli.asb.readiness.wait_until", return_value=_HEALTHY_PROBE), \
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


class TestResumeReadinessGate(unittest.TestCase):
    """A#2: `resume` legacy publicava conexao sem verificar nada.

    O ramo legacy fazia `podman start ... check=False` num loop, engolia
    todo erro e caia direto no `emit`, retornando 0 sempre. O gate de
    prontidao vivia apenas dentro do ramo systemd. O ramo legacy e o
    caminho DEFAULT, em uso em producao.

    Regra da spec (T1): falha de infraestrutura impede emitir conexao —
    stdout vazio, retorno != 0, e NENHUM dado destruido.
    """

    @staticmethod
    def _fake_wait_until(probe, *, timeout, interval=1.0):
        """Executa o callback UMA vez: exercita o `check_ws` real sem
        gastar os 30s de retry do `wait_until` de producao."""
        return probe(min(5.0, timeout))

    def _run_legacy_resume(self, probes):
        from unittest import mock
        from cli.asb.lifecycle import resume
        from cli.asb.workspace import Layout
        import contextlib
        import io

        podman_calls: list[tuple] = []

        def fake_run(*args, **kwargs):
            podman_calls.append(args)
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_origin = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_origin):
                d.mkdir(parents=True)
            project_root = fake_mount / "proj"
            project_root.mkdir(parents=True)
            work = project_root / "trabalho-do-agente.txt"
            work.write_text("dados do workspace", encoding="utf-8")

            fake_layout = Layout(
                ws="test-ws", project="proj", mount=fake_mount,
                project_root=project_root, state=fake_state)
            fake_names = {
                "net": "asb-test-ws", "out": "asb-test-ws-out",
                "agent": "asb-test-ws-agent", "proxy": "asb-test-ws-proxy",
            }

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch("cli.asb.lifecycle._require_workspace",
                            return_value=(fake_names, tmp / "home", fake_origin)), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
                 mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.lifecycle.podman.out", return_value="127.0.0.1:2222"), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.readiness.probe_workspace", return_value=probes), \
                 mock.patch("cli.asb.readiness.wait_until",
                            side_effect=self._fake_wait_until):
                with contextlib.redirect_stdout(stdout), \
                     contextlib.redirect_stderr(stderr):
                    rc = resume(fake_root, "test-ws")

            # Capturado AINDA dentro do TemporaryDirectory: o worktree
            # sintetico desaparece com o tmpdir, nao com o `resume`.
            return (
                rc,
                stdout.getvalue(),
                stderr.getvalue(),
                (work.is_file(), work.read_text(encoding="utf-8") if work.is_file() else None),
                podman_calls,
            )

    def test_legacy_resume_with_broken_proxy_refuses_to_emit(self):
        from cli.asb.readiness import ProbeResult

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "failed", "connect_failed", 2,
                        "verifique conectividade do destino ou uplink"),
            ProbeResult("ssh", "healthy", "ok", 3, ""),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, podman_calls = self._run_legacy_resume(probes)

        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("proxy", err)
        self.assertIn("connect_failed", err)
        # Nenhum dado destruido: o worktree segue intacto e nenhuma remocao
        # foi disparada contra containers, volumes ou redes.
        self.assertEqual(work, (True, "dados do workspace"))
        self.assertEqual([c for c in podman_calls if "rm" in c], [])

    def test_legacy_resume_with_broken_ssh_refuses_to_emit(self):
        from cli.asb.readiness import ProbeResult

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "healthy", "ok", 2, ""),
            ProbeResult("ssh", "failed", "connection_refused", 3,
                        "conexao recusada: verifique se sshd esta ativo"),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, _ = self._run_legacy_resume(probes)

        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("connection_refused", err)
        self.assertEqual(work, (True, "dados do workspace"))

    def test_legacy_resume_emits_only_when_every_probe_is_healthy(self):
        from cli.asb.readiness import ProbeResult
        import json as _json

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "healthy", "ok", 2, ""),
            ProbeResult("ssh", "healthy", "ok", 3, ""),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, _ = self._run_legacy_resume(probes)

        self.assertEqual(rc, 0)
        payload = _json.loads(out)
        self.assertEqual(payload["workspace"], "test-ws")
        self.assertEqual(payload["port"], 2222)
        self.assertEqual(work, (True, "dados do workspace"))


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


class TestTransactionalRollback(unittest.TestCase):
    def test_up_existing_workspace_failure_does_not_sweep(self):
        from unittest import mock
        from cli.asb import lifecycle

        root = Path("/fake/root")
        repo = Path("/fake/repo")
        with mock.patch("cli.asb.lifecycle.prepare_workspace"), \
             mock.patch("cli.asb.lifecycle.supervisor.start_workspace", side_effect=RuntimeError("proxy")), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as sweep:
            with self.assertRaises(RuntimeError):
                lifecycle.up(root, "test-existing", repo, runtime="systemd")
            sweep.assert_not_called()

    def test_up_on_already_existing_container_does_not_sweep(self):
        from unittest import mock
        from cli.asb import lifecycle

        root = Path("/fake/root")
        repo = Path("/fake/repo")
        with mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "container" and name == "asb-existing-agent"), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as sweep, \
             mock.patch("cli.asb.lifecycle.prepare_workspace") as prep:
            with self.assertRaises(lifecycle.podman.PodmanError):
                lifecycle.up(root, "existing", repo)
            sweep.assert_not_called()
            prep.assert_not_called()

    def test_up_rollback_by_id_in_new_workspace_cleans_only_tracked_ids(self):
        from unittest import mock
        from cli.asb import lifecycle

        root = Path("/fake/root")
        repo = Path("/fake/repo")
        rm_calls = []

        def fake_run(*args, **kwargs):
            if args and args[0] == "rm":
                rm_calls.append(args)
            return mock.MagicMock(returncode=0)

        def fake_prepare(r, ws, rp, runtime="legacy", tx=None):
            if tx is not None:
                tx.record_container("cid-proxy-new-123")
                tx.record_network(f"asb-{ws}-net")
            raise RuntimeError("simulated failure after partial creation")

        with mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.podman.run", side_effect=fake_run), \
             mock.patch("cli.asb.lifecycle.prepare_workspace", side_effect=fake_prepare), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as sweep:
            with self.assertRaises(RuntimeError):
                lifecycle.up(root, "new-ws", repo)

            sweep.assert_not_called()
            # Only the recorded container ID should be removed
            removed_ids = [c[2] for c in rm_calls if len(c) >= 3 and c[0] == "rm" and c[1] == "-f"]
            self.assertEqual(removed_ids, ["cid-proxy-new-123"])

    def test_up_runtime_systemd_creates_containers_with_restart_no(self):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        run_args_list = []
        def fake_run(*args, **kwargs):
            run_args_list.append(list(args))
            return mock.MagicMock(returncode=0, stdout="cid-12345")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])

            healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")

            from contextlib import ExitStack
            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.podman.ensure_rootless_netns"))
                stack.enter_context(mock.patch("cli.asb.podman.run", side_effect=fake_run))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="cid-12345"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.lifecycle.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"))
                mock_install = stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                mock_start = stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", return_value=healthy_probe))
                stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.emit", return_value=0))
                mock_restart = stack.enter_context(mock.patch("cli.asb.install.podman_restart"))

                rc = lifecycle.up(fake_root, "demo", fake_repo, runtime="systemd")
                self.assertEqual(rc, 0)
                mock_install.assert_called_once()
                mock_start.assert_called_once_with("demo", enable=True)
                # S2: politica Podman `no` e systemd controla a partida —
                # o ramo systemd NUNCA chama podman_restart().
                mock_restart.assert_not_called()

                # Check restart policy in container creation calls
                for call_args in run_args_list:
                    if call_args and call_args[0] == "create":
                        self.assertIn("--restart", call_args)
                        idx = call_args.index("--restart")
                        self.assertEqual(call_args[idx + 1], "no")

                # Check runtime.json content
                manifest_file = fake_state / "runtime.json"
                self.assertTrue(manifest_file.is_file())
                import json
                manifest = json.loads(manifest_file.read_text())
                self.assertEqual(manifest.get("runtime_type"), "systemd")

    def test_up_proxy_readiness_failure_before_mise_install(self):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])
            fake_key = tmp / "key"
            fake_key.write_text("k")
            (tmp / "key.pub").write_text("k.pub")

            failed_proxy = mock.MagicMock(state="failed", code="connect_denied", remediation="fix allowlist")

            with mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"), \
                 mock.patch("cli.asb.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.podman.run"), \
                 mock.patch("cli.asb.podman.out", return_value="cid-1"), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl x"), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"), \
                 mock.patch("cli.asb.readiness.wait_until", return_value=failed_proxy), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs") as mock_mise, \
                 mock.patch("cli.asb.install.podman_restart"):
                with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                    lifecycle.up(tmp, "demo", tmp / "origin")
                self.assertIn("proxy nao esta pronto", str(ctx.exception))
                mock_mise.assert_not_called()

    def test_up_ssh_readiness_failure_propagates_and_does_not_emit(self):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])
            fake_key = tmp / "key"
            fake_key.write_text("k")
            (tmp / "key.pub").write_text("k.pub")

            healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")
            failed_ssh = mock.MagicMock(state="failed", code="key_refused", remediation="fix ssh key")

            def fake_wait(probe_fn, timeout=30.0, **kwargs):
                if not hasattr(fake_wait, "calls"):
                    fake_wait.calls = 0
                fake_wait.calls += 1
                if fake_wait.calls == 1:
                    return healthy_probe
                return failed_ssh

            with mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"), \
                 mock.patch("cli.asb.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.podman.run"), \
                 mock.patch("cli.asb.podman.out", side_effect=["cid-proxy", "cid-agent", "127.0.0.1:2222"]), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl x"), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"), \
                 mock.patch("cli.asb.readiness.wait_until", side_effect=fake_wait), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]), \
                 mock.patch("cli.asb.lifecycle.emit") as mock_emit, \
                 mock.patch("cli.asb.install.podman_restart"):
                with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                    lifecycle.up(tmp, "demo", tmp / "origin")
                self.assertIn("SSH nao esta pronto", str(ctx.exception))
                mock_emit.assert_not_called()

    def test_up_with_host_ports_writes_forwarder_manifest_entry(self):
        """C1 regression: `manifest_containers["forwarder"]` referenciava
        `fwd_name`, uma variavel nunca atribuida em `prepare_workspace`.
        Qualquer profile com `host_ports` nao vazio levantava `NameError`
        dentro do bloco `try` de `up`, disparando um rollback espurio. Todo
        teste anterior usava `Profile(host_ports=[])`, e `TestStartForwarder`
        exercitava `start_forwarder` isolado — nenhum atravessava
        `prepare_workspace` de ponta a ponta com portas configuradas."""
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
            fake_profile = Profile(services=[], host_ports=[8080], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])

            healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")

            with mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"), \
                 mock.patch("cli.asb.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.podman.run", return_value=mock.MagicMock(returncode=0)), \
                 mock.patch("cli.asb.podman.out", return_value="cid-fwd-1"), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl x"), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]), \
                 mock.patch("cli.asb.readiness.wait_until", return_value=healthy_probe), \
                 mock.patch("cli.asb.lifecycle.emit", return_value=0), \
                 mock.patch("cli.asb.install.podman_restart"):
                rc = lifecycle.up(fake_root, "demo", fake_repo, runtime="legacy")
                self.assertEqual(rc, 0)

            manifest_file = fake_state / "runtime.json"
            self.assertTrue(manifest_file.is_file())
            import json
            manifest = json.loads(manifest_file.read_text())
            self.assertIn("forwarder", manifest["containers"])
            self.assertEqual(manifest["containers"]["forwarder"]["name"], "asb-demo-fwd")
            self.assertEqual(manifest["containers"]["forwarder"]["unit"], "asb-demo-fwd.service")

    def test_up_resolves_ssh_port_once_and_reuses_it_in_emit(self):
        """I4: `up` resolvia a porta SSH duas vezes (uma para o gate de
        prontidao, outra dentro de `emit`) com dois `podman port` redundantes.
        Agora `emit` aceita a porta ja resolvida."""
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            fake_layout = Layout(ws="test-ws", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")

            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])

            port_calls = []

            def fake_out(*args, **kwargs):
                if len(args) >= 1 and args[0] == "port":
                    port_calls.append(args)
                return "0.0.0.0:2222"

            def fake_exists(kind, name):
                if kind == "container" and name == "asb-test-ws-agent":
                    return False
                return True

            emitted = {}

            def fake_emit(ws, layout, port=None):
                emitted["port"] = port
                return 0

            with mock.patch("cli.asb.lifecycle.podman.exists", side_effect=fake_exists), \
                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="run-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="cred-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="tool-vol"), \
                 mock.patch("cli.asb.lifecycle.podman.run"), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl allow ..."), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]), \
                 mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
                 mock.patch("cli.asb.podman.out", side_effect=fake_out), \
                 mock.patch("cli.asb.lifecycle.emit", side_effect=fake_emit), \
                 mock.patch("cli.asb.install.podman_restart"):
                rc = lifecycle.up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            self.assertEqual(len(port_calls), 1)
            self.assertEqual(emitted["port"], "2222")

    def test_up_rollback_removes_real_units_and_logs_removal_failure(self):
        """I5: `WorkspaceTransaction.rollback` engolia qualquer excecao ao
        remover unidades systemd (`except Exception: pass`), e nenhum teste
        alcancava esse caminho com `created_units` de fato preenchido: os
        testes existentes mockavam `prepare_workspace` inteiro ou faziam
        `install_workspace` retornar `[]`. Aqui `install_workspace` roda de
        verdade (grava unidades reais em disco) e uma falha de prontidao
        posterior aciona o rollback; a falha de remocao deve ser logada em
        stderr, e a excecao original de `up` (nao a do rollback) deve
        prevalecer."""
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            fake_home = tmp / "home"
            for d in (fake_root, fake_state, fake_mount, fake_repo, fake_home):
                d.mkdir(parents=True)
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])

            failed_proxy = mock.MagicMock(state="failed", code="connect_denied", remediation="fix allowlist")

            with mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"), \
                 mock.patch("cli.asb.podman.ensure_rootless_netns"), \
                 mock.patch("cli.asb.podman.run", return_value=mock.MagicMock(returncode=0)), \
                 mock.patch("cli.asb.podman.out", return_value="cid-xyz"), \
                 mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile), \
                 mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("cli.asb.lifecycle.prepare_clone"), \
                 mock.patch("cli.asb.lifecycle.render", return_value="acl x"), \
                 mock.patch("cli.asb.lifecycle.build_staging", return_value=0), \
                 mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
                 mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"), \
                 mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"), \
                 mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"), \
                 mock.patch.object(Path, "home", return_value=fake_home), \
                 mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)), \
                 mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units",
                             side_effect=RuntimeError("systemctl indisponivel")) as mock_remove, \
                 mock.patch("cli.asb.readiness.wait_until", return_value=failed_proxy):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                        lifecycle.up(fake_root, "demo", fake_repo, runtime="systemd")
                self.assertIn("proxy nao esta pronto", str(ctx.exception))

            mock_remove.assert_called_once_with("demo")
            self.assertIn("systemctl indisponivel", stderr.getvalue())

            # install_workspace escreveu unidades REAIS em disco (nao []
            # mockado) antes da falha posterior — e essas sao as unidades
            # que tx.created_units rastreou para o rollback acima.
            unit_file = fake_home / ".config" / "systemd" / "user" / "asb-demo.target"
            self.assertTrue(unit_file.is_file())


class TestRuntimeOf(unittest.TestCase):
    """I3: `_runtime_of` deve distinguir manifesto AUSENTE (legacy, ok) de
    manifesto PRESENTE porem corrompido/ilegivel (erro real)."""

    def test_missing_manifest_returns_legacy(self):
        from cli.asb import lifecycle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(lifecycle._runtime_of("no-such-ws", home), "legacy")

    def test_valid_manifest_returns_declared_runtime(self):
        from cli.asb import lifecycle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / ".local" / "state" / "agent-sandbox" / "ws"
            state.mkdir(parents=True)
            (state / "runtime.json").write_text(
                '{"schemaVersion": 1, "workspace": "ws", "runtime_type": "systemd"}')
            self.assertEqual(lifecycle._runtime_of("ws", home), "systemd")

    def test_corrupted_manifest_raises_instead_of_silently_defaulting_legacy(self):
        """Um manifesto ilegivel NAO pode virar 'legacy' em silencio: isso
        faria `resume` pular enable/reset-failed/start do target e a sonda
        de prontidao, subindo containers --restart=no sem supervisao
        enquanto informa sucesso ao operador."""
        from cli.asb import lifecycle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / ".local" / "state" / "agent-sandbox" / "ws"
            state.mkdir(parents=True)
            (state / "runtime.json").write_text("{ nao-e-json valido ]")
            with self.assertRaises(lifecycle.podman.PodmanError):
                lifecycle._runtime_of("ws", home)

    def test_manifest_not_a_json_object_raises(self):
        from cli.asb import lifecycle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / ".local" / "state" / "agent-sandbox" / "ws"
            state.mkdir(parents=True)
            (state / "runtime.json").write_text("[1, 2, 3]")
            with self.assertRaises(lifecycle.podman.PodmanError):
                lifecycle._runtime_of("ws", home)


class TestManagedLifecycleCommands(unittest.TestCase):
    def test_suspend_managed_disables_and_stops_target_and_verifies_stopped(self):
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        systemctl_calls = []

        def fake_subprocess_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "systemctl":
                systemctl_calls.append(cmd)
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="systemd"), \
             mock.patch("subprocess.run", side_effect=fake_subprocess_run), \
             mock.patch("cli.asb.podman.out", return_value="asb-demo-agent\nasb-demo-proxy"), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", return_value=False):
            rc = lifecycle.suspend("demo")
            self.assertEqual(rc, 0)
            self.assertTrue(any("disable" in c and "asb-demo.target" in c for c in systemctl_calls))
            self.assertTrue(any("stop" in c and "asb-demo.target" in c for c in systemctl_calls))

    def test_suspend_legacy_stops_containers_directly(self):
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        stop_calls = []
        stopped = set()

        def fake_podman_run(*args, **kwargs):
            if args and args[0] == "stop":
                stop_calls.append(args)
                stopped.add(args[-1])
            return mock.MagicMock(returncode=0)

        def fake_running(name):
            # Simula o container efetivamente parando apos o `podman stop`.
            return name not in stopped

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="legacy"), \
             mock.patch("subprocess.run") as mock_subproc, \
             mock.patch("cli.asb.podman.out", return_value="asb-demo-agent\nasb-demo-proxy"), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", side_effect=fake_running), \
             mock.patch("cli.asb.podman.run", side_effect=fake_podman_run):
            rc = lifecycle.suspend("demo")
            self.assertEqual(rc, 0)
            mock_subproc.assert_not_called()
            self.assertEqual(len(stop_calls), 2)

    def test_suspend_fails_when_container_refuses_to_stop(self):
        """S1: suspend deve verificar que os containers pararam de fato, e
        retornar codigo != 0 (nunca 0 incondicional) quando algum permanece
        em execucao apos o stop."""
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="legacy"), \
             mock.patch("subprocess.run"), \
             mock.patch("cli.asb.podman.out", return_value="asb-demo-agent\nasb-demo-proxy"), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", return_value=True), \
             mock.patch("cli.asb.podman.run", return_value=mock.MagicMock(returncode=0)):
            import io
            import contextlib
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.suspend("demo")
            self.assertNotEqual(rc, 0)
            self.assertIn("asb-demo-agent", stderr.getvalue())

    def test_resume_managed_enables_resets_starts_and_checks_probes(self):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.workspace import Layout

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        systemctl_calls = []

        def fake_subprocess_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "systemctl":
                systemctl_calls.append(cmd)
            return mock.MagicMock(returncode=0)

        fake_layout = Layout(ws="demo", project="proj", mount=Path("/tmp/mount"),
                             project_root=Path("/tmp/mount/proj"), state=Path("/tmp/state"))
        healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="systemd"), \
             mock.patch("cli.asb.podman.ensure_rootless_netns"), \
             mock.patch("cli.asb.lifecycle.ensure_keyring_service"), \
             mock.patch("subprocess.run", side_effect=fake_subprocess_run), \
             mock.patch("cli.asb.lifecycle.supervisor.start_workspace") as mock_start, \
             mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout), \
             mock.patch("cli.asb.readiness.wait_until", return_value=healthy_probe), \
             mock.patch("cli.asb.lifecycle.emit", return_value=0) as mock_emit:
            rc = lifecycle.resume(Path("/fake/root"), "demo")
            self.assertEqual(rc, 0)
            self.assertTrue(any("enable" in c and "asb-demo.target" in c for c in systemctl_calls))
            self.assertTrue(any("reset-failed" in c for c in systemctl_calls))
            mock_start.assert_called_once_with("demo")
            mock_emit.assert_called_once()

    def test_down_managed_removes_units_before_cleaning_containers(self):
        from unittest import mock
        from cli.asb import lifecycle

        events = []

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units", side_effect=lambda ws, **kw: events.append("remove_units")) as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers", side_effect=lambda ws: events.append("sweep_containers")), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="systemd"), \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            rc = lifecycle.down("demo")
            self.assertEqual(rc, 0)
            mock_remove.assert_called_once()
            self.assertEqual(mock_remove.call_args[0][0], "demo")
            self.assertEqual(events, ["remove_units", "sweep_containers"])

    def test_down_legacy_does_not_call_remove_workspace_units(self):
        """I2: `down` de workspace legacy nao pode chamar remove_workspace_units.

        `remove_workspace_units` termina em `daemon-reload` com check=True,
        que levanta num host sem sessao systemd de usuario. Um workspace
        criado sem --runtime systemd nunca instalou unidade alguma.
        """
        from unittest import mock
        from cli.asb import lifecycle

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units") as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers"), \
             mock.patch("cli.asb.lifecycle._runtime_of", return_value="legacy"), \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            rc = lifecycle.down("demo")
            self.assertEqual(rc, 0)
            mock_remove.assert_not_called()

    def test_down_with_corrupted_manifest_still_cleans_up_best_effort(self):
        """`down` e a saida de emergencia de um workspace quebrado: um
        runtime.json corrompido (agora um erro real gracas a I3) NUNCA pode
        abortar a limpeza dos containers e redes locais. Diferente de
        `resume`/`suspend`, que reportam saude e por isso devem propagar o
        erro de `_runtime_of`, `down` segue com limpeza local best-effort e
        apenas avisa em stderr."""
        from unittest import mock
        from cli.asb import lifecycle
        import io
        import contextlib

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units") as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers") as mock_sweep, \
             mock.patch("cli.asb.lifecycle._runtime_of",
                        side_effect=lifecycle.podman.PodmanError("manifesto de runtime corrompido")), \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.down("demo")
            self.assertEqual(rc, 0)
            mock_remove.assert_not_called()
            mock_sweep.assert_called_once_with("demo")
            self.assertIn("manifesto de runtime corrompido", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

