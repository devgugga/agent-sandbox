import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import os
import tempfile
import unittest
from pathlib import Path

from cli.asb.lifecycle import discover_mise_dirs
from cli.asb.readiness import ProbeResult
from cli.asb.runtime.storage import RuntimeStorage

_HEALTHY_PROBE = ProbeResult("workspace", "healthy", "ok", 0, "")


def _fake_storage(*, credentials="asb-credentials", credential_mounts=(),
                  session="asb-test-ws-session", toolcache="t-vol"):
    """`RuntimeStorage` REAL, com so os quatro pontos que tocariam disco ou
    Podman trocados por valores fixos. Mesmo padrao que estes testes de `up`
    usavam antes da Tarefa 3 (mockar `ensure_credentials_volume`,
    `credential_mount_args`, `ensure_session_volume` e
    `ensure_toolcache_volume` soltos em `cli.asb.lifecycle`), so que agora o
    alvo do patch e a CLASSE `RuntimeStorage`. `session_mounts` fica REAL de
    proposito: nenhum destes testes jamais mockou `session_mount_args`, e o
    `home` real (nao mockado) sempre entrou no calculo dela."""
    from unittest import mock

    storage = RuntimeStorage(Path(os.path.expanduser("~")))
    storage.ensure_credentials = mock.Mock(return_value=credentials)
    storage.credential_mounts = mock.Mock(return_value=list(credential_mounts))
    storage.ensure_sessions = mock.Mock(return_value=session)
    storage.ensure_toolcache = mock.Mock(return_value=toolcache)
    return storage


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


class TestEmitDelegatesSerializationWithoutChangingTheContract(unittest.TestCase):
    """Tarefa 3: `emit()` passou a delegar a serializacao a `ConnectionInfo`,
    mas a linha que o recipe do Orca consome tem de continuar byte-a-byte a
    mesma: as MESMAS quatro chaves, na MESMA ordem, com `port` como int, e
    nenhum outro stdout no caminho."""

    def test_emit_prints_the_exact_json_contract_and_nothing_else(self):
        import contextlib
        import getpass
        import io
        from cli.asb.lifecycle import emit
        from cli.asb.workspace import Layout

        fake_layout = Layout(ws="test-ws", project="proj",
                             mount=Path("/tmp/fake-mount"),
                             project_root=Path("/sandbox/repo"),
                             state=Path("/tmp/fake-state"))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = emit("test-ws", fake_layout, port="2222")

        self.assertEqual(rc, 0)
        self.assertEqual(
            stdout.getvalue(),
            '{"workspace": "test-ws", "port": 2222, "user": "'
            f'{getpass.getuser()}", "project_root": "/sandbox/repo"}}\n')

    def test_emit_never_makes_a_second_podman_port_call_when_port_is_supplied(self):
        import contextlib
        import io
        from unittest import mock
        from cli.asb.lifecycle import emit
        from cli.asb.workspace import Layout

        fake_layout = Layout(ws="test-ws", project="proj",
                             mount=Path("/tmp/fake-mount"),
                             project_root=Path("/sandbox/repo"),
                             state=Path("/tmp/fake-state"))
        with mock.patch("cli.asb.lifecycle.podman.out") as mock_out:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = emit("test-ws", fake_layout, port="2222")
        self.assertEqual(rc, 0)
        mock_out.assert_not_called()


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
                 mock.patch("cli.asb.podman.run") as mock_podman_run, \
                 mock.patch("cli.asb.lifecycle.subprocess.run") as mock_run:
                rc = reload_allowlist(fake_root, "test-ws")
                self.assertEqual(rc, 0)
                # O proxy e supervisionado pelo systemd: `podman restart` mata o
                # `start --attach` da unidade, e o ExecStopPost derruba o
                # container recem-reiniciado. O reinicio passa pela unidade, e
                # so se ela ja estava no ar (workspace suspenso segue suspenso).
                mock_run.assert_called_once_with(
                    ["systemctl", "--user", "try-restart", "asb-test-ws-proxy.service"],
                    check=True)
                mock_podman_run.assert_not_called()
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
                 mock.patch("cli.asb.lifecycle.subprocess.run"):
                reload_allowlist(base, "ws")

            mock_load.assert_called_once_with(origin)


class TestLifecycleOrdering(unittest.TestCase):


    def test_up_ensures_keyring_service_before_creating_the_agent_and_mounts_runtime_without_pass(self):
        from unittest import mock
        from cli.asb.lifecycle import _up
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        events: list[str] = []
        agent_args_captured = []

        def fake_run(*args, **kwargs):
            if len(args) >= 4 and args[0] == "create" and "--name" in args:
                idx = args.index("--name") + 1
                if args[idx] == "asb-test-ws-agent":
                    events.append("podman create agent")
                    agent_args_captured.extend(args)
                elif args[idx] == "asb-test-ws-proxy":
                    events.append("podman create proxy")
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_root = tmp / "repo-root"
            fake_state = tmp / "state"
            fake_mount = tmp / "mount"
            fake_repo = tmp / "origin"
            for d in (fake_root, fake_state, fake_mount, fake_repo):
                d.mkdir(parents=True)
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)
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

            from contextlib import ExitStack
            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.lifecycle.podman.exists", side_effect=fake_exists))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service", side_effect=lambda *a, **k: events.append("ensure_keyring_service")))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(toolcache="tool-vol")))
                stack.enter_context(mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_run))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl allow ..."))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="127.0.0.1:2222"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.emit", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))
                rc = _up(fake_root, "test-ws", fake_repo)
                self.assertEqual(rc, 0)

            self.assertIn("ensure_keyring_service", events)
            self.assertIn("podman create agent", events)
            self.assertLess(
                events.index("ensure_keyring_service"),
                events.index("podman create agent"),
            )

            # Contract checks on agent args:
            self.assertIn("asb-keyring-runtime:/run/asb-keyring:ro,z", agent_args_captured)
            self.assertIn("asb-credentials:/run/asb-credentials:z", agent_args_captured)
            self.assertIn("type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000", agent_args_captured)
            self.assertFalse(any("asb-keyring-data" in str(arg) for arg in agent_args_captured))
            self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus", agent_args_captured)
            self.assertFalse(any("ASB_KEYRING_PASS" in str(arg) for arg in agent_args_captured))



class TestResumeReadinessGate(unittest.TestCase):
    """A#2: `resume` so publica conexao depois do gate de prontidao; falha de infraestrutura nao destroi dados."""

    @staticmethod
    def _fake_wait_until(probe, *, timeout, interval=1.0):
        """Executa o callback UMA vez: exercita o `check_ws` real sem
        gastar os 30s de retry do `wait_until` de producao."""
        return probe(min(5.0, timeout))

    def _run_resume(self, probes):
        from unittest import mock
        from cli.asb.lifecycle import resume
        from cli.asb.readiness import ProbeResult
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
                 mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=tmp / "runtime"), \
                 mock.patch("cli.asb.lifecycle.supervisor.start_workspace"), \
                 mock.patch("cli.asb.lifecycle.subprocess.run", return_value=mock.MagicMock(returncode=0)), \
                 mock.patch("cli.asb.readiness.probe_host", return_value=ProbeResult("host", "healthy", "ok", 0, "")), \
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

    def test_resume_with_broken_proxy_refuses_to_emit(self):
        from cli.asb.readiness import ProbeResult

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "failed", "connect_failed", 2,
                        "verifique conectividade do destino ou uplink"),
            ProbeResult("ssh", "healthy", "ok", 3, ""),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, podman_calls = self._run_resume(probes)

        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("proxy", err)
        self.assertIn("connect_failed", err)
        # Nenhum dado destruido: o worktree segue intacto e nenhuma remocao
        # foi disparada contra containers, volumes ou redes.
        self.assertEqual(work, (True, "dados do workspace"))
        self.assertEqual([c for c in podman_calls if "rm" in c], [])

    def test_resume_with_broken_ssh_refuses_to_emit(self):
        from cli.asb.readiness import ProbeResult

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "healthy", "ok", 2, ""),
            ProbeResult("ssh", "failed", "connection_refused", 3,
                        "conexao recusada: verifique se sshd esta ativo"),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, _ = self._run_resume(probes)

        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("connection_refused", err)
        self.assertEqual(work, (True, "dados do workspace"))

    def test_resume_emits_only_when_every_probe_is_healthy(self):
        from cli.asb.readiness import ProbeResult
        import json as _json

        probes = [
            ProbeResult("host", "healthy", "ok", 1, ""),
            ProbeResult("proxy", "healthy", "ok", 2, ""),
            ProbeResult("ssh", "healthy", "ok", 3, ""),
            ProbeResult("keyring", "healthy", "ok", 4, ""),
        ]
        rc, out, err, work, _ = self._run_resume(probes)

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
        from cli.asb import lifecycle
        from cli.asb.lifecycle import purge

        with mock.patch("cli.asb.lifecycle._origin_of", return_value=Path("/origin")), \
             mock.patch("cli.asb.lifecycle.layout_for"), \
             mock.patch("cli.asb.lifecycle.down") as mock_down, \
             mock.patch("cli.asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("cli.asb.lifecycle.podman.run") as mock_run, \
             mock.patch("cli.asb.lifecycle.remove_workspace"):
            purge("demo", confirmed=True)
            mock_down.assert_called_once_with("demo")

        # O purge remove o volume de SESSAO deste workspace — e so ele. O
        # volume de credenciais e o keyring sao compartilhados: nenhum purge
        # pode encostar neles.
        removed = [" ".join(str(a) for a in call.args)
                   for call in mock_run.call_args_list]
        # `down` passou a preservar o volume de containers aninhados, entao
        # e o `purge` que o remove — junto com o de sessao, nunca os
        # compartilhados.
        self.assertEqual(removed, ["volume rm -f asb-demo-session",
                                   "volume rm -f asb-demo-containers"])
        joined = " ".join(removed)
        for shared in ("asb-credentials", lifecycle.KEYRING_CONTAINER,
                       lifecycle.KEYRING_DATA_VOLUME,
                       lifecycle.KEYRING_RUNTIME_VOLUME):
            self.assertNotIn(str(shared), joined)


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
            self.assertEqual(args[0], "create")
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


class TestSingleRuntimeUp(unittest.TestCase):
    """Emenda A: `up` tem runtime unico, remove o drop-in, verifica o host e nunca roda `unshare`."""

    def _run_up(self, *, host_state: str = "healthy", dropin_removed: bool = False,
                host_ports: list | None = None, ports_state: str = "healthy"):
        import json
        from contextlib import ExitStack
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.readiness import ProbeResult
        from cli.asb.workspace import Layout

        events: list[str] = []
        podman_calls: list[list[str]] = []

        def fake_run(*args, **kwargs):
            podman_calls.append(list(args))
            if args and args[0] in ("create", "network"):
                events.append(f"podman {args[0]}")
            return mock.MagicMock(returncode=0, stdout="cid-12345")

        def fake_probe_host(**kwargs):
            events.append("host-probe")
            code = "ok" if host_state == "healthy" else "timeout"
            return ProbeResult("host", host_state, code, 0, "")

        def fake_remove_dropin(*args, **kwargs):
            events.append("remove-dropin")
            return dropin_removed

        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)
        fake_root, fake_state, fake_mount, fake_repo = (
            tmp / name for name in ("root", "state", "mount", "origin"))
        for d in (fake_root, fake_state, fake_mount, fake_repo):
            d.mkdir(parents=True)
        runtime_dir = tmp / "runtime" / "rev1"
        runtime_dir.mkdir(parents=True)
        fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                             project_root=fake_mount / "proj", state=fake_state)
        fake_key = tmp / "key"
        fake_key.write_text("dummy")
        (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
        fake_profile = Profile(services=[], host_ports=list(host_ports or []),
                               publish_ports=[],
                               host_api="none", container_mode="standard", allow=[])
        healthy = ProbeResult("probe", "healthy", "ok", 0, "")

        error = None
        rc = None
        with ExitStack() as stack:
            stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
            stack.enter_context(mock.patch("cli.asb.podman.run", side_effect=fake_run))
            stack.enter_context(mock.patch("cli.asb.podman.out", return_value="127.0.0.1:2222"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
            stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
            stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
            stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
            stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
            stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
            stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
            stack.enter_context(mock.patch(
                "cli.asb.runtime.workspace.RuntimeStorage",
                return_value=_fake_storage(credentials="c-vol", session="asb-demo-session")))
            stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
            mock_emit = stack.enter_context(mock.patch("cli.asb.lifecycle.emit", return_value=0))
            stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", side_effect=fake_remove_dropin))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_host", side_effect=fake_probe_host))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_proxy", return_value=healthy))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_ssh", return_value=healthy))
            stack.enter_context(mock.patch(
                "cli.asb.readiness.probe_host_ports",
                return_value=ProbeResult("host_ports", ports_state,
                                         "ok" if ports_state == "healthy" else "no_listener",
                                         0, "" if ports_state == "healthy" else "sem listener: 5432")))
            stack.enter_context(mock.patch(
                "cli.asb.readiness.wait_until",
                side_effect=lambda probe, *, timeout, interval=1.0: probe(1.0)))
            mock_install = stack.enter_context(mock.patch(
                "cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
            mock_start = stack.enter_context(mock.patch(
                "cli.asb.lifecycle.supervisor.start_workspace",
                side_effect=lambda ws, **kw: events.append("start-target")))
            try:
                rc = lifecycle.up(fake_root, "demo", fake_repo)
            except lifecycle.podman.PodmanError as exc:
                error = exc

        manifest_file = fake_state / "runtime.json"
        manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else None
        self.last_emit = mock_emit
        return rc, error, events, podman_calls, mock_install, mock_start, manifest

    def test_up_creates_stopped_containers_without_restart_policy_and_starts_the_target(self):
        rc, error, _, podman_calls, mock_install, mock_start, manifest = self._run_up()
        self.assertIsNone(error)
        self.assertEqual(rc, 0)
        self.assertNotIn("run", {call[0] for call in podman_calls if call})
        creates = [call for call in podman_calls if call and call[0] == "create"]
        self.assertTrue(creates)
        for call in creates:
            self.assertEqual(call[call.index("--restart") + 1], "no")
            self.assertNotIn("-d", call)
        mock_install.assert_called_once()
        mock_start.assert_called_once_with("demo", enable=True)
        self.assertEqual(manifest["runtime_type"], "systemd")
        self.assertEqual(manifest["runtime_backend"], "systemd")
        self.assertEqual(manifest["revision"], "rev1")

    def test_up_removes_the_project_dropin_and_checks_the_host_before_creating_resources(self):
        _, error, events, _, _, _, _ = self._run_up()
        self.assertIsNone(error)
        self.assertEqual(events[:2], ["remove-dropin", "host-probe"])
        first_resource = next(i for i, e in enumerate(events) if e.startswith("podman "))
        self.assertLess(events.index("host-probe"), first_resource)
        self.assertLess(first_resource, events.index("start-target"))

    def test_up_notifies_stderr_when_legacy_dropin_is_removed(self):
        import contextlib
        import io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            _, error, _, _, _, _, _ = self._run_up(dropin_removed=True)
        self.assertIsNone(error)
        self.assertIn("drop-in legado do podman-restart removido", stderr.getvalue())


    def test_up_without_network_fails_before_creating_any_resource(self):
        rc, error, _, podman_calls, mock_install, mock_start, manifest = self._run_up(
            host_state="unreachable")
        self.assertIsNone(rc)
        self.assertIsNotNone(error)
        self.assertIn("sem conectividade real", str(error))
        self.assertEqual(
            [c for c in podman_calls if c and c[0] in ("create", "network", "build")], [])
        mock_install.assert_not_called()
        mock_start.assert_not_called()
        self.assertIsNone(manifest)

    def test_up_refuses_to_emit_when_a_declared_host_port_has_no_listener(self):
        """`host_ports` e pos-condicao prometida ao projeto: sem sonda, o `up`
        imprimia a conexao com o servico declarado simplesmente ausente."""
        import contextlib
        import io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc, error, _, _, _, _, _ = self._run_up(host_ports=[5432],
                                                    ports_state="failed")
        self.assertIsNone(error)
        self.assertEqual(rc, 1)
        self.last_emit.assert_not_called()
        self.assertIn("5432", stderr.getvalue())

    def test_up_emits_when_every_declared_host_port_answers(self):
        rc, error, _, _, _, _, _ = self._run_up(host_ports=[5432])
        self.assertIsNone(error)
        self.assertEqual(rc, 0)
        self.last_emit.assert_called_once()

    def test_up_never_initializes_the_rootless_namespace(self):
        _, error, _, podman_calls, _, _, _ = self._run_up()
        self.assertIsNone(error)
        self.assertEqual([c for c in podman_calls if c and c[0] == "unshare"], [])


class TestSingleRuntimeResume(unittest.TestCase):
    """Emenda A: `resume` verifica o host, garante o keyring, sobe o target e nunca roda `unshare`."""

    def _run_resume(self, *, host_state: str = "healthy", manifest_content: str | None = None):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.podman import PodmanError
        from cli.asb.readiness import ProbeResult
        from cli.asb.workspace import Layout

        events: list[str] = []
        podman_calls: list[list[str]] = []
        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)
        state = tmp / "state"
        state.mkdir()
        if manifest_content is not None:
            (state / "runtime.json").write_text(manifest_content, encoding="utf-8")
        runtime_dir = tmp / "runtime" / "rev1"
        runtime_dir.mkdir(parents=True)
        layout = Layout(ws="demo", project="proj", mount=tmp / "mount",
                        project_root=tmp / "mount" / "proj", state=state)
        names = {"net": "asb-demo", "out": "asb-demo-out",
                 "agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        healthy = ProbeResult("probe", "healthy", "ok", 0, "")

        def fake_probe_host(**kwargs):
            events.append("host-probe")
            code = "ok" if host_state == "healthy" else "timeout"
            return ProbeResult("host", host_state, code, 0, "")

        def fake_podman_run(*args, **kwargs):
            podman_calls.append(list(args))
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace",
                        return_value=(names, tmp / "home", tmp / "origin")), \
             mock.patch("cli.asb.lifecycle.layout_for", return_value=layout), \
             mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir), \
             mock.patch("cli.asb.lifecycle.ensure_keyring_service",
                        side_effect=lambda *a, **k: events.append("keyring")) as mock_keyring, \
             mock.patch("cli.asb.lifecycle.subprocess.run", return_value=mock.MagicMock(returncode=0)), \
             mock.patch("cli.asb.lifecycle.supervisor.start_workspace",
                        side_effect=lambda ws, **kw: events.append("start-target")) as mock_start, \
             mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_podman_run), \
             mock.patch("cli.asb.readiness.probe_host", side_effect=fake_probe_host), \
             mock.patch("cli.asb.readiness.probe_workspace", return_value=[healthy]), \
             mock.patch("cli.asb.readiness.wait_until",
                        side_effect=lambda probe, *, timeout, interval=1.0: probe(1.0)), \
             mock.patch("cli.asb.lifecycle.emit", return_value=0):
            rc = lifecycle.resume(tmp / "root", "demo")
        return rc, events, podman_calls, mock_keyring, mock_start

    def test_resume_checks_the_host_then_the_keyring_then_starts_the_target(self):
        rc, events, _, _, mock_start = self._run_resume()
        self.assertEqual(rc, 0)
        self.assertEqual(events, ["host-probe", "keyring", "start-target"])
        mock_start.assert_called_once_with("demo")

    def test_resume_without_network_returns_1_before_keyring_or_target(self):
        rc, events, _, mock_keyring, mock_start = self._run_resume(host_state="unreachable")
        self.assertEqual(rc, 1)
        self.assertEqual(events, ["host-probe"])
        mock_keyring.assert_not_called()
        mock_start.assert_not_called()

    def test_resume_never_initializes_the_rootless_namespace(self):
        rc, _, podman_calls, _, _ = self._run_resume()
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in podman_calls if c and c[0] == "unshare"], [])

    def test_resume_hands_the_installed_runtime_to_the_keyring(self):
        rc, _, _, mock_keyring, _ = self._run_resume()
        self.assertEqual(rc, 0)
        (runtime_dir,), _ = mock_keyring.call_args
        self.assertEqual(runtime_dir.name, "rev1")

    def test_resume_corrupted_manifest_raises_podman_error(self):
        """R6: manifesto corrompido em resume levanta PodmanError em vez de silenciar."""
        from cli.asb.podman import PodmanError
        with self.assertRaises(PodmanError) as ctx:
            self._run_resume(manifest_content="{corrompido: sim")
        self.assertIn("manifesto de runtime corrompido", str(ctx.exception))



class TestTransactionalRollback(unittest.TestCase):
    def test_up_existing_workspace_failure_does_not_sweep(self):
        from unittest import mock
        from cli.asb import lifecycle

        root = Path("/fake/root")
        repo = Path("/fake/repo")
        with mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.install.remove_project_dropin", return_value=False), \
             mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
             mock.patch("cli.asb.lifecycle.prepare_workspace"), \
             mock.patch("cli.asb.lifecycle.supervisor.start_workspace", side_effect=RuntimeError("proxy")), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as sweep:
            with self.assertRaises(RuntimeError):
                lifecycle.up(root, "test-existing", repo)
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

        def fake_prepare(r, ws, rp, tx=None, **kwargs):
            if tx is not None:
                tx.record_container("cid-proxy-new-123")
                tx.record_network(f"asb-{ws}-net")
            raise RuntimeError("simulated failure after partial creation")

        with mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.install.remove_project_dropin", return_value=False), \
             mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
             mock.patch("cli.asb.podman.run", side_effect=fake_run), \
             mock.patch("cli.asb.lifecycle.prepare_workspace", side_effect=fake_prepare), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as sweep:
            with self.assertRaises(RuntimeError):
                lifecycle.up(root, "new-ws", repo)

            sweep.assert_not_called()
            # Only the recorded container ID should be removed
            removed_ids = [c[2] for c in rm_calls if len(c) >= 3 and c[0] == "rm" and c[1] == "-f"]
            self.assertEqual(removed_ids, ["cid-proxy-new-123"])

    def test_up_proxy_readiness_failure_before_mise_install(self):
        from unittest import mock
        from contextlib import ExitStack
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
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)

            healthy_host = mock.MagicMock(state="healthy", code="ok", remediation="")
            failed_proxy = mock.MagicMock(state="failed", code="connect_denied", remediation="fix allowlist")

            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.podman.run"))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="cid-1"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(credentials="c-vol")))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", side_effect=[healthy_host, failed_proxy]))
                mock_mise = stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))

                with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                    lifecycle.up(tmp, "demo", tmp / "origin")
                self.assertIn("proxy nao esta pronto", str(ctx.exception))
                mock_mise.assert_not_called()

    def test_up_rolls_back_when_credential_mount_setup_fails(self):
        """`storage.credential_mounts()` toca o disco (resolve o mountpoint do
        volume e cria os diretorios do fornecedor) e e avaliada DENTRO da
        lista de argumentos do agente. E um ponto de falha novo no meio da
        transacao: se ele levantar, o rollback tem de rodar, senao o proxy e a
        rede ja criados vazam."""
        from unittest import mock
        from contextlib import ExitStack
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.workspace import Layout

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_layout = Layout(ws="demo", project="proj", mount=tmp / "mount",
                                 project_root=tmp / "mount" / "proj",
                                 state=tmp / "state")
            fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                                   host_api="none", container_mode="standard",
                                   allow=[])
            fake_key = tmp / "key"
            fake_key.write_text("k")
            (tmp / "key.pub").write_text("k.pub")
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)

            boom = lifecycle.podman.PodmanError(
                "mountpoint do volume c-vol nao e um diretorio do host")

            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.podman.run"))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="cid-1"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                boom_storage = _fake_storage(credentials="c-vol", session="s-vol")
                boom_storage.credential_mounts = mock.Mock(side_effect=boom)
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage", return_value=boom_storage))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until",
                                               return_value=mock.MagicMock(state="healthy", code="ok")))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))
                rollback = stack.enter_context(mock.patch.object(lifecycle.WorkspaceTransaction, "rollback"))

                with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                    lifecycle.up(tmp, "demo", tmp / "origin")

            self.assertIn("mountpoint do volume", str(ctx.exception))
            rollback.assert_called_once()

    def test_up_ssh_readiness_failure_propagates_and_does_not_emit(self):
        from unittest import mock
        from contextlib import ExitStack
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
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)

            healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")
            failed_ssh = mock.MagicMock(state="failed", code="key_refused", remediation="fix ssh key")

            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.podman.run"))
                stack.enter_context(mock.patch("cli.asb.podman.out", side_effect=["cid-proxy", "cid-agent", "127.0.0.1:2222"]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(credentials="c-vol")))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", side_effect=[healthy_probe, healthy_probe, failed_ssh]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
                mock_emit = stack.enter_context(mock.patch("cli.asb.lifecycle.emit"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))

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
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)
            fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                                 project_root=fake_mount / "proj", state=fake_state)
            fake_key = tmp / "key"
            fake_key.write_text("dummy")
            (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
            fake_profile = Profile(services=[], host_ports=[8080], publish_ports=[],
                                   host_api="none", container_mode="standard", allow=[])

            healthy_probe = mock.MagicMock(state="healthy", code="ok", remediation="")

            from contextlib import ExitStack
            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.podman.run", return_value=mock.MagicMock(returncode=0)))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="cid-fwd-1"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(credentials="c-vol")))
                stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", return_value=healthy_probe))
                stack.enter_context(mock.patch("cli.asb.lifecycle.emit", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))
                rc = lifecycle.up(fake_root, "demo", fake_repo)
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
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)
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

            from contextlib import ExitStack
            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.lifecycle.podman.exists", side_effect=fake_exists))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="run-vol"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(credentials="cred-vol", toolcache="tool-vol")))
                stack.enter_context(mock.patch("cli.asb.lifecycle.podman.run"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl allow ..."))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")))
                stack.enter_context(mock.patch("cli.asb.podman.out", side_effect=fake_out))
                stack.enter_context(mock.patch("cli.asb.lifecycle.emit", side_effect=fake_emit))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))
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

            healthy_host = mock.MagicMock(state="healthy", code="ok", remediation="")
            failed_proxy = mock.MagicMock(state="failed", code="connect_denied", remediation="fix allowlist")
            runtime_dir = tmp / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)

            from contextlib import ExitStack
            with ExitStack() as stack:
                stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
                stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", return_value=False))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
                stack.enter_context(mock.patch("cli.asb.podman.run", return_value=mock.MagicMock(returncode=0)))
                stack.enter_context(mock.patch("cli.asb.podman.out", return_value="cid-xyz"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.load_profile", return_value=fake_profile))
                stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.layout_for", return_value=fake_layout))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.prepare_clone"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.render", return_value="acl x"))
                stack.enter_context(mock.patch("cli.asb.runtime.workspace.build_staging", return_value=0))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
                stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
                stack.enter_context(mock.patch(
                    "cli.asb.runtime.workspace.RuntimeStorage",
                    return_value=_fake_storage(session="s-vol")))
                stack.enter_context(mock.patch.object(Path, "home", return_value=fake_home))
                stack.enter_context(mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)))
                mock_remove = stack.enter_context(mock.patch(
                    "cli.asb.lifecycle.supervisor.remove_workspace_units",
                    side_effect=RuntimeError("systemctl indisponivel")))
                stack.enter_context(mock.patch("cli.asb.readiness.wait_until", side_effect=[healthy_host, failed_proxy]))
                stack.enter_context(mock.patch("cli.asb.lifecycle.supervisor.start_workspace"))

                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                        lifecycle.up(fake_root, "demo", fake_repo)
                self.assertIn("proxy nao esta pronto", str(ctx.exception))

            mock_remove.assert_called_once_with("demo")
            self.assertIn("systemctl indisponivel", stderr.getvalue())

            # install_workspace escreveu unidades REAIS em disco (nao []
            # mockado) antes da falha posterior — e essas sao as unidades
            # que tx.created_units rastreou para o rollback acima.
            unit_file = fake_home / ".config" / "systemd" / "user" / "asb-demo.target"
            self.assertTrue(unit_file.is_file())


class TestNoRuntimeSelection(unittest.TestCase):
    def test_runtime_selection_helper_no_longer_exists(self):
        from cli.asb import lifecycle
        self.assertFalse(hasattr(lifecycle, "_runtime_of"))


class TestRevisionFallbackIsPerCheckout(unittest.TestCase):
    """`dev` era compartilhado: dois checkouts sem git escreviam por cima do
    mesmo diretorio de runtime, e as unidades dos outros workspaces apontam
    para ele."""

    def test_revision_without_git_is_derived_from_the_checkout_path(self):
        from unittest import mock
        from cli.asb import lifecycle

        with mock.patch("cli.asb.lifecycle.subprocess.run",
                        side_effect=FileNotFoundError("git")):
            a = lifecycle._current_revision(Path("/home/v/checkout-a"))
            b = lifecycle._current_revision(Path("/home/v/checkout-b"))
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, "dev")
        for rev in (a, b):
            self.assertTrue(all(c not in rev for c in ("/", "\\", "..", " ")))


class TestDownKeepsWorkspaceData(unittest.TestCase):
    """`down` preserva o trabalho; so `purge` apaga. O volume de containers
    aninhados (imagens que o agente puxou) saia no `down`, ao contrario do
    volume de sessao — mesma classe de dado, tratamento oposto."""

    def _down(self, ws="demo"):
        from unittest import mock
        from cli.asb import lifecycle

        removed = []

        def fake_run(*args, **kwargs):
            if args[:1] == ("volume",):
                removed.append(args[-1])
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace",
                        return_value=(lifecycle.names(ws), Path("/tmp"), Path("/origin"))), \
             mock.patch("cli.asb.lifecycle.layout_for"), \
             mock.patch("cli.asb.lifecycle.remove_state"), \
             mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units"), \
             mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)), \
             mock.patch("cli.asb.podman.out", return_value=""), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", return_value=False), \
             mock.patch("cli.asb.podman.run", side_effect=fake_run):
            lifecycle.down(ws)
        return removed

    def test_down_keeps_the_nested_containers_volume(self):
        self.assertNotIn("asb-demo-containers", self._down())


class TestSharedNetworkGateSurvivesRollback(unittest.TestCase):
    """`up` reescreve `asb-network.service`, que TODO workspace `Requires=`,
    fora do rollback: um `up` que falhava deixava a espera compartilhada
    apontando para o runtime da invocacao que nao vingou."""

    def test_rollback_restores_the_previous_gate_unit(self):
        from unittest import mock
        from cli.asb import lifecycle

        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "asb-network.service"
            gate.write_text("ANTES\n")
            tx = lifecycle.WorkspaceTransaction("demo", is_existing=False)
            tx.record_restore(gate, gate.read_text())
            gate.write_text("DEPOIS\n")

            with mock.patch("cli.asb.podman.run"), \
                 mock.patch("cli.asb.podman.exists", return_value=False), \
                 mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units"):
                tx.rollback()

            self.assertEqual(gate.read_text(), "ANTES\n")


class TestPurgeRemovesNestedContainersVolume(unittest.TestCase):
    def test_purge_removes_what_down_now_preserves(self):
        from unittest import mock
        from cli.asb import lifecycle

        removed = []

        def fake_run(*args, **kwargs):
            if args[:1] == ("volume",):
                removed.append(args[-1])
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._origin_of", return_value=Path("/origin")), \
             mock.patch("cli.asb.lifecycle.layout_for"), \
             mock.patch("cli.asb.lifecycle.down", return_value=0), \
             mock.patch("cli.asb.lifecycle.remove_workspace"), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.run", side_effect=fake_run):
            lifecycle.purge("demo", confirmed=True)

        self.assertIn("asb-demo-containers", removed)
        self.assertIn("asb-demo-session", removed)


class TestPurgeAfterDown(unittest.TestCase):
    """`down` passou a preservar os volumes de sessao e de containers
    aninhados, mas apaga o estado — e o `purge` dependia do estado para saber
    o que limpar. Sem isto, os volumes preservados ficavam orfaos para sempre,
    sem nenhum comando do CLI capaz de remove-los."""

    def _purge(self, confirmed=True):
        from unittest import mock
        from cli.asb import lifecycle

        removed = []

        def fake_run(*args, **kwargs):
            if args[:1] == ("volume",):
                removed.append(args[-1])
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("cli.asb.lifecycle.os.path.expanduser", return_value=tmp), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None), \
             mock.patch("cli.asb.lifecycle.down", return_value=0) as down, \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.run", side_effect=fake_run):
            import contextlib, io
            with contextlib.redirect_stderr(io.StringIO()):
                rc = lifecycle.purge("demo", confirmed=confirmed)
        return rc, removed, down

    def test_purge_without_state_still_removes_the_named_volumes(self):
        rc, removed, down = self._purge()
        self.assertEqual(rc, 0)
        self.assertIn("asb-demo-session", removed)
        self.assertIn("asb-demo-containers", removed)
        down.assert_called_once_with("demo")

    def test_purge_without_state_still_requires_confirmation(self):
        from cli.asb import lifecycle
        with self.assertRaises(lifecycle.podman.PodmanError):
            self._purge(confirmed=False)


class TestManagedLifecycleCommands(unittest.TestCase):
    def test_suspend_disables_and_stops_target_and_verifies_stopped(self):
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        systemctl_calls = []

        def fake_subprocess_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "systemctl":
                systemctl_calls.append(cmd)
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("subprocess.run", side_effect=fake_subprocess_run), \
             mock.patch("cli.asb.podman.out", return_value="asb-demo-agent\nasb-demo-proxy"), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", return_value=False):
            rc = lifecycle.suspend("demo")
            self.assertEqual(rc, 0)
            self.assertTrue(any("disable" in c and "asb-demo.target" in c for c in systemctl_calls))
            self.assertTrue(any("stop" in c and "asb-demo.target" in c for c in systemctl_calls))

    def test_suspend_fails_when_the_unit_survives_the_stop(self):
        """Achado da revisao final: `systemctl` falhando (hook sem barramento
        do usuario, por exemplo) ia para /dev/null, e a verificacao perguntava
        ao Podman. Com a unidade viva, `Restart=always` devolve o container
        cinco segundos depois e o operador ja leu 'suspenso'."""
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}

        def fake_subprocess_run(cmd, *args, **kwargs):
            if cmd[:3] == ["systemctl", "--user", "is-active"]:
                return mock.MagicMock(returncode=0, stdout="active\n", stderr="")
            return mock.MagicMock(returncode=1, stdout="", stderr="Failed to connect to bus")

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
             mock.patch("subprocess.run", side_effect=fake_subprocess_run), \
             mock.patch("cli.asb.podman.out", return_value=""), \
             mock.patch("cli.asb.podman.exists", return_value=True), \
             mock.patch("cli.asb.podman.running", return_value=False), \
             mock.patch("cli.asb.podman.run") as podman_run:
            import contextlib, io
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.suspend("demo")
        self.assertEqual(rc, 1)
        self.assertIn("asb-demo.target", stderr.getvalue())
        # Falha do systemctl deixa de ser invisivel.
        self.assertIn("Failed to connect to bus", stderr.getvalue())
        # E nao se para container enquanto a unidade pode devolve-lo.
        podman_run.assert_not_called()

    def test_suspend_fails_when_container_refuses_to_stop(self):
        """S1: suspend deve verificar que os containers pararam de fato, e
        retornar codigo != 0 (nunca 0 incondicional) quando algum permanece
        em execucao apos o stop."""
        from unittest import mock
        from cli.asb import lifecycle

        fake_n = {"agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}

        with mock.patch("cli.asb.lifecycle._require_workspace", return_value=(fake_n, Path("/tmp"), Path("/origin"))), \
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

    def test_resume_enables_resets_starts_and_checks_probes(self):
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
             mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=Path("/tmp/runtime/rev1")), \
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

    def test_down_removes_units_before_cleaning_containers(self):
        from unittest import mock
        from cli.asb import lifecycle

        events = []

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units", side_effect=lambda ws, **kw: events.append("remove_units")) as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers", side_effect=lambda ws: events.append("sweep_containers")), \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            rc = lifecycle.down("demo")
            self.assertEqual(rc, 0)
            mock_remove.assert_called_once()
            self.assertEqual(mock_remove.call_args[0][0], "demo")
            self.assertEqual(events, ["remove_units", "sweep_containers"])

    def test_down_continues_sweeping_when_daemon_reload_fails(self):
        """B#4: `remove_workspace_units` termina em `daemon-reload` com
        check=True. Numa sessao systemd de usuario ausente ou velha —
        plausivel exatamente quando se derruba um workspace quebrado — a
        excecao propagava para fora de `down` ANTES do `_sweep_containers`,
        largando containers, redes e volumes para tras. `down` e a saida de
        emergencia: nunca aborta a limpeza local."""
        from unittest import mock
        from cli.asb import lifecycle
        import contextlib
        import io
        import subprocess as _subprocess

        boom = _subprocess.CalledProcessError(
            1, ["systemctl", "--user", "daemon-reload"])
        events = []

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units",
                        side_effect=boom) as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers",
                        side_effect=lambda ws: events.append("sweep")) as mock_sweep, \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.down("demo")

        self.assertEqual(rc, 0)
        mock_remove.assert_called_once()
        mock_sweep.assert_called_once_with("demo")
        self.assertEqual(events, ["sweep"])
        self.assertIn("aviso", stderr.getvalue())
        self.assertIn("daemon-reload", stderr.getvalue())

    def test_down_continues_sweeping_when_systemctl_is_missing(self):
        """Mesmo contrato para `FileNotFoundError`: host sem `systemctl` no
        PATH tambem nao pode abortar a limpeza local."""
        from unittest import mock
        from cli.asb import lifecycle
        import contextlib
        import io

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units",
                        side_effect=FileNotFoundError("systemctl")), \
             mock.patch("cli.asb.lifecycle._sweep_containers") as mock_sweep, \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.down("demo")

        self.assertEqual(rc, 0)
        mock_sweep.assert_called_once_with("demo")
        self.assertIn("aviso", stderr.getvalue())

    def test_down_with_corrupted_manifest_still_cleans_up_best_effort(self):
        """`down` e a saida de emergencia: um runtime.json corrompido que faz
        `remove_workspace_units` levantar NUNCA aborta a limpeza local."""
        from unittest import mock
        from cli.asb import lifecycle
        import contextlib
        import io

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units",
                        side_effect=ValueError("manifesto de runtime corrompido")) as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers") as mock_sweep, \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.down("demo")
        self.assertEqual(rc, 0)
        mock_remove.assert_called_once()
        mock_sweep.assert_called_once_with("demo")
        self.assertIn("manifesto de runtime corrompido", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
