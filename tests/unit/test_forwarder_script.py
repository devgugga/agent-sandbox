"""tests/unit/test_forwarder_script.py — Unit tests for image/forwarder.sh behavior."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class TestForwarderScriptValidation(unittest.TestCase):
    """Tests input validation of image/forwarder.sh."""

    @classmethod
    def setUpClass(cls):
        cls.script_path = (
            Path(__file__).resolve().parents[2] / "image" / "forwarder.sh"
        )
        if not cls.script_path.is_file():
            raise unittest.SkipTest(f"{cls.script_path} does not exist")

    def test_requires_at_least_one_port(self):
        res = subprocess.run(
            ["bash", str(self.script_path)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("at least one port", res.stderr)

    def test_rejects_invalid_port_values(self):
        invalid_cases = ["0", "65536", "70000", "-1", "abc", "80a", "080", ""]
        for port in invalid_cases:
            with self.subTest(port=port):
                res = subprocess.run(
                    ["bash", str(self.script_path), port],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("invalid port", res.stderr)

    def test_socat_failure_or_missing_fails_immediately(self):
        # PATH pointing only to bash directory so socat is missing
        bash_bin = shutil.which("bash") or "/bin/bash"
        bash_dir = str(Path(bash_bin).parent)
        env = dict(os.environ)
        env["PATH"] = bash_dir
        res = subprocess.run(
            [bash_bin, str(self.script_path), "80", "5432"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)


class TestForwarderProcessLifecycle(unittest.TestCase):
    """Tests process supervision semantics: fail-fast on child death and SIGTERM graceful stop."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="asb-test-fwd-"))
        # Create a mock socat script that sleeps until signaled or killed
        self.mock_socat = self.tmp_dir / "socat"
        self.mock_socat.write_text(
            "#!/bin/sh\n"
            "# Simulate socat: record invocation and sleep\n"
            "echo \"$@\" >> \"$MOCK_LOG\"\n"
            "trap 'exit 0' TERM INT\n"
            "while :; do sleep 0.2; done\n",
            encoding="utf-8",
        )
        self.mock_socat.chmod(0o755)
        self.script_path = (
            Path(__file__).resolve().parents[2] / "image" / "forwarder.sh"
        )
        self.log_file = self.tmp_dir / "socat.log"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run_forwarder(self, *ports: str) -> subprocess.Popen:
        env = dict(os.environ)
        env["PATH"] = f"{self.tmp_dir}:{env.get('PATH', '')}"
        env["MOCK_LOG"] = str(self.log_file)
        return subprocess.Popen(
            ["bash", str(self.script_path), *ports],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_spawns_socat_per_declared_port_with_strict_destination(self):
        proc = self._run_forwarder("80", "5432")
        try:
            deadline = time.monotonic() + 5.0
            content = ""
            while time.monotonic() < deadline:
                if self.log_file.exists():
                    content = self.log_file.read_text(encoding="utf-8")
                    if "TCP-LISTEN:80" in content and "TCP-LISTEN:5432" in content:
                        break
                time.sleep(0.1)
            self.assertIn("TCP-LISTEN:80,fork,reuseaddr TCP:host.containers.internal:80", content)
            self.assertIn("TCP-LISTEN:5432,fork,reuseaddr TCP:host.containers.internal:5432", content)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_child_death_triggers_fail_fast_and_kills_sibling(self):
        proc = self._run_forwarder("80", "5432")
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self.log_file.exists() and len(self.log_file.read_text().splitlines()) >= 2:
                    break
                time.sleep(0.1)

            # Find children of the forwarder script
            res = subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True)
            children = [int(p) for p in res.stdout.strip().split() if p.isdigit()]
            self.assertGreaterEqual(len(children), 2, "Expected at least 2 child processes")

            # Kill the first child (simulating socat failure)
            victim = children[0]
            sibling = children[1]
            os.kill(victim, 9)

            # Forwarder must exit quickly with non-zero exit code
            retcode = proc.wait(timeout=5.0)
            self.assertNotEqual(retcode, 0, "Forwarder must exit non-zero when child dies")

            # Sibling must have been stopped
            time.sleep(0.2)
            sibling_alive = True
            try:
                os.kill(sibling, 0)
            except OSError:
                sibling_alive = False
            self.assertFalse(sibling_alive, "Sibling process must be killed when one child fails")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_sigterm_stops_children_and_exits_zero(self):
        proc = self._run_forwarder("80", "5432")
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self.log_file.exists() and len(self.log_file.read_text().splitlines()) >= 2:
                    break
                time.sleep(0.1)

            res = subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True)
            children = [int(p) for p in res.stdout.strip().split() if p.isdigit()]
            self.assertGreaterEqual(len(children), 2)

            # Send SIGTERM to forwarder
            proc.terminate()
            retcode = proc.wait(timeout=5.0)
            self.assertEqual(retcode, 0, "Forwarder must exit 0 on graceful SIGTERM")

            # All children should be dead
            time.sleep(0.2)
            for c in children:
                alive = True
                try:
                    os.kill(c, 0)
                except OSError:
                    alive = False
                self.assertFalse(alive, f"Child {c} should have been stopped")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
