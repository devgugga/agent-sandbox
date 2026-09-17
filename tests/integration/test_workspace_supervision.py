"""tests/integration/test_workspace_supervision.py — Integration tests for managed lifecycle.

Proves the complete managed lifecycle under systemd supervision:
1. `asb-agent up` creates containers with `--restart=no` and installs systemd units.
2. Systemd target and units become active, and SSH handshake succeeds.
3. Sentinel file is written to container writable layer.
4. `asb-agent suspend` disables/stops target and ensures containers are stopped.
5. `asb-agent resume` re-enables target, resets failed states, starts target, and recovers state.
6. Container ID, published SSH port, and sentinel file persist across suspend/resume.
7. `asb-agent down` stops/removes systemd units, sweeping workspace containers/networks without
   touching global auth or the shared keyring singleton.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import readiness  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


class TestWorkspaceSupervision(unittest.TestCase):
    """End-to-end integration tests for systemd-managed workspace lifecycle."""

    def test_full_managed_lifecycle_under_systemd(self) -> None:
        """Proves complete managed lifecycle: up -> SSH -> sentinel -> suspend -> resume -> down."""
        with SandboxFixture("superv", auto_setup=False) as sandbox:
            # 1. Initialize git repo in worktree directory with an initial commit
            subprocess.run(
                ["git", "-C", str(sandbox.worktree_dir), "config", "user.name", "Test User"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(sandbox.worktree_dir), "config", "user.email", "test@example.com"],
                check=True,
                capture_output=True,
            )
            readme = sandbox.worktree_dir / "README.md"
            readme.write_text("# Test Workspace Supervision\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(sandbox.worktree_dir), "add", "README.md"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(sandbox.worktree_dir), "commit", "-m", "initial commit"],
                check=True,
                capture_output=True,
            )

            # Register workspace resources for strict fixture containment and isolation
            agent_name = f"asb-{sandbox.workspace}-agent"
            proxy_name = f"asb-{sandbox.workspace}-proxy"
            net_internal = f"asb-{sandbox.workspace}"
            net_out = f"asb-{sandbox.workspace}-out"
            target_unit = f"asb-{sandbox.workspace}.target"
            agent_unit = f"asb-{sandbox.workspace}-agent.service"
            proxy_unit = f"asb-{sandbox.workspace}-proxy.service"

            sandbox.register_container(agent_name)
            sandbox.register_container(proxy_name)
            sandbox.register_network(net_internal)
            sandbox.register_network(net_out)
            sandbox.register_unit(target_unit)
            sandbox.register_unit(agent_unit)
            sandbox.register_unit(proxy_unit)

            home = Path(os.path.expanduser("~"))
            mount_cleanup_dir = home / "asb-agent" / sandbox.worktree_dir.name / sandbox.workspace
            self.addCleanup(lambda: shutil.rmtree(mount_cleanup_dir, ignore_errors=True))

            # 2. Execute `asb-agent up`
            res_up = sandbox.cli(
                "up",
                "--workspace", sandbox.workspace,
                "--repo", str(sandbox.worktree_dir),
            )
            self.assertEqual(
                res_up.returncode,
                0,
                f"asb-agent up failed (code {res_up.returncode}):\nSTDOUT: {res_up.stdout}\nSTDERR: {res_up.stderr}",
            )

            # Assert single-line JSON on stdout
            stdout_lines = [l.strip() for l in res_up.stdout.strip().splitlines() if l.strip()]
            self.assertEqual(
                len(stdout_lines),
                1,
                f"asb-agent up stdout must be exactly one JSON line, got: {res_up.stdout!r}",
            )
            info = json.loads(stdout_lines[0])
            self.assertEqual(info.get("workspace"), sandbox.workspace)
            self.assertIn("port", info)
            ssh_port = int(info["port"])
            self.assertGreater(ssh_port, 0)

            # 3. Verify SSH handshake
            ssh_probe = readiness.wait_until(
                lambda to: readiness.probe_ssh(port=ssh_port, key=sandbox.ssh_key, timeout=to),
                timeout=20.0,
            )
            self.assertEqual(
                ssh_probe.state,
                "healthy",
                f"SSH probe failed on port {ssh_port}: {ssh_probe.code} -> {ssh_probe.remediation}",
            )

            # 4. Verify systemd target is active
            res_target = subprocess.run(
                ["systemctl", "--user", "is-active", target_unit],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_target.stdout.strip(), "active")

            # 5. Record container ID and write sentinel file
            res_cid = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            cid_before = res_cid.stdout.strip()
            self.assertTrue(cid_before)

            sentinel_content = "supervision-sentinel-verified-data"
            subprocess.run(
                ["podman", "exec", agent_name, "sh", "-c", f"echo '{sentinel_content}' > /sentinel.txt"],
                capture_output=True,
                text=True,
                check=True,
            )

            # 6. Suspend workspace
            res_susp = sandbox.cli("suspend", "--workspace", sandbox.workspace)
            self.assertEqual(
                res_susp.returncode,
                0,
                f"asb-agent suspend failed (code {res_susp.returncode}): {res_susp.stderr}",
            )

            # Verify target is stopped / inactive
            res_target_susp = subprocess.run(
                ["systemctl", "--user", "is-active", target_unit],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res_target_susp.stdout.strip(), "active")

            # Verify containers are stopped
            res_agent_ps = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{agent_name}$", "--filter", "status=running", "--quiet"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_agent_ps.stdout.strip(), "", "Agent container should be stopped after suspend")

            res_proxy_ps = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{proxy_name}$", "--filter", "status=running", "--quiet"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_proxy_ps.stdout.strip(), "", "Proxy container should be stopped after suspend")

            # 7. Resume workspace
            res_res = sandbox.cli("resume", "--workspace", sandbox.workspace)
            self.assertEqual(
                res_res.returncode,
                0,
                f"asb-agent resume failed (code {res_res.returncode}):\nSTDOUT: {res_res.stdout}\nSTDERR: {res_res.stderr}",
            )

            # Assert single-line JSON on stdout from resume
            res_lines = [l.strip() for l in res_res.stdout.strip().splitlines() if l.strip()]
            self.assertEqual(
                len(res_lines),
                1,
                f"asb-agent resume stdout must be exactly one JSON line, got: {res_res.stdout!r}",
            )
            resume_info = json.loads(res_lines[0])
            self.assertEqual(int(resume_info["port"]), ssh_port, "SSH port must be preserved across resume")

            # Verify target is active again
            res_target_res = subprocess.run(
                ["systemctl", "--user", "is-active", target_unit],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_target_res.stdout.strip(), "active")

            # Verify container ID and sentinel data preserved
            res_cid_after = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                res_cid_after.stdout.strip(),
                cid_before,
                "Container ID must be identical before and after suspend/resume",
            )

            res_sentinel = subprocess.run(
                ["podman", "exec", agent_name, "cat", "/sentinel.txt"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_sentinel.stdout.strip(), sentinel_content)

            # 8. Down workspace
            res_down = sandbox.cli("down", "--workspace", sandbox.workspace)
            self.assertEqual(
                res_down.returncode,
                0,
                f"asb-agent down failed (code {res_down.returncode}): {res_down.stderr}",
            )

            # Verify unit files removed
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            for u in (target_unit, agent_unit, proxy_unit):
                self.assertFalse((unit_dir / u).exists(), f"Unit file {u} should be removed by down")

            # Verify containers removed
            for c in (agent_name, proxy_name):
                c_exists = subprocess.run(
                    ["podman", "container", "exists", c],
                    capture_output=True,
                ).returncode == 0
                self.assertFalse(c_exists, f"Container {c} should be removed by down")

            # Verify networks removed
            for net in (net_internal, net_out):
                net_exists = subprocess.run(
                    ["podman", "network", "exists", net],
                    capture_output=True,
                ).returncode == 0
                self.assertFalse(net_exists, f"Network {net} should be removed by down")

            # Verify global keyring singleton was not removed or harmed
            self.assertEqual(
                readiness.probe_keyring().state,
                "healthy",
                "Shared keyring singleton must remain healthy after down",
            )


if __name__ == "__main__":
    unittest.main()
