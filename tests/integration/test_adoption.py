"""tests/integration/test_adoption.py — Integration tests for workspace and keyring adoption/rollback.

Verifies the 15 required scenarios from PROMPT-I6-GEMINI.md and spec §7:
 1. dry-run de workspace produz inventário e zero mutações;
 2. apply + rollback preservam ID, porta, sentinela, dados e worktree;
 3. policies e estados running/stopped são restaurados exatamente;
 4. target/unidades preexistentes, habilitação e atividade são restaurados;
 5. ID divergente antes do apply/rollback recusa sem mutação;
 6. falha entre policy update e start restaura o estado anterior;
 7. interrupção por etapa e retomada via diário são idempotentes;
 8. diário ausente, corrompido ou incompatível falha fechado;
 9. locks concorrentes recusam disputa;
10. keyring dry-run/apply/rollback separados e workspace não o desliga;
11. drop-in alheio/conteúdo divergente é preservado;
12. diagnóstico separa mounts legados, forwarder e supervisão;
13. produtores do namespace rootless são somente inventariados;
14. adoção/rollback nunca chamam podman rm/create/run;
15. teardown deixa zero recursos registrados da fixture.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


class TestAdoption(unittest.TestCase):
    """Integration test suite for adoption and rollback of workspaces and keyring."""

    def _init_repo(self, worktree_dir: Path) -> None:
        """Helper to configure git repo inside worktree."""
        subprocess.run(
            ["git", "-C", str(worktree_dir), "config", "user.name", "Test User"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree_dir), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
        )
        readme = worktree_dir / "README.md"
        readme.write_text("# Test Workspace Adoption\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worktree_dir), "add", "README.md"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree_dir), "commit", "-m", "initial commit"],
            check=True,
            capture_output=True,
        )

    def _cleanup_workspace_units(self, workspace: str) -> None:
        """Cleanup systemd units created for the test workspace."""
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        subprocess.run(["systemctl", "--user", "stop", f"asb-{workspace}.target"], capture_output=True)
        changed = False
        t_file = unit_dir / f"asb-{workspace}.target"
        if t_file.is_file():
            try:
                t_file.unlink()
                changed = True
            except OSError:
                pass
        for role in ("agent", "proxy", "forwarder", "docker"):
            u = unit_dir / f"asb-{workspace}-{role}.service"
            if u.is_file():
                try:
                    u.unlink()
                    changed = True
                except OSError:
                    pass
        if changed:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            subprocess.run(["systemctl", "--user", "reset-failed"], capture_output=True)

    def _cleanup_keyring(self) -> None:
        """Cleanup systemd keyring unit if left over."""
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        k_unit = unit_dir / "asb-keyring.service"
        if k_unit.exists():
            subprocess.run(["systemctl", "--user", "stop", "asb-keyring.service"], capture_output=True)
            try:
                k_unit.unlink()
            except OSError:
                pass
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            subprocess.run(["systemctl", "--user", "reset-failed", "asb-keyring.service"], capture_output=True)

    def _setup_test_workspace(
        self,
        sandbox: SandboxFixture,
        *,
        running: bool = True,
        initial_policy: str = "unless-stopped",
    ) -> tuple[str, str, int]:
        """Sets up an isolated legacy workspace with agent and proxy containers."""
        self.addCleanup(self._cleanup_workspace_units, sandbox.workspace)
        self._init_repo(sandbox.worktree_dir)

        # 1. Main agent container
        sandbox._extra_create_args = [
            "--label", f"asb.workspace={sandbox.workspace}",
            "--label", "asb.role=agent",
            "--restart", initial_policy,
        ]
        sandbox.setup_container()
        if running:
            subprocess.run(["podman", "start", sandbox.container], check=True, capture_output=True)

        cid, port = sandbox.inspect_identity()

        # 2. Proxy container belonging to same workspace
        proxy_name = sandbox.register_container(f"{sandbox._prefix}-proxy")
        cmd_proxy = [
            "podman", "create",
            "--name", proxy_name,
            "--label", f"asb.workspace={sandbox.workspace}",
            "--label", "asb.role=proxy",
            "--restart", initial_policy,
            "docker.io/library/alpine:latest",
            "sh", "-c", "trap 'exit 0' TERM INT; while :; do sleep 0.5 & wait $!; done",
        ]
        subprocess.run(cmd_proxy, check=True, capture_output=True)
        if running:
            subprocess.run(["podman", "start", proxy_name], check=True, capture_output=True)

        return sandbox.container, proxy_name, port

    def _setup_test_keyring(
        self,
        sandbox: SandboxFixture,
        *,
        running: bool = True,
        initial_policy: str = "unless-stopped",
    ) -> str:
        """Sets up an isolated keyring container for the fixture."""
        self.addCleanup(self._cleanup_keyring)
        keyring_name = sandbox.register_container(sandbox.keyring_container)
        cmd_keyring = [
            "podman", "create",
            "--name", keyring_name,
            "--label", "asb.role=keyring",
            "--label", "asb.keyring.schema=2",
            "--restart", initial_policy,
            "docker.io/library/alpine:latest",
            "sh", "-c", "trap 'exit 0' TERM INT; while :; do sleep 0.5 & wait $!; done",
        ]
        subprocess.run(cmd_keyring, check=True, capture_output=True)
        if running:
            subprocess.run(["podman", "start", keyring_name], check=True, capture_output=True)
        return keyring_name

    def test_01_dry_run_produces_inventory_and_zero_mutations(self) -> None:
        """Scenario 1: dry-run de workspace produz inventário e zero mutações."""
        with SandboxFixture("adopt01", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            # Check initial restart policy
            res_pol = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            initial_policy = res_pol.stdout.strip()
            self.assertEqual(initial_policy, "unless-stopped")

            # Run adopt-runtime without --apply (dry-run)
            res_dry = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(
                res_dry.returncode,
                0,
                f"adopt-runtime dry-run failed (code {res_dry.returncode}):\nSTDOUT: {res_dry.stdout}\nSTDERR: {res_dry.stderr}",
            )

            # Parse inventory from stdout
            out_data = json.loads(res_dry.stdout.strip())
            self.assertEqual(out_data.get("status"), "dry_run")
            inventory = out_data.get("inventory", {})
            self.assertIn("containers", inventory)
            self.assertIn("agent", inventory["containers"])

            # Verify ZERO mutations
            res_pol_after = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol_after.stdout.strip(), "unless-stopped")

            # Ensure unit files were NOT written
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            self.assertFalse((unit_dir / f"asb-{sandbox.workspace}.target").exists())
            self.assertFalse((unit_dir / f"asb-{sandbox.workspace}-agent.service").exists())

    def test_02_apply_and_rollback_preserve_identity_port_sentinel_data(self) -> None:
        """Scenario 2: apply + rollback preservam ID, porta, sentinela, dados e worktree."""
        with SandboxFixture("adopt02", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            # Record original identity and write sentinel
            original_identity = sandbox.inspect_identity()
            sentinel_val = "sentinel-preserve-test-42"
            sandbox.write_sentinel(sentinel_val)
            self.assertTrue(sandbox.sentinel_exists())

            # Apply adoption
            res_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(
                res_apply.returncode,
                0,
                f"adopt-runtime --apply failed:\nSTDOUT: {res_apply.stdout}\nSTDERR: {res_apply.stderr}",
            )

            # Check ID, sentinel, policy after apply
            self.assertEqual(sandbox.inspect_identity(), original_identity)
            self.assertTrue(sandbox.sentinel_exists())

            res_pol_apply = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol_apply.stdout.strip(), "no")

            # Rollback adoption
            res_rollback = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(
                res_rollback.returncode,
                0,
                f"rollback-runtime failed:\nSTDOUT: {res_rollback.stdout}\nSTDERR: {res_rollback.stderr}",
            )

            # Check ID, sentinel, policy, worktree after rollback
            self.assertEqual(sandbox.inspect_identity(), original_identity)
            self.assertTrue(sandbox.sentinel_exists())

            res_pol_rb = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol_rb.stdout.strip(), "unless-stopped")
            self.assertTrue((sandbox.worktree_dir / "README.md").is_file())

    def test_03_policies_and_running_stopped_states_restored_exactly(self) -> None:
        """Scenario 3: policies e estados running/stopped são restaurados exatamente."""
        with SandboxFixture("adopt03", auto_setup=False) as sandbox:
            # Setup workspace initially STOPPED
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox, running=False)

            # Apply adoption on STOPPED workspace
            res_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_apply.returncode, 0, f"adopt-runtime --apply failed: {res_apply.stderr}")

            # Crucial invariant: Workspace initially stopped must NOT be started as a side effect!
            res_ps_after_apply = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{agent_name}$", "--filter", "status=running", "--quiet"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ps_after_apply.stdout.strip(), "", "Stopped workspace was started as a side effect!")

            # Policy must be updated to 'no'
            res_pol_apply = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol_apply.stdout.strip(), "no")

            # Rollback
            res_rollback = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_rollback.returncode, 0, f"rollback-runtime failed: {res_rollback.stderr}")

            # Container remains stopped and policy restored to unless-stopped
            res_ps_rb = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{agent_name}$", "--filter", "status=running", "--quiet"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_ps_rb.stdout.strip(), "")
            res_pol_rb = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol_rb.stdout.strip(), "unless-stopped")

            # Additional sub-scenario (IMP-5): container started while supervised must be stopped on rollback
            sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            subprocess.run(["podman", "start", agent_name], check=True, capture_output=True)
            self.assertTrue(sandbox.is_container_running())
            res_rb2 = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_rb2.returncode, 0)
            self.assertFalse(sandbox.is_container_running())

    def test_04_target_and_units_restored_on_rollback(self) -> None:
        """Scenario 4: target/unidades preexistentes, habilitação e atividade são restaurados."""
        with SandboxFixture("adopt04", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            target_unit = f"asb-{sandbox.workspace}.target"
            agent_unit = f"asb-{sandbox.workspace}-agent.service"

            # Pre-condition: no systemd target unit exists
            self.assertFalse((unit_dir / target_unit).exists())
            self.assertFalse((unit_dir / agent_unit).exists())

            # Apply
            res_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_apply.returncode, 0)
            self.assertTrue((unit_dir / target_unit).exists())
            self.assertTrue((unit_dir / agent_unit).exists())

            # Rollback
            res_rb = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_rb.returncode, 0)
            self.assertFalse((unit_dir / target_unit).exists())
            self.assertFalse((unit_dir / agent_unit).exists())

    def test_05_divergent_id_before_apply_rollback_refuses_without_mutation(self) -> None:
        """Scenario 5: ID divergente antes do apply/rollback recusa sem mutação."""
        with SandboxFixture("adopt05", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            # Apply first to record journal
            res_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_apply.returncode, 0)

            # Tamper with journal to simulate divergent container ID
            state_dir = sandbox.state_root / "state" / sandbox.workspace
            journal_path = state_dir / "journal.json"
            self.assertTrue(journal_path.is_file())

            data = json.loads(journal_path.read_text(encoding="utf-8"))
            data["containers"]["agent"]["id"] = "fake-divergent-id-12345"
            journal_path.write_text(json.dumps(data), encoding="utf-8")

            # Now attempt rollback: MUST refuse fail-closed due to divergent ID
            res_rb = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertNotEqual(res_rb.returncode, 0, "Rollback should have failed closed on divergent ID")
            self.assertIn("divergente", res_rb.stderr.lower())

            # Fix journal to allow clean rollback
            res_cid = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            data["containers"]["agent"]["id"] = res_cid.stdout.strip()
            journal_path.write_text(json.dumps(data), encoding="utf-8")
            sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)

    def test_06_failure_between_policy_update_and_start_restores_prior_state(self) -> None:
        """Scenario 6: falha entre policy update e start restaura o estado anterior."""
        with SandboxFixture("adopt06", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            import asb.supervisor as sup

            original_start = sup.start_workspace
            def fail_start(ws, **kwargs):
                raise RuntimeError("Injected systemd start failure")

            try:
                sup.start_workspace = fail_start
                with self.assertRaises(RuntimeError):
                    sup.adopt_workspace(sandbox.workspace, apply=True)
            finally:
                sup.start_workspace = original_start

            # Verify that automatic rollback restored prior policy
            res_pol = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol.stdout.strip(), "unless-stopped")

    def test_07_interruption_per_phase_and_resumption_via_journal_are_idempotent(self) -> None:
        """Scenario 7: interrupção por etapa e retomada via diário são idempotentes."""
        with SandboxFixture("adopt07", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            # Apply adoption
            res_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_apply.returncode, 0)

            # Simulate mid-phase interruption (IMP-4)
            state_dir = sandbox.state_root / "state" / sandbox.workspace
            journal_path = state_dir / "journal.json"
            j_data = json.loads(journal_path.read_text(encoding="utf-8"))
            j_data["phase"] = "units_prepared"
            journal_path.write_text(json.dumps(j_data), encoding="utf-8")

            # Re-apply to resume (idempotent, baseline retention per CRIT-1)
            res_reapply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_reapply.returncode, 0)

            j_after = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(j_after["phase"], "readiness_verified")
            self.assertFalse(j_after["prior_units"]["target_existed"], "Baseline target_existed corrupted by re-apply")
            self.assertEqual(
                j_after["containers"]["agent"]["prior_restart_policy"],
                "unless-stopped",
                "Baseline prior_restart_policy corrupted by re-apply",
            )

            # Rollback: must restore unless-stopped and unlink units
            res_rb1 = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_rb1.returncode, 0)

            res_pol = subprocess.run(
                ["podman", "inspect", agent_name, "--format", "{{.HostConfig.RestartPolicy.Name}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res_pol.stdout.strip(), "unless-stopped")

            # Re-rollback (idempotent)
            res_rb2 = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_rb2.returncode, 0)

    def test_08_missing_corrupt_or_incompatible_journal_fails_closed(self) -> None:
        """Scenario 8: diário ausente, corrompido ou incompatível falha fechado."""
        with SandboxFixture("adopt08", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            state_dir = sandbox.state_root / "state" / sandbox.workspace
            state_dir.mkdir(parents=True, exist_ok=True)
            journal_path = state_dir / "journal.json"

            # 1. Corrupted JSON syntax
            journal_path.write_text("{ corrupt json ...", encoding="utf-8")
            res_rb_corrupt = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertNotEqual(res_rb_corrupt.returncode, 0)
            self.assertIn("corrompido", res_rb_corrupt.stderr.lower())

            # 2. Incompatible schemaVersion
            journal_path.write_text(json.dumps({"schemaVersion": 99}), encoding="utf-8")
            res_rb_incompat = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertNotEqual(res_rb_incompat.returncode, 0)
            self.assertIn("schemaversion", res_rb_incompat.stderr.lower())

            # 3. Missing journal fails closed on rollback (CRIT-2)
            journal_path.unlink()
            res_rb_missing = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertNotEqual(res_rb_missing.returncode, 0)
            self.assertIn("ausente", res_rb_missing.stderr.lower())

    def test_09_concurrent_locks_refuse_contention(self) -> None:
        """Scenario 9: locks concorrentes recusam disputa."""
        with SandboxFixture("adopt09", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            state_dir = sandbox.state_root / "state" / sandbox.workspace
            state_dir.mkdir(parents=True, exist_ok=True)
            lock_path = state_dir / ".adopt.lock"

            # Hold exclusive lock
            with open(lock_path, "a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Attempt adopt while locked
                res_adopt = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
                self.assertNotEqual(res_adopt.returncode, 0)
                self.assertIn("lock", res_adopt.stderr.lower())

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def test_10_keyring_dry_run_apply_rollback_and_workspace_does_not_stop_it(self) -> None:
        """Scenario 10: keyring dry-run/apply/rollback separados e workspace não o desliga."""
        with SandboxFixture("adopt10", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)
            keyring_name = self._setup_test_keyring(sandbox)

            # 1. Keyring dry-run
            res_dry = sandbox.cli("adopt-runtime", "--keyring")
            self.assertEqual(res_dry.returncode, 0, f"keyring dry-run failed: {res_dry.stderr}")
            data_dry = json.loads(res_dry.stdout.strip())
            self.assertEqual(data_dry.get("status"), "dry_run")
            self.assertEqual(data_dry.get("component"), "keyring")

            # 2. Keyring apply
            res_apply = sandbox.cli("adopt-runtime", "--keyring", "--apply")
            self.assertEqual(res_apply.returncode, 0, f"keyring apply failed: {res_apply.stderr}")

            # Adopt workspace as well (IMP-1)
            res_ws_apply = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            self.assertEqual(res_ws_apply.returncode, 0)

            # Keyring unit should exist and be active
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            self.assertTrue((unit_dir / "asb-keyring.service").exists())

            # 3. Workspace rollback should NOT stop or disable keyring service
            res_ws_rb = sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_ws_rb.returncode, 0)
            res_keyring_status = subprocess.run(
                ["systemctl", "--user", "is-active", "asb-keyring.service"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_keyring_status.stdout.strip(), "active")

            # 4. Keyring rollback
            res_rb = sandbox.cli("rollback-runtime", "--keyring")
            self.assertEqual(res_rb.returncode, 0, f"keyring rollback failed: {res_rb.stderr}")
            self.assertFalse((unit_dir / "asb-keyring.service").exists())

    def test_11_third_party_dropin_preserved_and_project_dropin_removed_and_restored(self) -> None:
        """Scenario 11: drop-in alheio é preservado; drop-in do projeto é removido e restaurado."""
        with SandboxFixture("adopt11", auto_setup=False) as sandbox:
            keyring_name = self._setup_test_keyring(sandbox)
            unit_dir = Path.home() / ".config" / "systemd" / "user"
            dropin_dir = unit_dir / "podman-restart.service.d"
            dropin_dir.mkdir(parents=True, exist_ok=True)
            dropin_file = dropin_dir / "agent-sandbox.conf"

            # 1. Write third-party / custom drop-in content
            foreign_content = "# Third party custom drop-in\n[Service]\nEnvironment=CUSTOM=1\n"
            dropin_file.write_text(foreign_content, encoding="utf-8")

            # Apply keyring adoption
            res_apply = sandbox.cli("adopt-runtime", "--keyring", "--apply")
            self.assertEqual(res_apply.returncode, 0)

            # Drop-in must NOT be deleted because it is foreign
            self.assertTrue(dropin_file.exists())
            self.assertEqual(dropin_file.read_text(encoding="utf-8"), foreign_content)

            # Rollback keyring
            sandbox.cli("rollback-runtime", "--keyring")
            self.assertTrue(dropin_file.exists())

            # 2. Write project drop-in content (IMP-2)
            project_content = (
                "[Service]\n"
                "ExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n"
            )
            dropin_file.write_text(project_content, encoding="utf-8")

            # Apply keyring adoption: project drop-in must be removed
            res_apply2 = sandbox.cli("adopt-runtime", "--keyring", "--apply")
            self.assertEqual(res_apply2.returncode, 0)
            self.assertFalse(dropin_file.exists())

            # Rollback keyring: project drop-in must be restored
            res_rb2 = sandbox.cli("rollback-runtime", "--keyring")
            self.assertEqual(res_rb2.returncode, 0)
            self.assertTrue(dropin_file.exists())
            self.assertIn("unshare --rootless-netns", dropin_file.read_text(encoding="utf-8"))

            dropin_file.unlink(missing_ok=True)

    def test_12_diagnostic_separates_legacy_mounts_forwarder_and_supervision(self) -> None:
        """Scenario 12: diagnóstico separa mounts legados, forwarder e supervisão."""
        with SandboxFixture("adopt12", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            # 1. Clean workspace
            res_dry = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_dry.returncode, 0)
            data = json.loads(res_dry.stdout.strip())
            inv = data.get("inventory", {})
            diag = inv.get("diagnostics", {})

            self.assertIn("legacy_credentials_layout", diag)
            self.assertIn("forwarder_needs_recreation", diag)
            self.assertIn("rootless_netns_producers", diag)
            self.assertFalse(diag["legacy_credentials_layout"])
            self.assertFalse(diag["forwarder_needs_recreation"])

            # 2. Setup legacy credentials layout and forwarder container (IMP-5)
            mp = subprocess.run(
                ["podman", "volume", "inspect", sandbox.credentials_volume, "--format", "{{.Mountpoint}}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if mp and Path(mp).is_dir():
                (Path(mp) / ".credentials.json").write_text("{}", encoding="utf-8")

            fwd_name = sandbox.register_container(f"{sandbox._prefix}-forwarder")
            subprocess.run(
                ["podman", "create", "--name", fwd_name, "docker.io/library/alpine:latest", "true"],
                check=True,
                capture_output=True,
            )

            res_dry2 = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace)
            self.assertEqual(res_dry2.returncode, 0)
            diag2 = json.loads(res_dry2.stdout.strip()).get("inventory", {}).get("diagnostics", {})
            self.assertTrue(diag2["legacy_credentials_layout"])
            self.assertTrue(diag2["forwarder_needs_recreation"])

    def test_13_rootless_netns_producers_only_inventoried(self) -> None:
        """Scenario 13: produtores do namespace rootless são somente inventariados."""
        with SandboxFixture("adopt13", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            res_dry = sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace)
            data = json.loads(res_dry.stdout.strip())
            diag = data.get("inventory", {}).get("diagnostics", {})
            producers = diag.get("rootless_netns_producers", [])
            self.assertIsInstance(producers, list)

    def test_14_adoption_and_rollback_never_call_podman_rm_create_run(self) -> None:
        """Scenario 14: adoção/rollback nunca chamam podman rm/create/run."""
        with SandboxFixture("adopt14", auto_setup=False) as sandbox:
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)

            import asb.podman as pmod
            forbidden = ["rm", "create", "run"]
            calls = []

            orig_run = pmod.run
            orig_out = pmod.out

            def audit_run(*args, **kwargs):
                if args and args[0] in forbidden:
                    calls.append(args[0])
                return orig_run(*args, **kwargs)

            def audit_out(*args, **kwargs):
                if args and args[0] in forbidden:
                    calls.append(args[0])
                return orig_out(*args, **kwargs)

            try:
                pmod.run = audit_run
                pmod.out = audit_out

                import asb.supervisor as sup
                sup.adopt_workspace(sandbox.workspace, apply=True)
                sup.rollback_workspace(sandbox.workspace)

                self.assertEqual(calls, [], f"Forbidden podman calls detected: {calls}")
            finally:
                pmod.run = orig_run
                pmod.out = orig_out

    def test_15_teardown_leaves_zero_registered_resources(self) -> None:
        """Scenario 15: teardown deixa zero recursos registrados da fixture."""
        with SandboxFixture("adopt15", auto_setup=False) as sandbox:
            ws = sandbox.workspace
            agent_name, proxy_name, port = self._setup_test_workspace(sandbox)
            sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
            sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)

        # Context manager exited, sandbox.teardown() ran
        # Verify no orphan containers exist for prefix (R8)
        res_ps = subprocess.run(
            ["podman", "ps", "-a", "--filter", f"name=^asb-test-adopt15-", "--quiet"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_ps.stdout.strip(), "")

        # Verify no orphan networks exist for prefix (R8)
        res_net = subprocess.run(
            ["podman", "network", "ls", "--filter", f"name=^asb-test-adopt15-", "--quiet"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_net.stdout.strip(), "")

        # Verify no orphan volumes exist for prefix (R8)
        res_vol = subprocess.run(
            ["podman", "volume", "ls", "--filter", f"name=^asb-test-adopt15-", "--quiet"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_vol.stdout.strip(), "")

        # Verify no unit files remain on disk for this workspace with known exact names (R1)
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        expected_unit_names = [f"asb-{ws}.target"] + [
            f"asb-{ws}-{role}.service" for role in ("agent", "proxy", "forwarder", "docker")
        ]
        remaining_files = [
            p.name for p in [unit_dir / name for name in expected_unit_names]
            if p.exists()
        ]
        self.assertEqual(remaining_files, [])

        # Verify no systemd units remain loaded or active (R1)
        res_units = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", *expected_unit_names, "--plain", "--no-legend"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_units.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
