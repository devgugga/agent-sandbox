"""Testes de cli/asb/podman.py — invólucro fino sobre o binário podman."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.podman import (  # noqa: E402
    PodmanError,
    ensure_rootless_netns,
    exists,
    json_out,
    out,
    require_binary,
    run,
    running,
)


class TestPodmanBinary(unittest.TestCase):
    def test_require_binary_finds_podman(self):
        binary = require_binary()
        self.assertTrue(binary.endswith("podman"))

    def test_require_binary_raises_when_missing(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(PodmanError) as ctx:
                require_binary()
            self.assertIn("podman nao encontrado", str(ctx.exception))


class TestPodmanRun(unittest.TestCase):
    def test_run_success(self):
        res = run("--version", capture=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("podman version", res.stdout)

    def test_run_failure_raises_podman_error(self):
        with self.assertRaises(PodmanError) as ctx:
            run("nonexistent-subcommand-12345")
        self.assertIn("falhou", str(ctx.exception))

    def test_run_failure_no_check(self):
        res = run("nonexistent-subcommand-12345", check=False, capture=True)
        self.assertNotEqual(res.returncode, 0)

    def test_out_returns_stripped_stdout(self):
        version = out("--version")
        self.assertTrue(version.startswith("podman version"))

    def test_json_out_parses_json(self):
        info = json_out("version")
        self.assertIsInstance(info, (dict, list))

    def test_run_passes_host_side_timeout_to_subprocess(self):
        # I2: `run()` precisa repassar `timeout=` para subprocess.run, para
        # que um podman travado no lado do host tenha um teto.
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            run("ps", capture=True, timeout=7)
        self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 7)

    def test_run_timeout_expired_propagates(self):
        with mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired(
                            cmd="podman ps", timeout=1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                run("ps", capture=True, timeout=1)

    def test_out_passes_host_side_timeout_to_subprocess(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="x", stderr="")
            out("ps", timeout=3)
        self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 3)

    def test_running_passes_host_side_timeout_through_to_out(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="abc", stderr="")
            running("some-container", timeout=4)
        self.assertEqual(mock_run.call_args.kwargs.get("timeout"), 4)


class TestPodmanKindAndStatus(unittest.TestCase):
    def test_exists_unknown_kind_raises(self):
        with self.assertRaises(PodmanError) as ctx:
            exists("invalid-kind", "name")
        self.assertIn("tipo desconhecido", str(ctx.exception))

    def test_exists_checks_known_kind(self):
        # An impossible name should return False
        self.assertFalse(exists("image", "nonexistent-image-xyz:9999"))
        self.assertFalse(exists("container", "nonexistent-container-xyz"))
        self.assertFalse(exists("network", "nonexistent-network-xyz"))

    def test_exists_dispatches_the_volume_kind(self):
        """O ramo `volume` roda com o subprocesso MOCKADO de proposito: o
        guarda de isolamento da suite (`asb_test_isolation`) proibe qualquer
        invocacao real de podman que NOMEIE um volume, e o que se quer aqui e
        o despacho de `_KINDS`, nao uma ida ao host."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            self.assertFalse(exists("volume", "nonexistent-volume-xyz"))
        argv = mock_run.call_args.args[0]
        self.assertEqual(argv[1:], ["volume", "exists",
                                    "nonexistent-volume-xyz"])

    def test_running_returns_false_for_absent(self):
        self.assertFalse(running("nonexistent-container-xyz"))


class TestEnsureRootlessNetns(unittest.TestCase):
    @mock.patch("asb.podman.run")
    @mock.patch("shutil.which", return_value="/usr/bin/true")
    def test_ensure_rootless_netns_success(self, mock_which, mock_run):
        ensure_rootless_netns()
        mock_which.assert_called_once_with("true")
        mock_run.assert_called_once_with(
            "unshare", "--rootless-netns", "/usr/bin/true"
        )

    @mock.patch("shutil.which", return_value=None)
    def test_ensure_rootless_netns_missing_true_raises(self, mock_which):
        with self.assertRaises(PodmanError) as ctx:
            ensure_rootless_netns()
        self.assertIn("binario 'true' nao encontrado", str(ctx.exception))

