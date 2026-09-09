"""Caracterizacao sintetica do contrato integrado de startup e auth.

Esta suite deliberadamente nao chama fornecedores nem ``auth.login``.  Ela
usa a ``SandboxFixture`` real para criar volumes e estado isolados, e injeta
apenas as respostas de prontidao/control-plane necessarias para pressionar
os ramos 403, 503 e keyring indisponivel sem depender da rede do operador.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import auth, keyring, lifecycle, readiness  # noqa: E402
from asb.workspace import Layout  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


class TestStartupAuth(unittest.TestCase):
    """Contrato entre readiness, account status e o adaptador Orca."""

    def _resume_with_probe(self, sandbox: SandboxFixture,
                           failed_probe: readiness.ProbeResult) -> tuple[int, str, str, list[tuple]]:
        """Executa o gate real de ``resume`` com uma falha controlada.

        O que esta prova detecta: remover o gate, emitir antes do gate, ou
        tratar 403/503/keyring como sucesso.  ``podman`` e substituido abaixo
        porque a falha e uma resposta controlada da readiness, nao uma queda
        de rede do desktop; o worktree e real e pertence a fixture.
        """
        root = sandbox.state_root / "root"
        origin = sandbox.worktree_dir
        root.mkdir(exist_ok=True)
        project_root = sandbox.worktree_dir / "project"
        project_root.mkdir(exist_ok=True)
        (project_root / "preserve.txt").write_text("dados preservados\n", encoding="utf-8")
        layout = Layout(sandbox.workspace, "project", sandbox.worktree_dir,
                        project_root, sandbox.state_root / "state")
        names = {
            "net": f"asb-{sandbox.workspace}",
            "out": f"asb-{sandbox.workspace}-out",
            "agent": f"asb-{sandbox.workspace}-agent",
            "proxy": f"asb-{sandbox.workspace}-proxy",
        }
        podman_calls: list[tuple] = []

        def fake_run(*args, **kwargs):
            podman_calls.append(args)
            return mock.MagicMock(returncode=0)

        probes = [
            readiness.ProbeResult("host", "healthy", "ok", 1, ""),
            failed_probe,
            readiness.ProbeResult("ssh", "healthy", "ok", 1, ""),
            readiness.ProbeResult("keyring", "healthy", "ok", 1, ""),
        ]
        if failed_probe.component == "keyring":
            probes[-1] = failed_probe

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(lifecycle, "_require_workspace", return_value=(names, Path.home(), origin)), \
             mock.patch.object(lifecycle, "layout_for", return_value=layout), \
             mock.patch.object(lifecycle.podman, "ensure_rootless_netns"), \
             mock.patch.object(lifecycle, "ensure_keyring_service"), \
             mock.patch.object(lifecycle.podman, "exists", return_value=True), \
             mock.patch.object(lifecycle.podman, "out", return_value=""), \
             mock.patch.object(lifecycle.podman, "run", side_effect=fake_run), \
             mock.patch.object(readiness, "probe_workspace", return_value=probes), \
             mock.patch.object(readiness, "wait_until", side_effect=lambda probe, **_: probe(0.1)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = lifecycle.resume(root, sandbox.workspace)

        self.assertEqual((project_root / "preserve.txt").read_text(encoding="utf-8"), "dados preservados\n")
        self.assertTrue(sandbox.worktree_exists())
        self.assertEqual([call for call in podman_calls if call and call[0] == "rm"], [])
        return rc, stdout.getvalue(), stderr.getvalue(), podman_calls

    def test_infrastructure_failures_never_emit_connection_or_destroy_worktree(self) -> None:
        """403, 503 e keyring parado nao podem parecer uma conexao Orca valida."""
        cases = (
            ("proxy403", readiness.ProbeResult("proxy", "failed", "connect_denied", 1,
                                                 "adicione o dominio em [network] allow")),
            ("proxy503", readiness.ProbeResult("proxy", "failed", "connect_failed", 1,
                                                 "verifique conectividade do destino ou uplink")),
            ("keyringstopped", readiness.ProbeResult("keyring", "unreachable", "keyring_stopped", 1,
                                                       "asb-agent login")),
        )
        for label, probe in cases:
            with self.subTest(label=label), SandboxFixture(f"startup{label}", auto_setup=False) as sandbox:
                rc, stdout, stderr, _ = self._resume_with_probe(sandbox, probe)
                self.assertNotEqual(rc, 0)
                self.assertEqual(stdout.strip(), "")
                self.assertIn(probe.code, stderr)
                sandbox.assert_no_orphans()

    def test_account_absent_is_json_status_not_a_ssh_blocker(self) -> None:
        """Uma conta ausente e distinta de infraestrutura: SSH saudavel fica utilizavel."""
        with SandboxFixture("startupaccount", auto_setup=False) as sandbox:
            absent = auth.AuthResult("claude", "unauthenticated", "2026-09-08T00:00:00Z",
                                     "conta sintetica ausente", "asb-agent login")
            ssh_ok = readiness.ProbeResult("ssh", "healthy", "ok", 1, "")
            stdout = io.StringIO()
            with mock.patch.object(auth, "check_status", return_value=absent), \
                 mock.patch.object(readiness, "probe_ssh", return_value=ssh_ok), \
                 contextlib.redirect_stdout(stdout):
                rc = auth.status(sandbox.workspace, "claude", json_output=True)
                self.assertEqual(readiness.probe_ssh(2222).state, "healthy")

            report = json.loads(stdout.getvalue())
            self.assertEqual(rc, 1)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["workspace"], sandbox.workspace)
            self.assertEqual(report["results"][0]["state"], "unauthenticated")

    def test_synthetic_auth_verify_keeps_stdout_json_and_spends_no_provider_call(self) -> None:
        """O piloto T1 valida a forma de verify sem executar fornecedor real."""
        with SandboxFixture("startupverify", auto_setup=False) as sandbox:
            verified = auth.AuthResult("codex", "authenticated", "2026-09-08T00:00:00Z",
                                       "resposta sintetica", "")
            stdout = io.StringIO()
            auth.reset_call_budget()
            with mock.patch.object(auth, "verify_client", return_value=verified), \
                 contextlib.redirect_stdout(stdout):
                rc = auth.verify(sandbox.workspace, "codex", json_output=True)

            report = json.loads(stdout.getvalue())
            self.assertEqual(rc, 0)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["callBudget"], {"codex": 0})
            self.assertEqual(report["results"][0]["state"], "authenticated")

    def test_busy_login_lock_is_reported_without_sharing_workspace_state(self) -> None:
        """Um segundo login do mesmo fornecedor falha imediatamente, sem prompt."""
        with SandboxFixture("startuplock", auto_setup=False) as sandbox:
            with mock.patch.object(keyring, "CONFIG", sandbox.state_root / "config"):
                with auth.operator_lock("claude"):
                    with self.assertRaises(auth.LoginBusy):
                        with auth.operator_lock("claude"):
                            pass

    def test_existing_workspace_refuses_new_up_and_preserves_project_data(self) -> None:
        """Um segundo ``up`` nao executa rollback/sweep no workspace existente."""
        with SandboxFixture("startupexists", auto_setup=False) as sandbox:
            sentinel = sandbox.worktree_dir / "existing-work.txt"
            sentinel.write_text("nao apagar\n", encoding="utf-8")
            with mock.patch.object(lifecycle.podman, "exists", return_value=True), \
                 self.assertRaises(lifecycle.podman.PodmanError):
                lifecycle.up(sandbox.state_root, sandbox.workspace, sandbox.worktree_dir)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "nao apagar\n")

    def test_recipe_adapter_preserves_orca_ssh_contract(self) -> None:
        """O adaptador ainda transforma port/project_root internos em schema 1 externo."""
        workspace = "test-startup-recipe"
        project_root = "/tmp/test-startup-project"
        common = Path(__file__).resolve().parents[2] / "recipes" / "common.sh"
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; asb_recipe_json "$2" "$3" "$4"',
             "bash", str(common), workspace, "22022", project_root],
            check=True, capture_output=True, text=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["schemaVersion"], 1)
        self.assertEqual(report["userData"]["workspace"], workspace)
        self.assertEqual(report["connection"]["projectRoot"], project_root)
        self.assertEqual(report["connection"]["type"], "ssh")
        self.assertEqual(report["connection"]["target"]["host"], "127.0.0.1")
        self.assertTrue(report["connection"]["target"]["identitiesOnly"])


if __name__ == "__main__":
    unittest.main()
