"""Testes de `asb.runtime.connection` e `asb.runtime.sandbox` (Tarefa 3).

Cobre o contrato externo duro: o `argv` exato de `ssh_argv`, o payload exato
de `to_lifecycle_payload` (as mesmas quatro chaves, mesma ordem, mesmos tipos
que `lifecycle.emit()` ja imprime), cada modo de falha de
`resolve_connection` (container ausente, origem ausente, porta ausente,
porta corrompida, chave ausente — todos levantam `PodmanError` sem imprimir
nada em stdout), e a ordem de `SandboxRuntime.ensure()` (so dispara o CLI
estavel quando nao ha runtime vivo, e nunca escreve no registro: o vinculo
ja existe desde o registro do checkout).

Nenhum teste aqui toca Podman, systemd ou SSH de verdade: tudo o que
`resolve_connection` consultaria e mockado.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import podman  # noqa: E402
from asb.checkouts.model import (  # noqa: E402
    Checkout, CheckoutId, CheckoutKind, CheckoutState,
)
from asb.projects.model import Project, ProjectId  # noqa: E402
from asb.projects.registry import CheckoutBinding, ProjectRegistry  # noqa: E402
from asb.runtime.connection import ConnectionInfo, resolve_connection  # noqa: E402
from asb.runtime.sandbox import (  # noqa: E402
    SandboxRuntime, session_volume_mountpoint,
)
from asb.workspace import Layout  # noqa: E402


def _info(**overrides) -> ConnectionInfo:
    fields = {
        "workspace": "ws-1", "host": "127.0.0.1", "port": 2222,
        "username": "v", "identity_file": Path("/keys/id_ed25519"),
        "project_root": Path("/sandbox/repo"),
    }
    fields.update(overrides)
    return ConnectionInfo(**fields)


class TestSshArgvContract(unittest.TestCase):
    def test_exact_argv_with_a_command(self):
        info = _info()
        self.assertEqual(info.ssh_argv(("pwd",)), [
            "ssh", "-tt", "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-i", "/keys/id_ed25519",
            "-p", "2222", "--", "v@127.0.0.1", "pwd",
        ])

    def test_no_command_has_no_trailing_argument(self):
        info = _info()
        self.assertEqual(info.ssh_argv(), [
            "ssh", "-tt", "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-i", "/keys/id_ed25519",
            "-p", "2222", "--", "v@127.0.0.1",
        ])

    def test_multi_word_command_becomes_one_joined_trailing_argument(self):
        info = _info()
        argv = info.ssh_argv(("ls", "-la", "/tmp"))
        self.assertEqual(argv[-1], "ls -la /tmp")
        self.assertEqual(argv[-2], "v@127.0.0.1")
        self.assertEqual(len(argv), 17)

    def test_accept_new_is_never_present(self):
        # O operador substituiu `accept-new` pela politica que
        # `readiness.py`/`auth.py` ja usam para este mesmo loopback:
        # host keys sao compartilhadas por build de imagem e portas sao
        # efemeras, entao `accept-new` falha apos rebuild ou porta reusada.
        info = _info()
        argv = info.ssh_argv(("pwd",))
        self.assertTrue(all("accept-new" not in arg for arg in argv))

    def test_destination_is_preceded_by_a_bare_double_dash(self):
        info = _info()
        argv = info.ssh_argv()
        self.assertEqual(argv[-2], "--")
        self.assertEqual(argv[-1], "v@127.0.0.1")

    def test_rejects_out_of_range_ports(self):
        for bad_port in (0, -1, 65536, 100000):
            with self.assertRaises(ValueError):
                _info(port=bad_port).ssh_argv()

    def test_accepts_boundary_ports(self):
        for good_port in (1, 65535):
            self.assertIn(str(good_port), _info(port=good_port).ssh_argv())

    def test_rejects_bool_disguised_as_int(self):
        # bool e subclasse de int em Python; True/False nunca sao portas
        # validas, mesmo passando a checagem ingenua `isinstance(x, int)`.
        with self.assertRaises(ValueError):
            _info(port=True).ssh_argv()


class TestSshArgvNonInteractive(unittest.TestCase):
    """`interactive=False`: sem TTY (`-T` no lugar de `-tt`), nunca pede
    senha (`BatchMode=yes`) e desiste de conectar em 10 s — as mesmas
    opcoes que `auth.py` ja usa para SSH nao interativo."""

    def test_exact_argv_with_a_command(self):
        self.assertEqual(_info().ssh_argv(("pwd",), interactive=False), [
            "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-i", "/keys/id_ed25519",
            "-p", "2222", "--", "v@127.0.0.1", "pwd",
        ])

    def test_exact_argv_without_a_command(self):
        self.assertEqual(_info().ssh_argv(interactive=False), [
            "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-i", "/keys/id_ed25519",
            "-p", "2222", "--", "v@127.0.0.1",
        ])

    def test_multi_word_command_is_still_one_joined_trailing_argument(self):
        argv = _info().ssh_argv(("ls", "-la", "/a b"), interactive=False)
        self.assertEqual(argv[-1], "ls -la '/a b'")
        self.assertEqual(argv[-2], "v@127.0.0.1")
        self.assertEqual(argv[-3], "--")
        self.assertNotIn("-tt", argv)

    def test_interactive_true_is_the_default_argv(self):
        info = _info()
        self.assertEqual(info.ssh_argv(("pwd",), interactive=True),
                         info.ssh_argv(("pwd",)))

    def test_non_interactive_still_rejects_invalid_ports(self):
        with self.assertRaises(ValueError):
            _info(port=0).ssh_argv(interactive=False)


class TestLifecyclePayloadContract(unittest.TestCase):
    def test_exact_payload_shape(self):
        info = _info()
        self.assertEqual(info.to_lifecycle_payload(), {
            "workspace": "ws-1", "port": 2222, "user": "v",
            "project_root": "/sandbox/repo",
        })

    def test_port_is_an_int_not_a_string(self):
        payload = _info(port=2222).to_lifecycle_payload()
        self.assertIsInstance(payload["port"], int)

    def test_payload_key_order_matches_the_lifecycle_contract(self):
        self.assertEqual(list(_info().to_lifecycle_payload().keys()),
                         ["workspace", "port", "user", "project_root"])


class TestResolveConnectionFailureModes(unittest.TestCase):
    """Cada modo de falha do brief: PodmanError, stdout vazio."""

    def test_missing_container_raises(self):
        stdout = io.StringIO()
        with mock.patch(
                "asb.lifecycle._require_workspace",
                side_effect=podman.PodmanError(
                    "workspace inexistente: ws-1 (use 'up')")):
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(podman.PodmanError):
                    resolve_connection("ws-1")
        self.assertEqual(stdout.getvalue(), "")

    def test_missing_origin_raises(self):
        stdout = io.StringIO()
        with mock.patch(
                "asb.lifecycle._require_workspace",
                side_effect=podman.PodmanError(
                    "estado ausente para ws-1; recrie o workspace com 'up'")):
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(podman.PodmanError):
                    resolve_connection("ws-1")
        self.assertEqual(stdout.getvalue(), "")

    def test_missing_port_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_layout = Layout(ws="ws-1", project="proj", mount=tmp / "mount",
                                 project_root=tmp / "mount" / "proj",
                                 state=tmp / "state")
            key = tmp / "key"
            key.write_text("k")
            stdout = io.StringIO()
            with mock.patch("asb.lifecycle._require_workspace",
                            return_value=({"agent": "asb-ws-1-agent"},
                                         tmp / "home", tmp / "origin")), \
                 mock.patch("asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("asb.podman.out", return_value=""), \
                 mock.patch("asb.lifecycle.SSH_KEY", key):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(podman.PodmanError):
                        resolve_connection("ws-1")
            self.assertEqual(stdout.getvalue(), "")

    def test_corrupt_port_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_layout = Layout(ws="ws-1", project="proj", mount=tmp / "mount",
                                 project_root=tmp / "mount" / "proj",
                                 state=tmp / "state")
            key = tmp / "key"
            key.write_text("k")
            stdout = io.StringIO()
            with mock.patch("asb.lifecycle._require_workspace",
                            return_value=({"agent": "asb-ws-1-agent"},
                                         tmp / "home", tmp / "origin")), \
                 mock.patch("asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("asb.podman.out", return_value="127.0.0.1:notaport"), \
                 mock.patch("asb.lifecycle.SSH_KEY", key):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(podman.PodmanError):
                        resolve_connection("ws-1")
            self.assertEqual(stdout.getvalue(), "")

    def test_missing_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_layout = Layout(ws="ws-1", project="proj", mount=tmp / "mount",
                                 project_root=tmp / "mount" / "proj",
                                 state=tmp / "state")
            missing_key = tmp / "does-not-exist"
            stdout = io.StringIO()
            with mock.patch("asb.lifecycle._require_workspace",
                            return_value=({"agent": "asb-ws-1-agent"},
                                         tmp / "home", tmp / "origin")), \
                 mock.patch("asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("asb.podman.out", return_value="0.0.0.0:2222"), \
                 mock.patch("asb.lifecycle.SSH_KEY", missing_key):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(podman.PodmanError):
                        resolve_connection("ws-1")
            self.assertEqual(stdout.getvalue(), "")


class TestResolveConnectionSuccess(unittest.TestCase):
    def test_returns_live_evidence_with_the_constant_loopback_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project_root = tmp / "mount" / "proj"
            fake_layout = Layout(ws="ws-1", project="proj", mount=tmp / "mount",
                                 project_root=project_root, state=tmp / "state")
            key = tmp / "key"
            key.write_text("k")
            with mock.patch("asb.lifecycle._require_workspace",
                            return_value=({"agent": "asb-ws-1-agent"},
                                         tmp / "home", tmp / "origin")), \
                 mock.patch("asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("asb.podman.out", return_value="0.0.0.0:2222"), \
                 mock.patch("asb.lifecycle.SSH_KEY", key), \
                 mock.patch("getpass.getuser", return_value="v"):
                info = resolve_connection("ws-1")

            self.assertEqual(info, ConnectionInfo(
                "ws-1", "127.0.0.1", 2222, "v", key, project_root))

    def test_never_calls_podman_port_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_layout = Layout(ws="ws-1", project="proj", mount=tmp / "mount",
                                 project_root=tmp / "mount" / "proj",
                                 state=tmp / "state")
            key = tmp / "key"
            key.write_text("k")
            calls = []

            def fake_out(*args, **kwargs):
                calls.append(args)
                return "0.0.0.0:2222"

            with mock.patch("asb.lifecycle._require_workspace",
                            return_value=({"agent": "asb-ws-1-agent"},
                                         tmp / "home", tmp / "origin")), \
                 mock.patch("asb.lifecycle.layout_for", return_value=fake_layout), \
                 mock.patch("asb.podman.out", side_effect=fake_out), \
                 mock.patch("asb.lifecycle.SSH_KEY", key), \
                 mock.patch("getpass.getuser", return_value="v"):
                resolve_connection("ws-1")

            self.assertEqual(len(calls), 1)


def _project_and_checkout(tmp: Path) -> tuple[Project, Checkout]:
    project = Project(
        id=ProjectId("p-" + "a" * 16), primary=tmp / "primary",
        integration_branch="main", worktree_root=tmp / "worktrees")
    checkout = Checkout(
        id=CheckoutId("c-abc123"), project_id=project.id, path=tmp / "primary",
        kind=CheckoutKind.PRIMARY, branch="main", state=CheckoutState.CLEAN,
        workspace="ws-1")
    return project, checkout


def _binding(tmp: Path) -> CheckoutBinding:
    """O registro persistido do checkout: e o que `ensure()` recebe."""
    return CheckoutBinding(
        checkout_id=CheckoutId("c-abc123"), project_id=ProjectId("p-" + "a" * 16),
        source_path=tmp / "primary", workspace="ws-1")


class TestSandboxRuntimeEnsure(unittest.TestCase):
    """Ronda 1 de revisao: so a AUSENCIA do container autoriza a queda para
    `asb-agent up`. Um container que ja existe segue direto para
    `resolve_connection`, e qualquer falha dali (porta corrompida, chave
    ausente) tem de chegar ao chamador sem disfarce — nunca dispara o
    runner."""

    def test_skips_the_cli_boundary_when_a_live_binding_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            live = _info(workspace="ws-1", project_root=tmp / "root")
            registry = mock.MagicMock(spec=ProjectRegistry)
            runner = mock.Mock(side_effect=AssertionError(
                "nao deveria disparar o runner quando ja ha runtime vivo"))

            with mock.patch("asb.podman.exists", return_value=True), \
                 mock.patch("asb.runtime.sandbox.resolve_connection",
                            return_value=live):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=runner)
                info = runtime.ensure(checkout)

            self.assertEqual(info, live)
            runner.assert_not_called()
            self.assertEqual(registry.method_calls, [])

    def test_raises_the_real_diagnostic_and_never_invokes_the_cli_boundary_when_the_live_container_has_a_corrupt_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)
            runner = mock.Mock(side_effect=AssertionError(
                "nao deveria disparar o runner para um container ja existente"))

            with mock.patch("asb.podman.exists", return_value=True), \
                 mock.patch(
                     "asb.runtime.sandbox.resolve_connection",
                     side_effect=podman.PodmanError(
                         "porta SSH corrompida para ws-1: 'notaport'")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=runner)
                with self.assertRaises(podman.PodmanError) as ctx:
                    runtime.ensure(checkout)

            self.assertIn("porta SSH corrompida", str(ctx.exception))
            runner.assert_not_called()
            self.assertEqual(registry.method_calls, [])

    def test_raises_the_real_diagnostic_and_never_invokes_the_cli_boundary_when_the_live_container_has_no_ssh_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)
            runner = mock.Mock(side_effect=AssertionError(
                "nao deveria disparar o runner para um container ja existente"))

            with mock.patch("asb.podman.exists", return_value=True), \
                 mock.patch(
                     "asb.runtime.sandbox.resolve_connection",
                     side_effect=podman.PodmanError(
                         "chave SSH ausente para ws-1: /keys/id_ed25519")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=runner)
                with self.assertRaises(podman.PodmanError) as ctx:
                    runtime.ensure(checkout)

            self.assertIn("chave SSH ausente", str(ctx.exception))
            runner.assert_not_called()
            self.assertEqual(registry.method_calls, [])

    def test_spawns_the_stable_cli_boundary_with_the_exact_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "root"
            checkout = _binding(tmp)
            live = _info(workspace="ws-1", project_root=root)
            registry = mock.MagicMock(spec=ProjectRegistry)
            captured = {}

            def fake_runner(argv):
                captured["argv"] = list(argv)
                return subprocess.CompletedProcess(
                    list(argv), 0,
                    stdout=json.dumps({"workspace": "ws-1", "port": 2222,
                                      "user": "v", "project_root": str(root)}),
                    stderr="")

            with mock.patch("asb.podman.exists", return_value=False), \
                 mock.patch("asb.runtime.sandbox.resolve_connection",
                            return_value=live):
                runtime = SandboxRuntime(root=root, registry=registry,
                                         runner=fake_runner)
                info = runtime.ensure(checkout)

            self.assertEqual(info, live)
            self.assertEqual(captured["argv"], [
                str(root / "cli" / "asb-agent"), "up",
                "--workspace", "ws-1", "--repo", str(checkout.source_path),
            ])
            self.assertEqual(registry.method_calls, [])

    def test_raises_and_never_records_a_binding_when_the_cli_boundary_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)

            def fake_runner(argv):
                return subprocess.CompletedProcess(list(argv), 1, stdout="",
                                                   stderr="boom")

            with mock.patch("asb.podman.exists", return_value=False), \
                 mock.patch(
                     "asb.runtime.sandbox.resolve_connection",
                     side_effect=AssertionError(
                         "nao deveria chamar resolve_connection antes do runner")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=fake_runner)
                with self.assertRaises(podman.PodmanError):
                    runtime.ensure(checkout)

            self.assertEqual(registry.method_calls, [])

    def test_raises_and_never_records_a_binding_when_readiness_never_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)

            def fake_runner(argv):
                return subprocess.CompletedProcess(
                    list(argv), 0,
                    stdout=json.dumps({"workspace": "ws-1", "port": 2222,
                                      "user": "v", "project_root": "/x"}),
                    stderr="")

            with mock.patch("asb.podman.exists", return_value=False), \
                 mock.patch(
                    "asb.runtime.sandbox.resolve_connection",
                    side_effect=podman.PodmanError("workspace nunca ficou pronto")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=fake_runner)
                with self.assertRaises(podman.PodmanError):
                    runtime.ensure(checkout)

            self.assertEqual(registry.method_calls, [])

    def test_raises_when_the_cli_boundary_prints_no_connection_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)

            def fake_runner(argv):
                return subprocess.CompletedProcess(list(argv), 0, stdout="",
                                                   stderr="")

            with mock.patch("asb.podman.exists", return_value=False), \
                 mock.patch(
                     "asb.runtime.sandbox.resolve_connection",
                     side_effect=AssertionError(
                         "nao deveria chamar resolve_connection antes do runner")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=fake_runner)
                with self.assertRaises(podman.PodmanError):
                    runtime.ensure(checkout)

            self.assertEqual(registry.method_calls, [])

    def test_raises_a_podman_error_when_the_cli_binary_is_missing(self):
        """Minor (ronda 1): o runner injetado pode falhar fora do contrato
        de `CompletedProcess` (ex: 'asb-agent' ausente do disco) — isto tem
        de virar `PodmanError`, nunca escapar como `OSError` cru, e a causa
        original tem de ficar encadeada."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            checkout = _binding(tmp)
            registry = mock.MagicMock(spec=ProjectRegistry)
            original = FileNotFoundError(
                "[Errno 2] No such file or directory: 'asb-agent'")

            def fake_runner(argv):
                raise original

            with mock.patch("asb.podman.exists", return_value=False), \
                 mock.patch(
                     "asb.runtime.sandbox.resolve_connection",
                     side_effect=AssertionError(
                         "nao deveria chamar resolve_connection antes do runner")):
                runtime = SandboxRuntime(root=tmp / "root", registry=registry,
                                         runner=fake_runner)
                with self.assertRaises(podman.PodmanError) as ctx:
                    runtime.ensure(checkout)

            self.assertIs(ctx.exception.__cause__, original)
            self.assertEqual(registry.method_calls, [])


class TestSandboxRuntimeBindingFor(unittest.TestCase):
    def test_matches_by_project_and_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project, checkout = _project_and_checkout(tmp)
            binding = CheckoutBinding(
                checkout_id=CheckoutId("c-registrybnd"), project_id=project.id,
                source_path=checkout.path, workspace="ws-1")
            registry = mock.MagicMock(spec=ProjectRegistry)
            registry.bindings.return_value = [binding]
            runtime = SandboxRuntime(root=tmp, registry=registry, runner=mock.Mock())

            found = runtime.binding_for(checkout)

            self.assertEqual(found, binding)
            registry.bindings.assert_called_once_with(project.id)

    def test_returns_none_when_no_binding_matches_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project, checkout = _project_and_checkout(tmp)
            other = CheckoutBinding(
                checkout_id=CheckoutId("c-otherbnd001"), project_id=project.id,
                source_path=tmp / "other", workspace="ws-other")
            registry = mock.MagicMock(spec=ProjectRegistry)
            registry.bindings.return_value = [other]
            runtime = SandboxRuntime(root=tmp, registry=registry, runner=mock.Mock())

            self.assertIsNone(runtime.binding_for(checkout))


class TestSandboxRuntimeDiscover(unittest.TestCase):
    def test_pairs_live_connections_with_their_bindings_and_skips_dead_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project, _ = _project_and_checkout(tmp)
            alive = CheckoutBinding(
                checkout_id=CheckoutId("c-alivebnd001"), project_id=project.id,
                source_path=tmp / "a", workspace="ws-alive")
            dead = CheckoutBinding(
                checkout_id=CheckoutId("c-deadbnd0001"), project_id=project.id,
                source_path=tmp / "b", workspace="ws-dead")
            registry = mock.MagicMock(spec=ProjectRegistry)
            registry.bindings.return_value = [alive, dead]
            live_info = _info(workspace="ws-alive")

            def fake_resolve(ws):
                if ws == "ws-alive":
                    return live_info
                raise podman.PodmanError("parado")

            with mock.patch("asb.runtime.sandbox.resolve_connection",
                            side_effect=fake_resolve):
                runtime = SandboxRuntime(root=tmp, registry=registry,
                                         runner=mock.Mock())
                found = runtime.discover(project)

            self.assertEqual(found, [(alive, live_info)])



class TestSessionVolumeMountpoint(unittest.TestCase):
    """Podman inteiramente mockado: nenhum volume real e inspecionado."""

    def test_inspects_the_workspace_session_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("asb.podman.out", return_value=tmp) as out, \
                 mock.patch("asb.podman.run") as run:
                self.assertEqual(session_volume_mountpoint("ws1"), Path(tmp))
        out.assert_called_once_with(
            "volume", "inspect", "asb-ws1-session",
            "--format", "{{.Mountpoint}}")
        run.assert_not_called()

    def test_missing_volume_raises_without_creating_it(self):
        with mock.patch("asb.podman.out",
                        side_effect=podman.PodmanError("no such volume")), \
             mock.patch("asb.podman.run") as run:
            with self.assertRaises(podman.PodmanError):
                session_volume_mountpoint("ws1")
        run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
