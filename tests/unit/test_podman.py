"""Testes de cli/asb/podman.py — invólucro fino sobre o binário podman."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.podman import (  # noqa: E402
    PodmanError,
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
        self.assertFalse(exists("volume", "nonexistent-volume-xyz"))

    def test_running_returns_false_for_absent(self):
        self.assertFalse(running("nonexistent-container-xyz"))
