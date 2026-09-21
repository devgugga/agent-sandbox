"""Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import doctor as doc_mod  # noqa: E402
from asb import lifecycle  # noqa: E402
from asb.diagnostics import checks as diag_checks  # noqa: E402
from asb.podman import PodmanError  # noqa: E402

CLI_PATH = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"


def _load_cli_module():
    loader = importlib.machinery.SourceFileLoader("asb_agent_cli_pull",
                                                  str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_doctor_all_healthy(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[]):
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
        self.assertIn("drop-in legado do podman-restart ausente", output)
        self.assertIn("guarda asb-claude aponta para este checkout", output)

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 3.4.4")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists")
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    def test_doctor_reports_a_tool_drift_as_an_informative_check_result(
        self, mock_which, mock_exists, mock_running, mock_home
    ):
        """`doctor.py`'s laco de defasagem (Passo 13 de `diagnose()`) monta
        `CheckResult(name=f"drift_{tool}", ...)` a partir de
        `checks.check_tool_drift(...)` — construcao NOVA desta Tarefa, nao
        uma relocacao, e sem cobertura ate este teste: um erro de digitacao
        no f-string quebraria o casamento de `_DRIFT_PREFIX` em
        `aggregate_exit_code`/`text_exit_code` e deixaria uma drift check
        (sempre informativa) fora do lugar esperado, sem nada para pegar."""
        mock_home.return_value = self.fake_home

        def fake_podman_out(*args, **kwargs):
            joined = " ".join(str(a) for a in args)
            if "asb.rtk.version" in joined:
                return "0.46.0"
            if "asb.graphify.version" in joined:
                return "0.9.51"
            return "podman version 5.0.0"

        def fake_subrun(argv, **kwargs):
            if isinstance(argv, (list, tuple)) and "systemctl" in argv:
                return mock.Mock(stdout="inactive\n", returncode=0)
            if isinstance(argv, (list, tuple)) and argv[:1] == ["rtk"]:
                # Unica versao com um token que comeca por digito: so `rtk`
                # aciona a defasagem (`graphify` fica None, ver
                # `_host_version`, e `check_tool_drift` nao adiciona nada).
                return mock.Mock(stdout="rtk 0.48.1\n", returncode=0)
            return mock.Mock(stdout="ok\n", returncode=0)

        with mock.patch("asb.diagnostics.checks.podman.out", side_effect=fake_podman_out), \
             mock.patch("asb.diagnostics.checks.subprocess.run", side_effect=fake_subrun), \
             mock.patch("asb.doctor.check_keyring_service",
                        return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[]):
            report = doc_mod.diagnose(self.fake_root)
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                doc_mod.doctor(self.fake_root, as_json=False)
            text = out.getvalue()

        names = [c["name"] for c in report["infrastructure"]["checks"]]
        self.assertIn("drift_rtk", names)
        self.assertNotIn("drift_graphify", names)

        drift = next(c for c in report["infrastructure"]["checks"] if c["name"] == "drift_rtk")
        self.assertTrue(drift["healthy"])  # sempre True: informativo, nunca reprova
        self.assertIn("0.46.0", drift["label"])
        self.assertIn("0.48.1", drift["label"])
        self.assertEqual(drift["remediation"], "asb-agent build")

        # Informativo: mesmo com uma defasagem real, nunca contamina o
        # agregado de saude (nem em JSON nem em texto).
        self.assertTrue(report["healthy"])

        # Aparece no texto exatamente onde o renderizador o trata como
        # qualquer outro check "ok" (o `healthy` sempre True hardcoded
        # suprime a remediacao no texto, tal como antes desta Tarefa).
        self.assertIn("  ok   rtk 0.46.0 na imagem, 0.48.1 no host", text)
        self.assertNotIn("asb-agent build", text)

    @mock.patch("asb.diagnostics.checks.check_workspace_egress", return_value=(True, "ws-running: rodando (egresso ok)", ""))
    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running")
    @mock.patch("asb.diagnostics.checks.podman.exists")
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.check_legacy_agent_container", return_value=(False, "")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("ws-nocontainer: SEM CONTAINER  ->  asb-agent up", output)
        self.assertIn("ws-running: rodando", output)
        self.assertIn("ws-stopped: parado  ->  asb-agent resume --workspace ws-stopped", output)

    @mock.patch("asb.diagnostics.checks.check_workspace_egress")
    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_doctor_fails_when_workspace_egress_fails(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home, mock_egress
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")
        state_dir = self.fake_home / ".local" / "state" / "agent-sandbox"
        origin_file = state_dir / "broken-ws" / "origin"
        origin_file.parent.mkdir(parents=True)
        origin_file.write_text("/fake/origin")

        remediation = "com a rede do host ativa, suspenda e retome todos os workspaces"
        mock_egress.return_value = (
            False,
            "broken-ws: uplink rootless morto (Network is unreachable)",
            remediation,
        )

        out = io.StringIO()
        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.check_legacy_agent_container", return_value=(False, "")), \
             mock.patch("sys.stdout", out):
            code = doc_mod.doctor(self.fake_root)

        self.assertEqual(code, 1)
        output = out.getvalue()
        self.assertIn(
            f"FALTA broken-ws: uplink rootless morto (Network is unreachable)  ->  {remediation}",
            output,
        )


class TestCheckWorkspaceEgress(unittest.TestCase):
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    def test_proxy_stopped(self, mock_running):
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: proxy parado", label)
        self.assertIn("asb-agent resume --workspace demo", fix)

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_egress_ok(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=0, stdout="OK\n")
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertTrue(ok)
        self.assertIn("demo: rodando (egresso ok)", label)
        self.assertEqual(fix, "")

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_egress_uplink_unreachable(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=2, stdout="UNREACHABLE\n")
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: uplink rootless morto (Network is unreachable)", label)
        self.assertNotIn("--rootless-netns", fix)
        self.assertIn("asb-agent suspend", fix)
        self.assertIn("asb-agent resume", fix)

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run", side_effect=OSError("sonda quebrou"))
    def test_egress_probe_error_points_at_the_proxy_logs(self, mock_run, mock_bin, mock_running):
        # Causa desconhecida: nao e necessariamente o uplink, entao a orientacao
        # e diagnostica e nunca manda recriar nem reinicializar o namespace.
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("sonda quebrou", label)
        self.assertNotIn("--rootless-netns", fix)
        self.assertEqual(fix, "podman logs --tail 50 asb-demo-proxy")

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_egress_domain_denied(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=3, stdout="DENIED\n")
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: dominio github.com bloqueado pelo Squid (TCP_DENIED)", label)
        self.assertIn("[network] allow", fix)

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_egress_squid_down(self, mock_run, mock_bin, mock_running):
        mock_run.return_value = mock.Mock(returncode=4, stdout="SQUID_DOWN\n")
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: proxy Squid nao responde na porta 3128", label)
        self.assertIn("asb-agent resume --workspace demo", fix)

    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.require_binary", return_value="/usr/bin/podman")
    @mock.patch("asb.diagnostics.checks.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="mock", timeout=5))
    def test_egress_timeout(self, mock_run, mock_bin, mock_running):
        ok, label, fix = diag_checks.check_workspace_egress("demo")
        self.assertFalse(ok)
        self.assertIn("demo: uplink rootless morto (timeout na sonda de egresso)", label)
        self.assertNotIn("--rootless-netns", fix)
        self.assertIn("asb-agent suspend", fix)
        self.assertIn("asb-agent resume", fix)



class TestPull(unittest.TestCase):
    @mock.patch("asb.lifecycle._origin_of", return_value=None)
    def test_pull_unknown_workspace_raises(self, mock_origin):
        with self.assertRaises(PodmanError) as ctx:
            lifecycle.pull("unknown-ws")
        self.assertIn("workspace desconhecido: unknown-ws", str(ctx.exception))

    def _pull(self, head, valid=True, ref_ok=True, main=None):
        """Roda `pull("test-ws")` (ou `main`) com o Git simulado: `head` e
        a saida de `symbolic-ref` (None = HEAD destacado), `valid` o
        veredito de `check-ref-format --branch` e `ref_ok` o da ref de
        destino. Devolve (resultado, chamadas, stderr, origin, raiz)."""
        calls = []

        def run(argv, **kwargs):
            calls.append((list(argv), kwargs))
            args = argv[3:]
            if args[:1] == ["symbolic-ref"]:
                if head is None:
                    return subprocess.CompletedProcess(
                        argv, 128, b"",
                        b"fatal: ref HEAD is not a symbolic ref\n")
                return subprocess.CompletedProcess(
                    argv, 0, f"{head}\n".encode(), b"")
            if args[:2] == ["check-ref-format", "--branch"]:
                out = f"{args[2]}\n".encode() if valid else b""
                return subprocess.CompletedProcess(
                    argv, 0 if valid else 1, out, b"")
            if args[:1] == ["check-ref-format"]:
                return subprocess.CompletedProcess(
                    argv, 0 if ref_ok else 1, b"", b"")
            return subprocess.CompletedProcess(argv, 0)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        origin = Path(tmp.name) / "origin"
        origin.mkdir()
        err = io.StringIO()
        with mock.patch("asb.lifecycle._origin_of", return_value=origin), \
                mock.patch("asb.lifecycle.subprocess.run", side_effect=run), \
                mock.patch("sys.stderr", err):
            try:
                result = (main or (lambda: lifecycle.pull("test-ws")))()
            except PodmanError as error:
                result = error
        root = str(lifecycle.layout_for(
            origin, "test-ws", Path(os.path.expanduser("~"))).project_root)
        return result, calls, err.getvalue(), origin, root

    def test_pull_fetches_into_namespaced_ref(self):
        code, calls, err, origin, root = self._pull("feat/awesome")
        self.assertEqual(code, 0)
        git = dict(shell=False, capture_output=True, timeout=mock.ANY,
                   check=False, stdin=subprocess.DEVNULL)
        self.assertEqual(calls, [
            (["git", "-C", root, "symbolic-ref", "--short", "HEAD"], git),
            (["git", "-C", root, "check-ref-format", "--branch",
              "feat/awesome"], git),
            (["git", "-C", str(origin), "check-ref-format",
              "refs/asb/test-ws/feat/awesome"], git),
            (["git", "-C", str(origin), "fetch", "--", root,
              "refs/heads/feat/awesome:refs/asb/test-ws/feat/awesome"],
             dict(check=True)),
        ])
        # Mesmas tres linhas de antes, byte a byte.
        self.assertEqual(err, (
            f"buscado em {origin}: refs/asb/test-ws/feat/awesome\n"
            f"  revise:  git -C {origin} log refs/asb/test-ws/feat/awesome\n"
            f"  integre: git -C {origin} merge "
            "refs/asb/test-ws/feat/awesome\n"))

    def test_pull_refuses_an_unusable_branch_without_fetching(self):
        """O branch vem do checkout que o agente escreve: um HEAD
        destacado, uma opcao disfarcada de branch ou um nome que o Git
        recusa nunca chegam ao `git fetch` do host."""
        cases = {
            "detached": dict(head=None),
            "option": dict(head="--upload-pack=touch /tmp/x"),
            "bad name": dict(head="a..b", valid=False),
            "bad destination": dict(head="ok", ref_ok=False),
        }
        for label, case in cases.items():
            with self.subTest(label):
                result, calls, err, _origin, _root = self._pull(**case)
                self.assertIsInstance(result, PodmanError)
                self.assertEqual(
                    [argv for argv, _kw in calls if "fetch" in argv], [])
                self.assertNotIn("buscado em", err)

    def test_a_refused_pull_exits_2_through_the_cli(self):
        cli = _load_cli_module()
        for label, case in {"detached": dict(head=None),
                            "option": dict(head="-x"),
                            "bad name": dict(head="a..b", valid=False)
                            }.items():
            with self.subTest(label), mock.patch.object(
                    cli.sys, "argv",
                    ["asb-agent", "pull", "--workspace", "test-ws"]):
                code, calls, err, _origin, _root = self._pull(
                    **case, main=cli.main)
                self.assertEqual(code, 2)
                self.assertEqual(
                    [argv for argv, _kw in calls if "fetch" in argv], [])
                self.assertTrue(err.startswith("asb-agent: "), err)


class TestPurge(unittest.TestCase):
    @mock.patch("asb.lifecycle.podman.exists", return_value=False)
    @mock.patch("asb.lifecycle._origin_of", return_value=None)
    def test_purge_unknown_workspace_raises(self, mock_origin, mock_exists):
        # Sem estado E sem volume com esse nome: engano de digitacao, nao um
        # workspace derrubado por `down`.
        with self.assertRaises(PodmanError) as ctx:
            lifecycle.purge("unknown-ws", confirmed=True)
        self.assertIn("workspace desconhecido: unknown-ws", str(ctx.exception))

    @mock.patch("asb.lifecycle.podman.exists", return_value=False)
    @mock.patch("asb.lifecycle._origin_of")
    def test_purge_unconfirmed_raises(self, mock_origin, mock_exists):
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
            with mock.patch("sys.stderr", err), \
                    mock.patch("asb.lifecycle.podman.exists", return_value=False):
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
        self.assertIsNone(diag_checks.tool_drift("rtk", "0.46.0", None))

    def test_ferramenta_ausente_na_imagem_pede_build(self):
        ok, label, fix = diag_checks.tool_drift("rtk", None, "0.46.0")
        self.assertFalse(ok)
        self.assertIn("rtk", label)
        self.assertEqual("asb-agent build", fix)

    def test_versoes_iguais_reportam_ok(self):
        ok, label, fix = diag_checks.tool_drift("graphify", "0.9.51", "0.9.51")
        self.assertTrue(ok)
        self.assertIn("0.9.51", label)
        self.assertEqual("", fix)

    def test_versoes_diferentes_citam_as_duas_e_pedem_build(self):
        ok, label, fix = diag_checks.tool_drift("rtk", "0.46.0", "0.48.1")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
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

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_fails_closed_on_inspect_error(self, mock_out):
        mock_out.side_effect = Exception("container inspect failure")
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("falha ao inspecionar container", reason)

    @mock.patch("asb.diagnostics.checks.podman.out", return_value="[]")
    def test_check_legacy_agent_container_fails_closed_on_unexpected_json_shape(self, mock_out):
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("falha ao inspecionar container", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_detects_missing_keyring_mount(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Destination": "/run/asb-credentials"}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("mount /run/asb-keyring ausente", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_detects_missing_keyring_mask(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Destination": "/run/asb-keyring", "RW": false}, {"Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {}}, "Config": {"Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("mascara de isolamento de keyrings ausente", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_rejects_bind_mount_as_keyring_mask(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": false}, {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": true}, {"Type": "bind", "Destination": "/run/asb-credentials/keyrings", "RW": false}], "HostConfig": {"Tmpfs": {}}, "Config": {"Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("mascara", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_rejects_permissive_tmpfs_mask(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": false}, {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "rw,mode=777"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,rw,notmpcopyup,tmpfs-mode=777"], "Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("mascara", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_requires_notmpcopyup(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": false}, {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,tmpfs-mode=000"], "Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("notmpcopyup", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_requires_read_only_runtime_mount(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": true}, {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000"], "Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("somente leitura", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_detects_bad_dbus_env(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Destination": "/run/asb-keyring", "RW": false}, {"Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000"], "Env": []}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_detects_keyring_pass_env(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Destination": "/run/asb-keyring", "RW": false}, {"Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000"], "Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus", "ASB_KEYRING_PASS=secret"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertTrue(is_legacy)
        self.assertIn("ASB_KEYRING_PASS", reason)

    @mock.patch("asb.diagnostics.checks.podman.out")
    def test_check_legacy_agent_container_modern_passes(self, mock_out):
        mock_out.return_value = '{"Mounts": [{"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": false}, {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": true}], "HostConfig": {"Tmpfs": {"/run/asb-credentials/keyrings": "ro,mode=000"}}, "Config": {"CreateCommand": ["podman", "run", "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000"], "Env": ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"]}}'
        is_legacy, reason = diag_checks.check_legacy_agent_container("asb-ws-agent")
        self.assertFalse(is_legacy)
        self.assertEqual(reason, "")

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_doctor_reports_legacy_workspace_container(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        ws_dir = self.fake_home / ".local" / "state" / "agent-sandbox" / "test-ws"
        ws_dir.mkdir(parents=True)
        (ws_dir / "origin").write_text("/fake/repo with space")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.check_legacy_agent_container", return_value=(True, "mount /run/asb-keyring ausente")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root)

            self.assertEqual(code, 1)
            output = out.getvalue()
            self.assertIn("workspace test-ws: container legado (mount /run/asb-keyring ausente)", output)
            self.assertIn("asb-agent up --workspace test-ws --repo '/fake/repo with space'", output)

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running", return_value=False)
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out", return_value="podman version 5.0.0")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_doctor_json_schema1_and_separation(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root, as_json=True)

        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data.get("schemaVersion"), 1)
        self.assertIn("infrastructure", data)
        self.assertIn("providers", data)
        self.assertTrue(data["infrastructure"]["healthy"])
        self.assertIn("claude", data["providers"])
        self.assertIn("codex", data["providers"])
        self.assertIn("agy", data["providers"])

    @mock.patch("asb.doctor.Path.home")
    @mock.patch("asb.diagnostics.checks.podman.running")
    @mock.patch("asb.diagnostics.checks.podman.exists", return_value=True)
    @mock.patch("asb.diagnostics.checks.podman.out")
    @mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock")
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_doctor_service_without_healthcheck_is_process_running(
        self, mock_run, mock_which, mock_out, mock_exists, mock_running, mock_home
    ):
        mock_home.return_value = self.fake_home
        mock_run.return_value = mock.Mock(stdout="enabled\n")
        mock_running.return_value = True

        ws_dir = self.fake_home / ".local" / "state" / "agent-sandbox" / "test-svc-ws"
        ws_dir.mkdir(parents=True)
        repo_dir = Path(self.tmp.name) / "my-repo"
        repo_dir.mkdir(parents=True)
        (ws_dir / "origin").write_text(str(repo_dir))
        (repo_dir / ".agent-sandbox.toml").write_text('[services.redis]\nimage = "redis:alpine"\n')

        def fake_out(*args):
            if any("version" in str(a) for a in args):
                return "podman version 5.0.0"
            if any("{{.State.Health.Status}}" in str(a) for a in args):
                return ""  # Sem healthcheck
            return ""

        mock_out.side_effect = fake_out

        with mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.check_legacy_agent_container", return_value=(False, "")), \
             mock.patch("asb.diagnostics.checks.check_workspace_egress", return_value=(True, "egresso ok", "")), \
             mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[]), \
             mock.patch("asb.podman.run") as mock_podman_run:
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root, as_json=True)

            self.assertEqual(code, 0)
            data = json.loads(out.getvalue())
            ws_item = next(w for w in data["infrastructure"]["workspaces"] if w["workspace"] == "test-svc-ws")
            self.assertEqual(len(ws_item["services"]), 1)
            svc = ws_item["services"][0]
            self.assertEqual(svc["state"], "process_running")
            self.assertNotEqual(svc["state"], "application_ready")
            mock_podman_run.assert_not_called()


class TestDoctorServiceBlockNeverSwallows(unittest.TestCase):
    # Reaproveita o cenario, nunca os testes: herdar a classe os rodaria de
    # novo aqui.
    setUp = TestDoctorSecretService.setUp
    tearDown = TestDoctorSecretService.tearDown
    """Achado da revisao final: um `except Exception: pass` cobria o bloco
    inteiro de servicos. Perfil com erro de sintaxe, ou uma inspecao que
    levanta no meio, davam `services: []` (identico a projeto sem servico) e
    `healthy: true` — o diagnostico reportando sucesso por nao ter conseguido
    ler a propria entrada."""

    def _payload(self, toml_text, out_side_effect):
        ws_dir = self.fake_home / ".local" / "state" / "agent-sandbox" / "test-svc-ws"
        ws_dir.mkdir(parents=True)
        repo_dir = Path(self.tmp.name) / "my-repo"
        repo_dir.mkdir(parents=True)
        (ws_dir / "origin").write_text(str(repo_dir))
        (repo_dir / ".agent-sandbox.toml").write_text(toml_text)

        with mock.patch("asb.doctor.Path.home", return_value=self.fake_home), \
             mock.patch("asb.diagnostics.checks.shutil.which", return_value="/usr/bin/mock"), \
             mock.patch("asb.diagnostics.checks.subprocess.run", return_value=mock.Mock(stdout="enabled\n")), \
             mock.patch("asb.diagnostics.checks.podman.exists", return_value=True), \
             mock.patch("asb.diagnostics.checks.podman.running", return_value=True), \
             mock.patch("asb.diagnostics.checks.podman.out", side_effect=out_side_effect), \
             mock.patch("asb.doctor.check_keyring_service", return_value=(True, "Secret Service (asb-keyring)", "")), \
             mock.patch("asb.diagnostics.checks.check_legacy_agent_container", return_value=(False, "")), \
             mock.patch("asb.diagnostics.checks.check_workspace_egress", return_value=(True, "egresso ok", "")), \
             mock.patch("asb.diagnostics.checks.third_party_netns_producers", return_value=[]):
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = doc_mod.doctor(self.fake_root, as_json=True)
        data = json.loads(out.getvalue())
        ws_item = next(w for w in data["infrastructure"]["workspaces"]
                       if w["workspace"] == "test-svc-ws")
        return code, ws_item

    def test_unreadable_project_profile_fails_the_workspace(self):
        def fake_out(*args):
            return "podman version 5.0.0" if any("version" in str(a) for a in args) else ""

        code, ws_item = self._payload("[services.redis\nimage = ", fake_out)
        self.assertNotEqual(code, 0)
        self.assertFalse(ws_item["healthy"])
        self.assertIn("perfil", ws_item["remediation"] + ws_item["status"])

    def test_one_failing_inspect_does_not_hide_the_remaining_services(self):
        calls = {"n": 0}

        def fake_out(*args):
            if any("version" in str(a) for a in args):
                return "podman version 5.0.0"
            if any("{{.State.Health.Status}}" in str(a) for a in args):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PodmanError("inspect falhou")
                return "unhealthy"
            return ""

        code, ws_item = self._payload(
            '[services.a]\nimage = "redis:alpine"\n[services.b]\nimage = "redis:alpine"\n',
            fake_out)
        self.assertEqual(len(ws_item["services"]), 2)
        self.assertFalse(ws_item["healthy"])
        self.assertNotEqual(code, 0)


class TestEmendaAChecks(unittest.TestCase):
    """Emenda A: o doctor aponta o drop-in legado, a espera de rede e produtores alheios."""

    PROJECT_DROPIN = (
        "# Managed by agent-sandbox: podman-restart netns initialization\n"
        "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_root = Path(self._tmp.name)
        self.dropin_dir = self.config_root / "systemd" / "user" / "podman-restart.service.d"
        env = mock.patch.dict(os.environ, {"ASB_CONFIG_ROOT": str(self.config_root)})
        env.start()
        self.addCleanup(env.stop)

    def test_absent_project_dropin_is_healthy(self):
        check = diag_checks.check_project_dropin_absent()
        self.assertEqual(check.name, "project_dropin_absent")
        self.assertTrue(check.healthy)
        self.assertEqual(check.remediation, "")

    def test_present_project_dropin_is_an_infrastructure_failure(self):
        self.dropin_dir.mkdir(parents=True)
        (self.dropin_dir / "agent-sandbox.conf").write_text(self.PROJECT_DROPIN)
        check = diag_checks.check_project_dropin_absent()
        self.assertFalse(check.healthy)
        self.assertIn("daemon-reload", check.remediation)

    def test_failed_network_gate_is_an_infrastructure_failure(self):
        """Toda unidade de workspace tem Requires=asb-network.service: com a
        espera em `failed`, nenhum workspace sobe, e o doctor dizia 'saudavel'."""
        with mock.patch("asb.diagnostics.checks.subprocess.run",
                        return_value=mock.Mock(stdout="failed\n")):
            check = diag_checks.check_network_gate()
        self.assertFalse(check.healthy)
        self.assertIn("failed", check.label)
        self.assertIn("journalctl", check.remediation)

    def test_network_gate_state_is_reported_without_failing_health(self):
        with mock.patch("asb.diagnostics.checks.subprocess.run",
                        return_value=mock.Mock(stdout="activating\n")):
            check = diag_checks.check_network_gate()
        self.assertEqual(check.name, "network_gate")
        self.assertTrue(check.healthy)
        self.assertIn("activating", check.label)
        self.assertIn("aguardando", check.remediation)

    def test_third_party_producers_exclude_asb_workspaces_and_networkless_containers(self):
        self.dropin_dir.mkdir(parents=True)
        (self.dropin_dir / "agent-sandbox.conf").write_text(self.PROJECT_DROPIN)
        (self.dropin_dir / "other.conf").write_text("[Service]\nExecStartPre=/bin/true\n")
        ps = mock.Mock(returncode=0, stderr="", stdout=(
            "asb-demo-proxy|asb.workspace=demo|asb-demo\n"
            "foreign-app|app=x|podman\n"
            "networkless||\n"
        ))
        with mock.patch("asb.diagnostics.checks.podman.run", return_value=ps) as run:
            producers = diag_checks.third_party_netns_producers()
        self.assertEqual(producers, ["dropin:other.conf", "container:foreign-app"])
        self.assertEqual(run.call_args.args[:4], ("ps", "-a", "--filter", "should-start-on-boot=true"))

    def test_check_project_dropin_absent_handles_runtime_error(self):
        with mock.patch("asb.install.read_project_dropin",
                        side_effect=RuntimeError("symlink outside root")):
            check = diag_checks.check_project_dropin_absent()
        self.assertFalse(check.healthy)
        self.assertIn("symlink outside root", check.remediation)

    def test_third_party_producers_handles_podman_error(self):
        with mock.patch("asb.diagnostics.checks.podman.run",
                        side_effect=PodmanError("podman down")):
            producers = diag_checks.third_party_netns_producers()
        self.assertEqual(producers, ["desconhecido: podman ps falhou (podman down)"])

    def test_diagnose_with_third_party_producers_reports_label_and_remediation(self):
        with mock.patch("asb.diagnostics.checks.third_party_netns_producers",
                        return_value=["container:foreign-app"]), \
             mock.patch("asb.diagnostics.checks.check_project_dropin_absent",
                        return_value=diag_checks.CheckResult(
                            name="dropin", healthy=True, label="ok", remediation="")), \
             mock.patch("asb.diagnostics.checks.check_network_gate",
                        return_value=diag_checks.CheckResult(
                            name="gate", healthy=True, label="ok", remediation="")), \
             mock.patch("asb.diagnostics.checks.podman.run", return_value=mock.Mock(returncode=0)), \
             mock.patch("asb.diagnostics.checks.podman.exists", return_value=True), \
             mock.patch("asb.doctor.check_keyring_service", return_value=(True, "ok", "")):
            report = doc_mod.diagnose(self.config_root)
        netns_checks = [c for c in report["infrastructure"]["checks"] if c["name"] == "netns_producers_third_party"]
        self.assertEqual(len(netns_checks), 1)
        self.assertIn("foreign-app", netns_checks[0]["label"])
        self.assertIn("revise-os", netns_checks[0]["remediation"])
