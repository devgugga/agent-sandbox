"""tests/integration/test_supervisor_pilot.py — Empirical supervision pilot test.

Validates systemd Type=exec supervision over persistent Podman containers:
1. Supervision recovery on failure (SIGKILL), preserving container ID, port, and writable data.
2. Supervision recovery on unexpected zero exit (exit 0).
3. ExecStartPost failure handling and ExecStopPost cleanup.
4. Reconnection to an already running container using a runtime launcher helper.
5. Behavior and self-healing of literal unit when reconnecting to an already running container.
6. Strict isolation guards refusing foreign resource names and paths.
"""
from __future__ import annotations

import subprocess
import time
import unittest
from pathlib import Path

from tests.integration.sandbox_fixture import IsolationError, SandboxFixture


class TestSupervisorPilot(unittest.TestCase):
    """Empirical integration test suite for systemd rootless supervision."""

    def test_supervision_restart_and_identity_preservation(self) -> None:
        """Proves systemd Type=exec restarts container on failure, preserving identity and data."""
        with SandboxFixture("supervision") as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15), "Sandbox unit should become active")

            original = sandbox.inspect_identity()
            self.assertTrue(original[0], "Container ID must be non-empty")
            self.assertGreater(original[1], 0, "Host port must be valid")

            sandbox.write_sentinel("proof-sentinel-data")
            self.assertTrue(sandbox.sentinel_exists(), "Sentinel file must exist before failure")

            # Simulate container crash (SIGKILL)
            sandbox.fail_container()

            # Systemd must detect exit, schedule restart job (RestartSec=5s), and restart container
            self.assertTrue(
                sandbox.wait_active(timeout=30),
                "Supervised unit must recover and become active after failure",
            )
            self.assertEqual(
                sandbox.inspect_identity(),
                original,
                "Container ID and host port mapping must be preserved after restart",
            )
            self.assertTrue(
                sandbox.sentinel_exists(),
                "Sentinel file in writable container layer must persist across restarts",
            )

            # Clean intentional stop
            sandbox.stop()
            self.assertFalse(
                sandbox.wait_active(timeout=7),
                "Unit must not be active after intentional stop",
            )
            sandbox.assert_no_orphans()

    def test_supervision_unexpected_zero_exit(self) -> None:
        """Proves systemd Restart=always restarts container even when exiting cleanly (status 0)."""
        with SandboxFixture("zeroexit") as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15))

            original = sandbox.inspect_identity()

            # Trigger clean exit (code 0)
            sandbox.exit_zero()

            # Systemd must restart the service
            self.assertTrue(
                sandbox.wait_active(timeout=30),
                "Supervised unit must restart container even after status 0 exit",
            )
            self.assertEqual(sandbox.inspect_identity(), original)

            sandbox.stop()
            self.assertFalse(sandbox.wait_active(timeout=7))
            sandbox.assert_no_orphans()

    def test_supervision_exec_start_post_failure_cleans_up_via_stop_post(self) -> None:
        """Proves ExecStopPost stops container when ExecStartPost fails during startup."""
        with SandboxFixture(
            "execpost",
            exec_start_post="/usr/bin/false",
            restart="no",
        ) as sandbox:
            # Starting the unit must fail because ExecStartPost returned non-zero
            with self.assertRaises(subprocess.CalledProcessError):
                sandbox.start()

            self.assertFalse(sandbox.wait_active(timeout=3))

            # ExecStopPost must have executed, ensuring container is not left running
            self.assertFalse(
                sandbox.is_container_running(),
                "Container must be stopped by ExecStopPost on ExecStartPost failure",
            )
            sandbox.assert_no_orphans()

    def test_supervision_reconnect_to_running_container_with_launcher(self) -> None:
        """Proves runtime launcher helper seamlessly attaches to an already running container."""
        with SandboxFixture("reconnhelp", use_launcher=True, auto_setup=False) as sandbox:
            sandbox.setup_container()
            # Start container directly via podman
            subprocess.run(
                [sandbox._podman_bin, "start", sandbox.container],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(sandbox.is_container_running())
            original = sandbox.inspect_identity()

            # Install unit with launcher helper and start
            sandbox.install_unit()
            sandbox.start()

            self.assertTrue(
                sandbox.wait_active(timeout=15),
                "Unit with launcher helper must attach to running container and report active",
            )
            self.assertEqual(sandbox.inspect_identity(), original)

            sandbox.stop()
            self.assertFalse(sandbox.wait_active(timeout=7))
            sandbox.assert_no_orphans()

    def test_supervision_literal_reconnect_bounces_via_stop_post_and_restarts(self) -> None:
        """Proves literal unit behavior: podman start --attach on running container bounces.

        Empirical finding: in Podman 6.1 rootless, literal 'podman start --attach' cannot
        attach to an already running container (exits with status 125).
        ExecStopPost stops the container, and systemd's Restart=always schedules a restart
        (RestartSec=5s), which then successfully starts the now-stopped container.
        This proves why the brief requires a launcher helper for seamless adoption in I3.
        """
        with SandboxFixture("reconnlit", auto_setup=False) as sandbox:
            sandbox.setup_container()
            subprocess.run(
                [sandbox._podman_bin, "start", sandbox.container],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(sandbox.is_container_running())
            original = sandbox.inspect_identity()

            sandbox.install_unit()
            sandbox.start()

            # Wait briefly for initial exit 125 and ExecStopPost to execute
            time.sleep(1.0)
            # Systemd schedules restart and recovers after RestartSec (5s)
            self.assertTrue(
                sandbox.wait_active(timeout=30),
                "Systemd must self-heal via Restart=always after initial exit 125",
            )
            self.assertEqual(sandbox.inspect_identity(), original)

            sandbox.stop()
            self.assertFalse(sandbox.wait_active(timeout=7))
            sandbox.assert_no_orphans()

    def test_isolation_guards_refuse_foreign_names_and_paths(self) -> None:
        """Proves SandboxFixture refuses foreign resources, production names, and external paths."""
        with SandboxFixture("guards") as sandbox:
            # Must reject names outside the specific fixture prefix
            with self.assertRaises(IsolationError):
                sandbox.register_container("asb-keyring")

            with self.assertRaises(IsolationError):
                sandbox.register_container("asb-test-foreign-uuid-pilot")

            with self.assertRaises(IsolationError):
                sandbox.register_volume("asb-toolcache")

            with self.assertRaises(IsolationError):
                sandbox.register_network("asb-default-net")

            # Must reject paths outside state_root
            with self.assertRaises(IsolationError):
                sandbox._validate_path(Path("/tmp/arbitrary-file"))

            with self.assertRaises(IsolationError):
                sandbox._validate_path(Path.home() / ".config" / "agent-sandbox")


if __name__ == "__main__":
    unittest.main()
