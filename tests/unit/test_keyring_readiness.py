"""tests/unit/test_keyring_readiness.py — prontidao do Secret Service."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import readiness  # noqa: E402


class TestProbeContract(unittest.TestCase):
    def test_probe_keyring_maps_check_results(self) -> None:
        cases = (
            ((True, "ok", ""), ("healthy", "ok")),
            ((False, "keyring parado", "reinicie"), ("unreachable", "keyring_stopped")),
            ((False, "secret service indisponivel", "consulte logs"), ("failed", "keyring_unavailable")),
        )
        for result, expected in cases:
            with self.subTest(result=result), \
                    mock.patch("asb.lifecycle.check_keyring_service", return_value=result) as chk:
                res = readiness.probe_keyring("test-c")
                self.assertEqual((res.state, res.code), expected)
                chk.assert_called_once_with("test-c", timeout=5.0)

    def test_check_keyring_service_propagates_timeout_to_every_podman_call(self) -> None:
        from asb import keyring
        with mock.patch("asb.podman.exists", return_value=True) as exists, \
                mock.patch("asb.podman.running", return_value=True) as running, \
                mock.patch("asb.keyring._inspect_keyring_container", return_value=(keyring.KEYRING_SCHEMA, {})) as insp, \
                mock.patch("asb.keyring._keyring_mount_contract_issue", return_value="") as issue, \
                mock.patch("asb.podman.run", return_value=mock.Mock(returncode=0)) as run:
            ok, _, _ = keyring.check_keyring_service("asb-keyring", timeout=7.5)
        self.assertTrue(ok)
        exists.assert_called_once_with("container", "asb-keyring", timeout=7.5)
        running.assert_called_once_with("asb-keyring", timeout=7.5)
        insp.assert_called_once_with("asb-keyring", timeout=7.5)
        issue.assert_called_once_with({})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs.get("timeout"), 7.5)

    def test_podman_exists_forwards_timeout(self) -> None:
        from asb import podman
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(podman.exists("container", "c", timeout=4.2))
        self.assertEqual(run.call_args.kwargs.get("timeout"), 4.2)


if __name__ == "__main__":
    unittest.main()
