"""tests/integration/test_forwarder.py — Integration tests for port forwarder fail-fast and low ports."""
from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from tests.integration.sandbox_fixture import SandboxFixture


class TestForwarderIntegration(unittest.TestCase):
    """Empirical integration tests for asb-forwarder and unprivileged low ports."""

    def test_forwarder_fail_fast_and_restart(self) -> None:
        """Proves killing one listener causes forwarder failure, supervisor restart, and restoration."""
        with SandboxFixture("fwdfail", forwarder_ports=[80, 5432]) as sandbox:
            self.assertTrue(
                sandbox.wait_forwarder_listener(80, timeout=15),
                "Listener 80 should be active on start",
            )
            self.assertTrue(
                sandbox.wait_forwarder_listener(5432, timeout=15),
                "Listener 5432 should be active on start",
            )

            before = sandbox.forwarder_restart_count()

            # Kill listener 80 inside the container
            sandbox.fail_forwarder_listener(80)

            # Forwarder must fail-fast, trigger supervisor restart, and recover both listeners
            self.assertTrue(
                sandbox.wait_forwarder_listener(80, timeout=30),
                "Listener 80 must recover after supervisor restart",
            )
            self.assertTrue(
                sandbox.wait_forwarder_listener(5432, timeout=30),
                "Listener 5432 must be active after restart",
            )
            self.assertGreater(
                sandbox.forwarder_restart_count(),
                before,
                "Forwarder restart count must have increased",
            )

    def test_forwarder_old_script_masks_child_failure(self) -> None:
        """Proves the old un-supervised script masks child process failure."""
        with SandboxFixture("fwdold", auto_setup=True) as sandbox:
            sandbox.setup_forwarder([80, 5432], use_old_script=True)
            self.assertTrue(sandbox.wait_forwarder_listener(80, timeout=15))
            self.assertTrue(sandbox.wait_forwarder_listener(5432, timeout=15))

            before = sandbox.forwarder_restart_count()

            sandbox.fail_forwarder_listener(80)
            time.sleep(2.0)

            # Old script does not fail-fast: port 80 stays down, port 5432 stays up, no restart
            self.assertFalse(
                sandbox.wait_forwarder_listener(80, timeout=0.5),
                "Listener 80 should stay down in the old script",
            )
            self.assertTrue(
                sandbox.wait_forwarder_listener(5432, timeout=0.5),
                "Listener 5432 should remain alive in the old script",
            )
            self.assertEqual(
                sandbox.forwarder_restart_count(),
                before,
                "Restart count must not increment with the old script",
            )

    def test_forwarder_graceful_shutdown_on_term(self) -> None:
        """Proves forwarder handles SIGTERM cleanly and exits status 0."""
        with SandboxFixture("fwdterm", forwarder_ports=[80, 5432]) as sandbox:
            self.assertTrue(sandbox.wait_forwarder_listener(80, timeout=15))
            self.assertTrue(sandbox.wait_forwarder_listener(5432, timeout=15))

            # Stop container with SIGTERM
            res = subprocess.run(
                ["podman", "stop", "-t", "10", sandbox.forwarder_container],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)

            # Inspect exit code of container: trap ensures clean exit 0
            res_code = subprocess.run(
                [
                    "podman",
                    "inspect",
                    sandbox.forwarder_container,
                    "--format",
                    "{{.State.ExitCode}}",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_code.stdout.strip(), "0")

    def test_forwarder_bind_error_and_validation(self) -> None:
        """Proves initial bind errors or invalid port arguments fail immediately."""
        # 1. Invalid port in script fails immediately
        res_inv = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "agent-sandbox-proxy:latest",
                "/usr/local/bin/asb-forwarder",
                "70000",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_inv.returncode, 0)
        self.assertIn("invalid port", res_inv.stderr)

        # 2. No arguments fails immediately
        res_no_args = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "agent-sandbox-proxy:latest",
                "/usr/local/bin/asb-forwarder",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_no_args.returncode, 0)
        self.assertIn("at least one port", res_no_args.stderr)

        # 3. Port collision (port already occupied inside container)
        with SandboxFixture("fwdcoll", auto_setup=False) as sandbox:
            c_name = sandbox.register_container(f"{sandbox._prefix}-collision")
            # Start container running a conflicting listener on port 80 and then invoking forwarder
            run_cmd = [
                "podman",
                "run",
                "--rm",
                "--name",
                c_name,
                "--sysctl",
                "net.ipv4.ip_unprivileged_port_start=0",
                "--user",
                "900",
                "agent-sandbox-proxy:latest",
                "bash",
                "-c",
                "socat TCP-LISTEN:80,reuseaddr SYSTEM:'echo busy' & P1=$!; sleep 0.5; /usr/local/bin/asb-forwarder 80 5432; RC=$?; kill $P1 2>/dev/null || true; exit $RC",
            ]
            res_coll = subprocess.run(run_cmd, capture_output=True, text=True)
            self.assertNotEqual(res_coll.returncode, 0)

    def test_forwarder_undeclared_ports_remain_closed(self) -> None:
        """Proves undeclared ports remain closed and forwarder is not a general proxy."""
        with SandboxFixture("fwdclosed", forwarder_ports=[80, 5432]) as sandbox:
            self.assertTrue(sandbox.wait_forwarder_listener(80, timeout=15))
            self.assertTrue(sandbox.wait_forwarder_listener(5432, timeout=15))

            # Undeclared port 8080 must not be listening
            self.assertFalse(
                sandbox.wait_forwarder_listener(8080, timeout=1.0),
                "Undeclared port 8080 must not be listening",
            )

            # Check listening sockets inside container via ss
            res = subprocess.run(
                ["podman", "exec", sandbox.forwarder_container, "ss", "-tlnH"],
                capture_output=True,
                text=True,
            )
            for line in res.stdout.strip().splitlines():
                if not line.strip():
                    continue
                has_declared = (
                    ":80 " in line
                    or ":5432 " in line
                    or line.endswith(":80")
                    or line.endswith(":5432")
                )
                self.assertTrue(
                    has_declared,
                    f"Unexpected open listening port found: {line}",
                )

    def test_proxy_image_contains_bash_and_executable_forwarder(self) -> None:
        """Proves the proxy image explicitly contains bash and the forwarder executable."""
        res_bash = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "agent-sandbox-proxy:latest",
                "bash",
                "--version",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_bash.returncode, 0)
        self.assertIn("GNU bash", res_bash.stdout)

        res_exec = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "agent-sandbox-proxy:latest",
                "test",
                "-x",
                "/usr/local/bin/asb-forwarder",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_exec.returncode, 0)


if __name__ == "__main__":
    unittest.main()
