"""tests/unit/test_diagnostic_checks.py — Tarefa 5, Passo 3: cobertura direta
dos checks que antes eram inline em `diagnose()` e ganharam uma funcao
propria em `cli/asb/diagnostics/checks.py`. Cada teste afirma os DADOS
devolvidos (nao que um mock foi chamado) e nenhum deles imprime nada."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import doctor as doc_mod  # noqa: E402
from asb.diagnostics import checks as diag_checks  # noqa: E402
from asb.diagnostics.checks import CheckResult  # noqa: E402


class TestCheckPodmanInstalled(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/podman")
    def test_present(self, _which):
        cr = diag_checks.check_podman_installed()
        self.assertEqual(cr, CheckResult("podman_installed", True, "podman instalado", ""))

    @mock.patch("asb.diagnostics.checks.shutil.which", return_value=None)
    def test_absent(self, _which):
        cr = diag_checks.check_podman_installed()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "instale o podman (>= 4.0)")


class TestCheckPodmanVersion(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.1.0")
    def test_modern_is_healthy(self, _out):
        cr = diag_checks.check_podman_version()
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.label, "podman 5.1.0 (>= 4.0)")
        self.assertEqual(cr.remediation, "")

    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 3.4.4")
    def test_old_is_unhealthy(self, _out):
        cr = diag_checks.check_podman_version()
        self.assertFalse(cr.healthy)
        self.assertIn("3.4.4", cr.label)
        self.assertIn("--internal", cr.remediation)


class TestCheckPythonVersion(unittest.TestCase):
    def test_current_interpreter_is_at_least_3_11(self):
        # A propria suite exige 3.11+ (tomllib) — caracteriza o interprete
        # real em vez de forjar sys.version_info.
        cr = diag_checks.check_python_version()
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "")

    def test_old_interpreter_is_unhealthy(self):
        with mock.patch.object(diag_checks.sys, "version_info", (3, 10, 0)):
            cr = diag_checks.check_python_version()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "tomllib e stdlib so a partir do 3.11")


class TestCheckGitInstalled(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/git")
    def test_present(self, _which):
        self.assertTrue(diag_checks.check_git_installed().healthy)

    @mock.patch("asb.diagnostics.checks.shutil.which", return_value=None)
    def test_absent(self, _which):
        cr = diag_checks.check_git_installed()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "instale o git")


class TestCheckImageAndVolumes(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    def test_image_present(self, _exists):
        self.assertTrue(diag_checks.check_image().healthy)

    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=False)
    def test_image_absent_points_at_build(self, _exists):
        cr = diag_checks.check_image()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "asb-agent build")

    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=False)
    def test_credentials_volume_absent_points_at_login(self, _exists):
        cr = diag_checks.check_credentials_volume()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "asb-agent login")

    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=False)
    def test_toolcache_volume_absent_points_at_volume_create(self, _exists):
        cr = diag_checks.check_toolcache_volume()
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "podman volume create asb-toolcache")


class TestCheckGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        self.home = Path(self.tmp.name) / "home"
        self.root.mkdir(parents=True)
        self.home.mkdir(parents=True)
        self.guard_bin = self.root / "cli" / "asb-guard"
        self.guard_bin.parent.mkdir(parents=True)
        self.guard_bin.write_text("#!/bin/sh\n")
        self.bin_dir = self.home / ".local" / "bin"
        self.bin_dir.mkdir(parents=True)

    def test_guard_pointing_at_this_checkout_is_healthy(self):
        (self.bin_dir / "asb-claude").symlink_to(self.guard_bin)
        with mock.patch("asb.diagnostics.checks.Path.home", return_value=self.home):
            cr = diag_checks.check_guard("claude", self.root)
        self.assertEqual(cr.name, "guard_claude")
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "")

    def test_guard_pointing_elsewhere_is_unhealthy(self):
        (self.bin_dir / "asb-claude").symlink_to(Path("/other/path"))
        with mock.patch("asb.diagnostics.checks.Path.home", return_value=self.home):
            cr = diag_checks.check_guard("claude", self.root)
        self.assertFalse(cr.healthy)
        self.assertEqual(cr.remediation, "asb-agent install-guards")

    def test_missing_guard_is_unhealthy(self):
        with mock.patch("asb.diagnostics.checks.Path.home", return_value=self.home):
            cr = diag_checks.check_guard("codex", self.root)
        self.assertFalse(cr.healthy)


class TestCheckCliGuard(unittest.TestCase):
    def test_cli_guard_matching_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            home = Path(tmp) / "home"
            cli_bin = root / "cli" / "asb-agent"
            cli_bin.parent.mkdir(parents=True)
            cli_bin.write_text("#!/usr/bin/env python3\n")
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "asb-agent").symlink_to(cli_bin)
            with mock.patch("asb.diagnostics.checks.Path.home", return_value=home):
                cr = diag_checks.check_cli_guard(root)
            self.assertTrue(cr.healthy)


class TestCheckDockerBroker(unittest.TestCase):
    """`healthy` e sempre True (recurso opcional); so a `remediation` muda
    com a presenca do socket, e a marca de texto deriva dela — ver
    `report.py`."""

    def test_socket_present_is_healthy_with_no_remediation(self):
        with mock.patch("pathlib.Path.is_socket", return_value=True):
            cr = diag_checks.check_docker_broker()
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "")

    def test_socket_absent_is_still_healthy_but_names_the_fix(self):
        with mock.patch("pathlib.Path.is_socket", return_value=False):
            cr = diag_checks.check_docker_broker()
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "asb-agent install-broker")


class TestCheckNetnsProducersThirdParty(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[])
    def test_no_producers_is_healthy(self, _producers):
        cr = diag_checks.check_netns_producers_third_party()
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "")
        self.assertIn("nenhum produtor alheio", cr.label)

    @mock.patch("asb.diagnostics.checks.third_party_netns_producers",
                return_value=["container:foreign-app"])
    def test_producers_are_named_but_still_healthy(self, _producers):
        cr = diag_checks.check_netns_producers_third_party()
        self.assertTrue(cr.healthy)
        self.assertIn("foreign-app", cr.label)
        self.assertIn("revise-os", cr.remediation)


class TestCheckToolDrift(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks._host_version", return_value="0.48.1")
    @mock.patch("asb.diagnostics.checks._image_version", return_value="0.46.0")
    def test_resolves_both_versions_and_delegates_to_tool_drift(self, _img, _host):
        drift = diag_checks.check_tool_drift("rtk", "asb.rtk.version")
        self.assertIsNotNone(drift)
        ok, label, fix = drift
        self.assertFalse(ok)
        self.assertIn("0.46.0", label)
        self.assertIn("0.48.1", label)
        self.assertEqual(fix, "asb-agent build")

    @mock.patch("asb.diagnostics.checks._host_version", return_value=None)
    def test_host_without_the_tool_is_none(self, _host):
        self.assertIsNone(diag_checks.check_tool_drift("rtk", "asb.rtk.version"))


class TestCollectWorkspaces(unittest.TestCase):
    def test_workspace_without_container_is_missing_container_and_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            state_dir = home / ".local" / "state" / "agent-sandbox" / "demo"
            state_dir.mkdir(parents=True)
            (state_dir / "origin").write_text("")
            with mock.patch("asb.diagnostics.checks.Path.home", return_value=home), \
                 mock.patch("asb.diagnostics.checks.podman.exists", return_value=False):
                workspaces = diag_checks.collect_workspaces(Path(tmp) / "root")
        self.assertEqual(len(workspaces), 1)
        ws = workspaces[0]
        self.assertEqual(ws["workspace"], "demo")
        self.assertTrue(ws["healthy"])
        self.assertEqual(ws["status"], "missing_container")
        self.assertEqual(ws["remediation"], "asb-agent up")
        self.assertEqual(ws["services"], [])

    def test_workspaces_are_sorted_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            for name in ("zeta", "alpha", "mid"):
                d = home / ".local" / "state" / "agent-sandbox" / name
                d.mkdir(parents=True)
                (d / "origin").write_text("")
            with mock.patch("asb.diagnostics.checks.Path.home", return_value=home), \
                 mock.patch("asb.diagnostics.checks.podman.exists", return_value=False):
                workspaces = diag_checks.collect_workspaces(Path(tmp) / "root")
        self.assertEqual([w["workspace"] for w in workspaces], ["alpha", "mid", "zeta"])


class TestNoDuplicateProbing(unittest.TestCase):
    """Passo 4: cada sonda cara roda exatamente uma vez por `doctor()`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake_root = Path(self.tmp.name) / "checkout"
        self.fake_home = Path(self.tmp.name) / "home"
        self.fake_root.mkdir(parents=True)
        self.fake_home.mkdir(parents=True)
        guard_bin = self.fake_root / "cli" / "asb-guard"
        guard_bin.parent.mkdir(parents=True)
        guard_bin.write_text("#!/bin/sh\n")
        bin_dir = self.fake_home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        for agent in ("claude", "codex", "agy"):
            (bin_dir / f"asb-{agent}").symlink_to(guard_bin)
        cli_bin = self.fake_root / "cli" / "asb-agent"
        cli_bin.write_text("#!/usr/bin/env python3\n")
        (bin_dir / "asb-agent").symlink_to(cli_bin)

    def test_each_probe_runs_once_per_doctor_call(self):
        """Roda nos DOIS modos: o probe duplicado que esta Tarefa removeu
        (`docker_broker.is_socket()`) vivia so no laco de impressao em
        texto — um teste que so chama `as_json=True` nunca o teria pego (o
        JSON antigo ja sondava uma unica vez). Ver achado da revisao."""
        for as_json in (False, True):
            with self.subTest(as_json=as_json):
                counts = {"which": 0, "podman_out": 0, "podman_exists": 0,
                          "subprocess_run": 0, "is_socket": 0, "keyring": 0}

                def fake_which(cmd):
                    counts["which"] += 1
                    return "/usr/bin/mock"

                def fake_podman_out(*args, **kwargs):
                    counts["podman_out"] += 1
                    return "podman version 5.0.0"

                def fake_podman_exists(kind, name):
                    counts["podman_exists"] += 1
                    return True

                def fake_subrun(*args, **kwargs):
                    counts["subprocess_run"] += 1
                    return mock.Mock(stdout="inactive\n", returncode=0)

                def fake_is_socket(self):
                    counts["is_socket"] += 1
                    return False

                def fake_keyring():
                    counts["keyring"] += 1
                    return True, "Secret Service (asb-keyring)", ""

                with mock.patch("asb.diagnostics.checks.Path.home", return_value=self.fake_home), \
                     mock.patch("asb.diagnostics.checks.shutil.which", side_effect=fake_which), \
                     mock.patch("asb.diagnostics.checks.podman.out", side_effect=fake_podman_out), \
                     mock.patch("asb.diagnostics.checks.podman.exists", side_effect=fake_podman_exists), \
                     mock.patch("asb.diagnostics.checks.subprocess.run", side_effect=fake_subrun), \
                     mock.patch("pathlib.Path.is_socket", fake_is_socket), \
                     mock.patch("asb.doctor.check_keyring_service", side_effect=fake_keyring), \
                     mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[]):
                    out = io.StringIO()
                    with mock.patch("sys.stdout", out):
                        doc_mod.doctor(self.fake_root, as_json=as_json)

                # `podman.exists` roda uma vez por checagem que a usa (image,
                # credentials_volume, toolcache_volume) — 3 vezes, nao mais.
                self.assertEqual(counts["podman_exists"], 3)
                # O socket do broker Docker: uma unica sonda em QUALQUER modo
                # (nao mais a segunda sondagem redundante que o texto antigo
                # fazia so no laco de impressao).
                self.assertEqual(counts["is_socket"], 1)
                self.assertEqual(counts["keyring"], 1)
                # `shutil.which`: podman, git, rtk, graphify = 4.
                self.assertEqual(counts["which"], 4)
                # `podman.out`: "--version" (check_podman_version) + uma
                # inspecao de label por ferramenta de CONTEXT_TOOLS (rtk,
                # graphify) via _image_version = 1 + 2 = 3.
                self.assertEqual(counts["podman_out"], 3)
                # `subprocess.run`: a espera de rede (check_network_gate) +
                # uma sonda "--version" por ferramenta de CONTEXT_TOOLS via
                # _host_version = 1 + 2 = 3.
                self.assertEqual(counts["subprocess_run"], 3)


if __name__ == "__main__":
    unittest.main()
