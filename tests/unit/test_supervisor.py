"""Unit tests for cli/asb/supervisor.py — systemd supervision and unit generation."""
from __future__ import annotations

import json
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
            unit_file.write_text(text, encoding="utf-8")
            res = subprocess.run(
                ["systemd-analyze", "verify", str(unit_file)],
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


if __name__ == "__main__":
    unittest.main()
