"""Unit tests for cli/asb/runtime_check.py — papel keyring (Emenda A §5)."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import runtime_check  # noqa: E402
from asb.readiness import ProbeResult  # noqa: E402


def _once(probe, *, timeout, interval=1.0):
    return probe(1.0)


class TestKeyringRole(unittest.TestCase):
    def _main(self, argv, keyring_state="healthy"):
        result = ProbeResult("keyring", keyring_state,
                             "ok" if keyring_state == "healthy" else "keyring_unavailable", 0, "fix")
        stderr = io.StringIO()
        with mock.patch("asb.runtime_check.wait_until", side_effect=_once), \
             mock.patch("asb.runtime_check.probe_keyring", return_value=result) as probe, \
             contextlib.redirect_stderr(stderr):
            rc = runtime_check.main(argv)
        return rc, probe, stderr.getvalue()

    def test_keyring_ready_returns_zero_without_a_manifest(self):
        rc, probe, _ = self._main(["--role", "keyring", "--container", "asb-keyring"])
        self.assertEqual(rc, 0)
        probe.assert_called_once_with(container="asb-keyring", timeout=1.0)

    def test_keyring_unavailable_returns_one(self):
        rc, _, err = self._main(["--role", "keyring", "--container", "asb-keyring"],
                                keyring_state="failed")
        self.assertEqual(rc, 1)
        self.assertIn("keyring_unavailable", err)

    def test_keyring_without_container_is_a_usage_error(self):
        rc, probe, err = self._main(["--role", "keyring"])
        self.assertEqual(rc, 2)
        probe.assert_not_called()
        self.assertIn("--container", err)

    def test_proxy_still_requires_a_manifest(self):
        rc, _, _ = self._main(["--role", "proxy"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
