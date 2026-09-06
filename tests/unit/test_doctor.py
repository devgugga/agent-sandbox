"""Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import doctor as doc_mod  # noqa: E402
from asb import lifecycle  # noqa: E402
from asb.podman import PodmanError  # noqa: E402


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake_root = Path(self.tmp.name) / "checkout"
        self.fake_home = Path(self.tmp.name) / "home"
        self.fake_root.mkdir(parents=True)
        self.fake_home.mkdir(parents=True)

        # Fake guards
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

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_all_healthy(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("podman instalado", output)
        self.assertIn("podman 5.0.0 (>= 4.0)", output)
        self.assertIn("git instalado", output)
        self.assertIn("imagem agent-sandbox:latest", output)
        self.assertIn("volume asb-credentials", output)
        self.assertIn("Secret Service (asb-keyring)", output)
        self.assertIn("podman-restart.service habilitado", output)
        self.assertIn("guarda asb-claude aponta para este checkout", output)

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_acusa_asb_agent_fora_do_path(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        """Sem o link o CLI so roda de dentro do checkout, e isso fica mudo."""
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")
        (self.fake_home / ".local" / "bin" / "asb-agent").unlink()

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        self.assertIn("asb-agent aponta para este checkout", out.getvalue())
        self.assertIn("FALTA", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_missing_podman(
        self, mock_run, mock_which, mock_out, mock_exists, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_which.side_effect = lambda cmd: None if cmd == "podman" else "/usr/bin/git"
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn("FALTA podman instalado  ->  instale o podman (>= 4.0)", output)

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 3.4.4")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_old_podman(
        self, mock_run, mock_which, mock_out, mock_exists, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn(
            "FALTA podman 3.4.4 (>= 4.0)  ->  atualize: --internal e resolucao por nome exigem 4+",
            output,
        )

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists")
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_missing_image_and_volume(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")
        mock_exists.return_value = False

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn("FALTA imagem agent-sandbox:latest  ->  asb-agent build", output)
        self.assertIn("FALTA volume asb-credentials  ->  asb-agent login", output)

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_guards_invalid(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        # Break a guard
        claude_link = self.fake_home / ".local" / "bin" / "asb-claude"
        claude_link.unlink()
        claude_link.symlink_to(Path("/other/path"))

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn(
            "FALTA guarda asb-claude aponta para este checkout  ->  asb-agent install-guards",
            output,
        )

    @mock.patch("asb.doctor.check_workspace_egress", return_value=(True, "ws-running: rodando (egresso ok)", ""))
    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running")
    @mock.patch("asb.doctor.podman.exists")
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_workspace_listing(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home, mock_egress
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        # Create 3 workspace states: ws-running, ws-stopped, ws-nocontainer
        state_dir = self.fake_home / ".local" / "state" / "agent-sandbox"
        for ws in ("ws-running", "ws-stopped", "ws-nocontainer"):
            origin_file = state_dir / ws / "origin"
            origin_file.parent.mkdir(parents=True)
            origin_file.write_text("/fake/origin")

        def fake_exists(kind, name):
            if kind == "container" and name == "asb-ws-nocontainer-agent":
                return False
            return True

        def fake_running(name):
            return name == "asb-ws-running-agent"

        mock_exists.side_effect = fake_exists
        mock_running.side_effect = fake_running

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("ws-nocontainer: SEM CONTAINER  ->  asb-agent up", output)
        self.assertIn("ws-running: rodando", output)
        self.assertIn("ws-stopped: parado  ->  asb-agent resume --workspace ws-stopped", output)

    @mock.patch("asb.doctor.check_workspace_egress")
    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_fails_when_workspace_egress_fails(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home, mock_egress
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")
        state_dir = self.fake_home / ".local" / "state" / "agent-sandbox"
        origin_file = state_dir / "broken-ws" / "origin"
        origin_file.parent.mkdir(parents=True)
        origin_file.write_text("/fake/origin")

        mock_egress.return_value = (
            False,
            "broken-ws: uplink rootless morto (Network is unreachable)",
            "podman unshare --rootless-netns true",
        )

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn(
            "FALTA broken-ws: uplink rootless morto (Network is unreachable)  ->  podman unshare --rootless-netns true",
            output,
        )


class TestCheckWorkspaceEgress(unittest.TestCase):
    @mock.patch("asb.doctor.podman.running", return_value=False)
    def test_proxy_stopped(self, mock_running):
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: proxy parado", label)
        self.assertIn("asb-agent resume --workspace demo", fix)

    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.doctor.subprocess.run")
    def test_egress_ok(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=0, stdout="OK\n")
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertTrue(ok)
        self.assertIn("demo: rodando (egresso ok)", label)
        self.assertEqual(fix, "")

    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.doctor.subprocess.run")
    def test_egress_uplink_unreachable(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=2, stdout="UNREACHABLE\n")
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: uplink rootless morto (Network is unreachable)", label)
        self.assertEqual(fix, "podman unshare --rootless-netns true")

    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.doctor.subprocess.run")
    def test_egress_domain_denied(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=3, stdout="DENIED\n")
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: dominio github.com bloqueado pelo Squid (TCP_DENIED)", label)
        self.assertIn("[network] allow", fix)

    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.doctor.subprocess.run")
    def test_egress_squid_down(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=4, stdout="SQUID_DOWN\n")
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: proxy Squid nao responde na porta 3128", label)
        self.assertIn("asb-agent resume --workspace demo", fix)

    @mock.patch("asb.doctor.podman.running", return_value=True)
    @mock.patch("asb.doctor.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.doctor.subprocess.run", side_effect=doc_mod.subprocess.TimeoutExpired(cmd="mock", timeout=5))
    def test_egress_timeout(self, mock_run, mock_bin, mock_running):
        ok, label, fix = doc_mod.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: uplink rootless morto (timeout na sonda de egresso)", label)
        self.assertEqual(fix, "podman unshare --rootless-netns true")



class TestPull(unittest.TestCase):
    @mock.patch("asb.lifecycle._origin_of", return_value=None)
    def test_pull_unknown_workspace_raises(self, mock_origin):
        with self.assertRaises(PodmanError) as ctx:
            lifecycle.pull("unknown-ws")
        self.assertIn("workspace desconhecido: unknown-ws", str(ctx.exception))

    @mock.patch("asb.lifecycle._origin_of")
    @mock.patch("asb.lifecycle.subprocess.run")
    def test_pull_fetches_into_namespaced_ref(self, mock_run, mock_origin):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            origin.mkdir()
            mock_origin.return_value = origin

            mock_run.return_value = mock.Mock(stdout="feat/awesome\n")

            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                code = lifecycle.pull("test-ws")

            self.assertEqual(code, 0)
            mock_run.assert_has_calls([
                mock.call(
                    ["git", "-C", mock.ANY, "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, check=True
                ),
                mock.call(
                    ["git", "-C", str(origin), "fetch", mock.ANY,
                     "feat/awesome:refs/asb/test-ws/feat/awesome"],
                    check=True
                ),
            ])
            self.assertIn("buscado em", err.getvalue())
            self.assertIn("refs/asb/test-ws/feat/awesome", err.getvalue())


class TestPurge(unittest.TestCase):
    @mock.patch("asb.lifecycle._origin_of", return_value=None)
    def test_purge_unknown_workspace_raises(self, mock_origin):
        with self.assertRaises(PodmanError) as ctx:
            lifecycle.purge("unknown-ws", confirmed=True)
        self.assertIn("workspace desconhecido: unknown-ws", str(ctx.exception))

    @mock.patch("asb.lifecycle._origin_of")
    def test_purge_unconfirmed_raises(self, mock_origin):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            origin.mkdir()
            mock_origin.return_value = origin

            with self.assertRaises(PodmanError) as ctx:
                lifecycle.purge("test-ws", confirmed=False)
            self.assertIn("purge apaga", str(ctx.exception))
            self.assertIn("asb-agent pull --workspace test-ws", str(ctx.exception))
            self.assertIn("--yes", str(ctx.exception))

    @mock.patch("asb.lifecycle.remove_workspace")
    @mock.patch("asb.lifecycle.down")
    @mock.patch("asb.lifecycle._origin_of")
    def test_purge_confirmed_calls_down_and_remove(
        self, mock_origin, mock_down, mock_remove
    ):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            origin.mkdir()
            mock_origin.return_value = origin

            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                code = lifecycle.purge("test-ws", confirmed=True)

            self.assertEqual(code, 0)
            mock_down.assert_called_once_with("test-ws")
            mock_remove.assert_called_once()
            self.assertIn("removido:", err.getvalue())


class TestToolDrift(unittest.TestCase):
    """Defasagem entre a versao assada na imagem e a instalada no host.

    O host e a referencia: e nele que o operador atualiza a ferramenta. A
    imagem so muda com `asb-agent build`, entao a divergencia e silenciosa
    ate alguem comparar as duas.
    """

    def test_host_sem_a_ferramenta_nao_diz_nada(self):
        # Nem todo host usa rtk. Avisar aqui seria ruido, nao diagnostico.
        self.assertIsNone(doc_mod.tool_drift("rtk", "0.46.0", None))

    def test_ferramenta_ausente_na_imagem_pede_build(self):
        ok, label, fix = doc_mod.tool_drift("rtk", None, "0.46.0")
        self.assertFalse(ok)
        self.assertIn("rtk", label)
        self.assertEqual("asb-agent build", fix)

    def test_versoes_iguais_reportam_ok(self):
        ok, label, fix = doc_mod.tool_drift("graphify", "0.9.51", "0.9.51")
        self.assertTrue(ok)
        self.assertIn("0.9.51", label)
        self.assertEqual("", fix)

    def test_versoes_diferentes_citam_as_duas_e_pedem_build(self):
        ok, label, fix = doc_mod.tool_drift("rtk", "0.46.0", "0.48.1")
        self.assertFalse(ok)
        self.assertIn("0.46.0", label)
        self.assertIn("0.48.1", label)
        self.assertEqual("asb-agent build", fix)


class TestDoctorSecretService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_secret_service_healthy(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 0)
            self.assertIn("ok   Secret Service (asb-keyring)", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_secret_service_container_missing(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(False, "container asb-keyring", "asb-agent login")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 1)
            self.assertIn("FALTA container asb-keyring  ->  asb-agent login", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_secret_service_container_stopped(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(False, "asb-keyring parado", "asb-agent login")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 1)
            self.assertIn("FALTA asb-keyring parado  ->  asb-agent login", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_secret_service_socket_missing(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(False, "socket do Secret Service (asb-keyring)", "asb-agent login")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 1)
            self.assertIn("FALTA socket do Secret Service (asb-keyring)  ->  asb-agent login", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_secret_service_unresponsive(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(False, "Secret Service sem resposta (asb-keyring)", "asb-agent login")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 1)
            self.assertIn("FALTA Secret Service sem resposta (asb-keyring)  ->  asb-agent login", out.getvalue())

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.doctor.podman.running", return_value=False)
    @mock.patch("asb.doctor.podman.exists", return_value=True)
    @mock.patch("asb.doctor.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.doctor.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.doctor.subprocess.run")
    def test_doctor_never_starts_or_mutates_secret_service(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.podman.run") as mock_podman_run:
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                doc_mod.doctor(self.fake_root)

            # Doctor must never start or create containers
            for call in mock_podman_run.call_args_list:
                args = list(call[0])
                self.assertNotIn("start", args)
                self.assertNotIn("create", args)
                if "run" in args:
                    self.assertNotIn("-d", args)

