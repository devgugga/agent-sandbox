"""Unit tests for cli/asb/supervisor.py — systemd supervision and unit generation."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import supervisor  # noqa: E402


class TestContainerUnitAndRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.checkout = self.tmp_path / "checkout"
        self.checkout.mkdir(parents=True)
        self.runtime_dir = self.tmp_path / "runtime" / "rev1"
        self.runtime_dir.mkdir(parents=True)
        self.launcher = self.runtime_dir / "launcher.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.launcher.chmod(0o755)
        self.state_dir = self.tmp_path / "state" / "test-ws"
        self.state_dir.mkdir(parents=True)
        self.manifest = self.state_dir / "runtime.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "workspace": "test-ws",
                    "containers": {
                        "proxy": {"name": "asb-test-ws-proxy", "id": "p123"},
                        "agent": {"name": "asb-test-ws-agent", "id": "a456", "port": 2222},
                    },
                }
            )
        )

    def test_container_unit_frozen_and_fields(self):
        unit = supervisor.ContainerUnit(
            name="asb-test-ws-agent",
            container_id="a456",
            role="agent",
            unit_name="asb-test-ws-agent.service",
            target_name="asb-test-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
        )
        self.assertEqual(unit.name, "asb-test-ws-agent")
        self.assertEqual(unit.container_id, "a456")
        self.assertEqual(unit.role, "agent")
        self.assertEqual(unit.unit_name, "asb-test-ws-agent.service")
        self.assertEqual(unit.target_name, "asb-test-ws.target")
        self.assertEqual(unit.helper_path, self.launcher)
        self.assertEqual(unit.manifest_path, self.manifest)
        with self.assertRaises(AttributeError):
            unit.name = "mutate"  # frozen dataclass

    def test_rejects_newline_in_unit_fields(self):
        invalid_fields = [
            {"name": "asb-test\nagent"},
            {"container_id": "a456\r\n"},
            {"role": "agent\n"},
            {"unit_name": "asb-agent.service\n"},
            {"target_name": "asb.target\n"},
        ]
        for field in invalid_fields:
            params = {
                "name": "asb-test-agent",
                "container_id": "c123",
                "role": "agent",
                "unit_name": "asb-agent.service",
                "target_name": "asb.target",
                "helper_path": self.launcher,
                "manifest_path": self.manifest,
            }
            params.update(field)
            with self.assertRaises(ValueError, msg=f"Should reject newline in {field}"):
                supervisor.ContainerUnit(**params)

    def test_render_unit_mandatory_fields_and_no_checkout(self):
        unit = supervisor.ContainerUnit(
            name="asb-test-ws-agent",
            container_id="a456",
            role="agent",
            unit_name="asb-test-ws-agent.service",
            target_name="asb-test-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
        )
        text = supervisor.render_unit(unit)

        self.assertIn("--attach", text)
        self.assertIn("--sig-proxy=false", text)
        self.assertIn("Restart=always", text)
        self.assertIn("RestartSec=5s", text)
        self.assertIn("TimeoutStartSec=150s", text)
        self.assertIn("TimeoutStopSec=20s", text)
        self.assertIn("KillMode=process", text)
        self.assertIn("StartLimitIntervalSec=600s", text)
        self.assertIn("StartLimitBurst=3", text)
        self.assertIn("ExecStopPost=", text)
        self.assertNotIn(str(self.checkout), text)
        self.assertNotIn("start --all", text)
        self.assertNotIn("BindsTo", text)

    def test_render_unit_dependencies(self):
        # Proxy unit
        proxy_unit = supervisor.ContainerUnit(
            name="asb-test-ws-proxy",
            container_id="p123",
            role="proxy",
            unit_name="asb-test-ws-proxy.service",
            target_name="asb-test-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
        )
        proxy_text = supervisor.render_unit(proxy_unit)
        self.assertIn("PartOf=asb-test-ws.target", proxy_text)
        self.assertNotIn("asb-test-ws-agent.service", proxy_text)

        # Agent unit: must have After and Wants on proxy and keyring
        agent_unit = supervisor.ContainerUnit(
            name="asb-test-ws-agent",
            container_id="a456",
            role="agent",
            unit_name="asb-test-ws-agent.service",
            target_name="asb-test-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
        )
        agent_text = supervisor.render_unit(agent_unit)
        self.assertIn("PartOf=asb-test-ws.target", agent_text)
        self.assertIn("asb-test-ws-proxy.service", agent_text)
        self.assertIn("asb-keyring.service", agent_text)
        self.assertIn("After=", agent_text)
        self.assertIn("Wants=", agent_text)
        self.assertNotIn("BindsTo", agent_text)

    def test_render_unit_exec_start_post_runtime_check(self):
        unit = supervisor.ContainerUnit(
            name="asb-test-ws-agent",
            container_id="a456",
            role="agent",
            unit_name="asb-test-ws-agent.service",
            target_name="asb-test-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
        )
        text = supervisor.render_unit(unit)
        self.assertIn("ExecStartPost=", text)
        self.assertIn("runtime_check.py", text)
        self.assertIn("--role agent", text)
        self.assertIn(f"--manifest {self.manifest}", text)

    def test_render_unit_escaping_spaces_and_percent(self):
        special_dir = self.tmp_path / "space dir" / "pct%dir"
        special_dir.mkdir(parents=True)
        special_launcher = special_dir / "my launcher.sh"
        special_launcher.write_text("#!/bin/sh\nexit 0\n")
        special_launcher.chmod(0o755)
        special_manifest = special_dir / "my %manifest.json"
        special_manifest.write_text("{}")

        unit = supervisor.ContainerUnit(
            name="asb-test-ws-agent",
            container_id="a456",
            role="agent",
            unit_name="asb-test-ws-agent.service",
            target_name="asb-test-ws.target",
            helper_path=special_launcher,
            manifest_path=special_manifest,
        )
        text = supervisor.render_unit(unit)

        # Percent % must be escaped as %% in systemd unit syntax
        self.assertIn("pct%%dir", text)
        self.assertIn("my %%manifest.json", text)
        # Paths with spaces must be quoted
        escaped_launcher_str = str(special_launcher).replace("%", "%%")
        self.assertIn(f'"{escaped_launcher_str}"', text)
        escaped_manifest_str = str(special_manifest).replace("%", "%%")
        self.assertIn(f'"{escaped_manifest_str}"', text)

        # Verify parsing with systemd-analyze if available
        if shutil.which("systemd-analyze"):
            unit_file = self.tmp_path / "test-verify.service"
            # create mock runtime_check.py in special_dir
            mock_rc = special_dir / "runtime_check.py"
            mock_rc.write_text("#!/bin/sh\nexit 0\n")
            mock_rc.chmod(0o755)
            # create mock asb-network.service to satisfy Requires=asb-network.service
            gate_file = self.tmp_path / "asb-network.service"
            gate_file.write_text(
                supervisor.render_network_unit(special_launcher), encoding="utf-8")
            unit_file.write_text(text, encoding="utf-8")
            res = subprocess.run(
                ["systemd-analyze", "verify", str(unit_file), str(gate_file)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"systemd-analyze verify failed on rendered unit: {res.stderr}",
            )


class TestWorkspaceOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.fake_home = self.tmp_path / "home"
        self.fake_home.mkdir()
        self.target_dir = self.fake_home / ".config" / "systemd" / "user"
        self.target_dir.mkdir(parents=True)
        self.state_dir = self.fake_home / ".local" / "state" / "agent-sandbox" / "myws"
        self.state_dir.mkdir(parents=True)
        self.runtime_dir = self.fake_home / ".local" / "lib" / "agent-sandbox" / "runtime" / "r1"
        self.runtime_dir.mkdir(parents=True)
        self.launcher = self.runtime_dir / "launcher.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.launcher.chmod(0o755)
        self.manifest_file = self.state_dir / "runtime.json"
        self.manifest_data = {
            "schemaVersion": 1,
            "workspace": "myws",
            "revision": "r1",
            "containers": {
                "proxy": {"name": "asb-myws-proxy", "id": "p111"},
                "agent": {"name": "asb-myws-agent", "id": "a222", "port": 2222},
            },
        }
        self.manifest_file.write_text(json.dumps(self.manifest_data), encoding="utf-8")

    def test_install_workspace_atomic_writes_units_and_reloads(self):
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch("subprocess.run") as mock_run:
            supervisor.install_workspace(
                "myws",
                target_dir=self.target_dir,
                state_dir=self.state_dir,
                helper_path=self.launcher,
            )

        proxy_unit = self.target_dir / "asb-myws-proxy.service"
        agent_unit = self.target_dir / "asb-myws-agent.service"
        target_unit = self.target_dir / "asb-myws.target"

        self.assertTrue(proxy_unit.is_file())
        self.assertTrue(agent_unit.is_file())
        self.assertTrue(target_unit.is_file())

        proxy_content = proxy_unit.read_text()
        self.assertIn("asb-myws-proxy", proxy_content)
        self.assertIn("PartOf=asb-myws.target", proxy_content)

        agent_content = agent_unit.read_text()
        self.assertIn("asb-myws-agent", agent_content)
        self.assertIn("asb-myws-proxy.service", agent_content)

        target_content = target_unit.read_text()
        self.assertIn("WantedBy=default.target", target_content)

        mock_run.assert_any_call(["systemctl", "--user", "daemon-reload"], check=True)

    def test_install_workspace_rejects_missing_or_invalid_manifest(self):
        # Missing manifest
        missing_state = self.tmp_path / "nonexistent"
        with self.assertRaises(FileNotFoundError):
            supervisor.install_workspace("otherws", target_dir=self.target_dir, state_dir=missing_state)

        # Invalid schemaVersion
        invalid_manifest = self.state_dir / "runtime.json"
        invalid_manifest.write_text(json.dumps({"schemaVersion": 2, "workspace": "myws"}))
        with self.assertRaises(ValueError):
            supervisor.install_workspace(
                "myws",
                target_dir=self.target_dir,
                state_dir=self.state_dir,
                helper_path=self.launcher,
            )

    def test_install_workspace_is_idempotent(self):
        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch("subprocess.run"):
            supervisor.install_workspace(
                "myws",
                target_dir=self.target_dir,
                state_dir=self.state_dir,
                helper_path=self.launcher,
            )
            supervisor.install_workspace(
                "myws",
                target_dir=self.target_dir,
                state_dir=self.state_dir,
                helper_path=self.launcher,
            )

        self.assertTrue((self.target_dir / "asb-myws.target").is_file())

    def test_start_workspace(self):
        with mock.patch("subprocess.run") as mock_run:
            supervisor.start_workspace("myws")
            mock_run.assert_called_once_with(
                ["systemctl", "--user", "start", "asb-myws.target"],
                check=True,
            )

    def test_stop_workspace(self):
        with mock.patch("subprocess.run") as mock_run:
            supervisor.stop_workspace("myws")
            mock_run.assert_called_once_with(
                ["systemctl", "--user", "stop", "asb-myws.target"],
                check=True,
            )

    def test_remove_workspace_units(self):
        # Create dummy units
        proxy_unit = self.target_dir / "asb-myws-proxy.service"
        agent_unit = self.target_dir / "asb-myws-agent.service"
        target_unit = self.target_dir / "asb-myws.target"
        proxy_unit.write_text("proxy")
        agent_unit.write_text("agent")
        target_unit.write_text("target")

        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch("subprocess.run") as mock_run:
            supervisor.remove_workspace_units("myws", target_dir=self.target_dir)

        self.assertFalse(proxy_unit.exists())
        self.assertFalse(agent_unit.exists())
        self.assertFalse(target_unit.exists())
        mock_run.assert_any_call(["systemctl", "--user", "daemon-reload"], check=True)

    def test_remove_workspace_units_does_not_touch_sibling_with_shared_prefix(self):
        """I1: `remove_workspace_units` removia unidades por glob
        `asb-{ws}-*.service`, que casa tambem workspaces irmaos cujo nome
        comeca com o mesmo prefixo sem delimitador (`asb-demo-` casa
        `asb-demo-2-agent.service`). As unidades devem ser identificadas
        EXCLUSIVAMENTE pelos nomes gravados no runtime.json do proprio
        workspace, nunca por prefixo."""
        ws_a = "demo"
        ws_b = "demo-2"

        state_a = self.fake_home / ".local" / "state" / "agent-sandbox" / ws_a
        state_a.mkdir(parents=True)
        (state_a / "runtime.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "workspace": ws_a,
                "containers": {
                    "proxy": {"name": f"asb-{ws_a}-proxy", "id": "p1",
                              "unit": f"asb-{ws_a}-proxy.service"},
                    "agent": {"name": f"asb-{ws_a}-agent", "id": "a1",
                              "unit": f"asb-{ws_a}-agent.service"},
                },
            })
        )

        # Unidades reais dos dois workspaces no mesmo diretorio de unidades.
        units = {
            f"asb-{ws_a}-proxy.service": self.target_dir / f"asb-{ws_a}-proxy.service",
            f"asb-{ws_a}-agent.service": self.target_dir / f"asb-{ws_a}-agent.service",
            f"asb-{ws_a}.target": self.target_dir / f"asb-{ws_a}.target",
            f"asb-{ws_b}-proxy.service": self.target_dir / f"asb-{ws_b}-proxy.service",
            f"asb-{ws_b}-agent.service": self.target_dir / f"asb-{ws_b}-agent.service",
            f"asb-{ws_b}.target": self.target_dir / f"asb-{ws_b}.target",
        }
        for path in units.values():
            path.write_text("unit")

        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch("subprocess.run"):
            supervisor.remove_workspace_units(
                ws_a, target_dir=self.target_dir, state_dir=state_a)

        # Unidades do workspace A foram removidas.
        self.assertFalse(units[f"asb-{ws_a}-proxy.service"].exists())
        self.assertFalse(units[f"asb-{ws_a}-agent.service"].exists())
        self.assertFalse(units[f"asb-{ws_a}.target"].exists())

        # Unidades do workspace irmao B (prefixado por A) permanecem intactas.
        self.assertTrue(units[f"asb-{ws_b}-proxy.service"].exists())
        self.assertTrue(units[f"asb-{ws_b}-agent.service"].exists())
        self.assertTrue(units[f"asb-{ws_b}.target"].exists())

    def test_remove_workspace_units_without_manifest_removes_only_target(self):
        """Sem manifesto legivel, nao ha como saber quais nomes de servico
        pertencem a este workspace: nada e removido por adivinhacao/glob,
        apenas a unidade .target cujo nome e derivado do proprio ws."""
        target_unit = self.target_dir / "asb-orphan.target"
        stray_service = self.target_dir / "asb-orphan-2-agent.service"
        target_unit.write_text("target")
        stray_service.write_text("service")

        with mock.patch.object(Path, "home", return_value=self.fake_home), \
             mock.patch("subprocess.run"):
            supervisor.remove_workspace_units(
                "orphan", target_dir=self.target_dir,
                state_dir=self.tmp_path / "no-such-state")

        self.assertFalse(target_unit.exists())
        self.assertTrue(stray_service.exists())


class TestNetworkGateUnits(unittest.TestCase):
    """Emenda A §3/§4: toda unidade de container espera a conectividade real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.runtime_dir = self.root / "runtime" / "rev1"
        self.runtime_dir.mkdir(parents=True)
        self.launcher = self.runtime_dir / "launcher.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.state_dir = self.root / "state" / "ws"
        self.state_dir.mkdir(parents=True)
        self.manifest = self.state_dir / "runtime.json"

    def _unit_text(self, role: str, **kwargs) -> str:
        return supervisor.render_unit(supervisor.ContainerUnit(
            name=f"asb-ws-{role}",
            container_id="c1",
            role=role,
            unit_name=f"asb-ws-{role}.service",
            target_name="asb-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
            **kwargs,
        ))

    def test_render_network_unit_is_an_infinite_oneshot_gate(self):
        gate = self.runtime_dir / "network_gate.py"
        text = supervisor.render_network_unit(gate)
        for line in ("Type=oneshot", "RemainAfterExit=yes",
                     "TimeoutStartSec=infinity", "Restart=on-failure"):
            self.assertIn(line + "\n", text)
        self.assertIn(f"ExecStart={gate}\n", text)
        self.assertNotIn("podman", text)
        self.assertNotIn("unshare", text)
        self.assertNotIn("Environment=", text)
        self.assertNotIn("[Install]", text)

    def test_render_network_unit_pins_the_gate_target_when_given(self):
        text = supervisor.render_network_unit(
            self.runtime_dir / "network_gate.py", target="127.0.0.1:18080")
        self.assertIn("Environment=ASB_NETWORK_GATE_TARGET=127.0.0.1:18080\n", text)

    def test_every_container_role_requires_and_orders_after_the_gate(self):
        for role in ("proxy", "agent", "forwarder", "docker", "svc-db"):
            with self.subTest(role=role):
                text = self._unit_text(role)
                self.assertIn("Requires=asb-network.service\n", text)
                after = next(l for l in text.splitlines() if l.startswith("After="))
                self.assertIn("asb-network.service", after.split("=", 1)[1].split())

    def test_network_unit_none_omits_the_dependency(self):
        text = self._unit_text("proxy", network_unit=None)
        self.assertNotIn("Requires=", text)
        self.assertNotIn("asb-network.service", text)

    def test_network_unit_name_honors_the_isolation_environment(self):
        with mock.patch.dict(os.environ, {"ASB_NETWORK_UNIT": "asb-test-x-network.service"}):
            self.assertEqual(supervisor.network_unit_name(), "asb-test-x-network.service")
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("ASB_NETWORK_UNIT", None)
            self.assertEqual(supervisor.network_unit_name(), "asb-network.service")

    def test_install_workspace_writes_the_shared_gate_and_wires_every_unit(self):
        unit_dir = self.root / "units"
        self.manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "workspace": "ws",
            "containers": {
                "proxy": {"name": "asb-ws-proxy", "id": "p1"},
                "agent": {"name": "asb-ws-agent", "id": "a1"},
                "forwarder": {"name": "asb-ws-fwd", "id": "f1", "unit": "asb-ws-fwd.service"},
            },
        }))
        with mock.patch.dict(os.environ, {"ASB_NETWORK_GATE_TARGET": "127.0.0.1:18080"}), \
             mock.patch("asb.supervisor.subprocess.run") as run:
            os.environ.pop("ASB_NETWORK_UNIT", None)
            written = supervisor.install_workspace(
                "ws", target_dir=unit_dir, state_dir=self.state_dir, helper_path=self.launcher)

        gate = unit_dir / "asb-network.service"
        self.assertTrue(gate.is_file())
        gate_text = gate.read_text(encoding="utf-8")
        self.assertIn(f"ExecStart={self.runtime_dir / 'network_gate.py'}\n", gate_text)
        self.assertIn("Environment=ASB_NETWORK_GATE_TARGET=127.0.0.1:18080\n", gate_text)
        # Compartilhada: nunca devolvida para o rollback transacional apagar.
        self.assertNotIn(gate, written)
        for unit in ("asb-ws-proxy.service", "asb-ws-agent.service", "asb-ws-fwd.service"):
            self.assertIn("Requires=asb-network.service\n",
                          (unit_dir / unit).read_text(encoding="utf-8"))
        run.assert_called_with(["systemctl", "--user", "daemon-reload"], check=True)

    def test_install_network_unit_writes_file_directly(self):
        unit_dir = self.root / "direct_units"
        gate = self.runtime_dir / "network_gate.py"
        path = supervisor.install_network_unit(
            target_dir=unit_dir, gate_path=gate, target="127.0.0.1:18080")
        self.assertEqual(path, unit_dir / "asb-network.service")
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn(f"ExecStart={gate}\n", text)
        self.assertIn("Environment=ASB_NETWORK_GATE_TARGET=127.0.0.1:18080\n", text)


class TestKeyringUnit(unittest.TestCase):
    """Emenda A §5: o keyring e uma unidade systemd com sonda de prontidao."""

    def test_render_keyring_unit_runs_readiness_and_ignores_the_network_gate(self):
        runtime_dir = Path("/opt/asb/runtime/rev1")
        text = supervisor.render_keyring_unit("asb-keyring", runtime_dir)
        self.assertIn(
            "ExecStart=/opt/asb/runtime/rev1/launcher.sh start --attach --sig-proxy=false asb-keyring\n", text)
        self.assertIn(
            "ExecStartPost=/opt/asb/runtime/rev1/runtime_check.py --role keyring --container asb-keyring\n", text)
        self.assertIn("WantedBy=default.target\n", text)
        self.assertNotIn("asb-network", text)
        self.assertNotIn("Requires=", text)

    def test_install_keyring_unit_writes_the_unit_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp) / "units"
            with mock.patch("asb.supervisor.subprocess.run") as run:
                path = supervisor.install_keyring_unit(
                    "asb-keyring", Path("/opt/rt"), target_dir=unit_dir)
            self.assertEqual(path, unit_dir / "asb-keyring.service")
            self.assertIn("--role keyring", path.read_text(encoding="utf-8"))
            run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)

    def test_keyring_names_honor_the_isolation_environment(self):
        with mock.patch.dict(os.environ, {"ASB_KEYRING_CONTAINER": "asb-test-k-keyring"}):
            self.assertEqual(supervisor.keyring_container_name(), "asb-test-k-keyring")
            self.assertEqual(supervisor.keyring_unit_name(), "asb-test-k-keyring.service")

    def test_install_workspace_points_the_agent_at_the_keyring_unit_in_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)
            launcher = runtime_dir / "launcher.sh"
            launcher.write_text("#!/bin/sh\n")
            state_dir = root / "state" / "ws"
            state_dir.mkdir(parents=True)
            (state_dir / "runtime.json").write_text(json.dumps({
                "schemaVersion": 1, "workspace": "ws",
                "containers": {"agent": {"name": "asb-ws-agent", "id": "a1"}},
            }))
            unit_dir = root / "units"
            with mock.patch.dict(os.environ, {"ASB_KEYRING_CONTAINER": "asb-test-k-keyring"}), \
                 mock.patch("asb.supervisor.subprocess.run"):
                supervisor.install_workspace(
                    "ws", target_dir=unit_dir, state_dir=state_dir, helper_path=launcher)
            agent_text = (unit_dir / "asb-ws-agent.service").read_text(encoding="utf-8")
            self.assertIn("asb-test-k-keyring.service", agent_text)
            self.assertNotIn(" asb-keyring.service", agent_text)


if __name__ == "__main__":
    unittest.main()
