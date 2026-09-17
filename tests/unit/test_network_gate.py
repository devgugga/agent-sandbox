"""Unit tests for cli/asb/network_gate.py — espera unica por conectividade real (Emenda A §4)."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import install, network_gate  # noqa: E402
from asb.readiness import ProbeResult  # noqa: E402

NON_HEALTHY_CODES = (
    "dns_failed", "timeout", "no_route", "tls_failed",
    "connection_refused", "unexpected_error",
)


def _result(state: str, code: str) -> ProbeResult:
    return ProbeResult("host", state, code, 0, "")


class _FakeClock:
    """Cada leitura avanca `step` segundos."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class TestWaitForNetwork(unittest.TestCase):
    def _run(self, results, *, step: float = 0.0):
        pending = list(results)
        calls: list[dict] = []
        sleeps: list[float] = []
        logs: list[str] = []

        def probe(**kwargs):
            calls.append(kwargs)
            return pending.pop(0)

        rc = network_gate.wait_for_network(
            "github.com:443",
            probe=probe,
            sleep=sleeps.append,
            clock=_FakeClock(step),
            log=logs.append,
            interval=5.0,
            summary_every=60.0,
        )
        return rc, calls, sleeps, logs

    def test_returns_zero_immediately_when_host_is_healthy(self):
        rc, calls, sleeps, _ = self._run([_result("healthy", "ok")])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [{"target": "github.com:443", "timeout": 5.0}])
        self.assertEqual(sleeps, [])

    def test_every_non_healthy_result_means_keep_waiting(self):
        for code in NON_HEALTHY_CODES:
            with self.subTest(code=code):
                rc, calls, sleeps, _ = self._run(
                    [_result("unreachable", code), _result("healthy", "ok")])
                self.assertEqual(rc, 0)
                self.assertEqual(len(calls), 2)
                self.assertEqual(sleeps, [5.0])

    def test_logs_only_state_changes_while_waiting(self):
        results = [_result("unreachable", "timeout")] * 4 + [
            _result("unreachable", "dns_failed"),
            _result("healthy", "ok"),
        ]
        rc, _, _, logs = self._run(results)
        self.assertEqual(rc, 0)
        waiting = [line for line in logs if "aguardando conectividade" in line]
        self.assertEqual(len(waiting), 2)
        self.assertIn("timeout", waiting[0])
        self.assertIn("dns_failed", waiting[1])
        self.assertIn("confirmada", logs[-1])

    def test_emits_a_bounded_number_of_summaries_while_the_code_repeats(self):
        results = [_result("unreachable", "timeout")] * 20 + [_result("healthy", "ok")]
        rc, _, _, logs = self._run(results, step=10.0)
        self.assertEqual(rc, 0)
        summaries = [line for line in logs if "ainda aguardando" in line]
        self.assertGreaterEqual(len(summaries), 2)
        self.assertLess(len(summaries), 20)


class TestGateNeverSpawnsProcesses(unittest.TestCase):
    def test_wait_for_network_never_spawns_a_process(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("processo proibido")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("processo proibido")):
            rc = network_gate.wait_for_network(
                "github.com:443",
                probe=lambda **kw: _result("healthy", "ok"),
                sleep=lambda seconds: None,
                clock=lambda: 0.0,
                log=lambda message: None,
            )
        self.assertEqual(rc, 0)

    def test_module_imports_nothing_that_spawns_processes(self):
        tree = ast.parse(Path(network_gate.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(alias.name for alias in node.names)
        self.assertFalse({"subprocess", "podman"} & imported, imported)


class TestGateTarget(unittest.TestCase):
    def test_default_target_is_github_https(self):
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("ASB_NETWORK_GATE_TARGET", None)
            self.assertEqual(network_gate.gate_target(), "github.com:443")

    def test_environment_overrides_the_target(self):
        with mock.patch.dict(os.environ, {"ASB_NETWORK_GATE_TARGET": "127.0.0.1:18080"}):
            self.assertEqual(network_gate.gate_target(), "127.0.0.1:18080")


class TestRuntimeShipsNetworkGate(unittest.TestCase):
    def test_install_runtime_ships_the_wrapper_and_the_module(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            dest = install.install_runtime(repo, "revgate", target_base=Path(tmp))
            wrapper = dest / "network_gate.py"
            self.assertTrue(wrapper.is_file())
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
            self.assertIn("from asb.network_gate import main",
                          wrapper.read_text(encoding="utf-8"))
            self.assertTrue((dest / "asb" / "network_gate.py").is_file())


if __name__ == "__main__":
    unittest.main()
