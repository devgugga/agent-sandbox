"""tests/unit/test_journal_schema.py — Prisoner tests for strict journal schema 1 validation (C3, I5)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import readiness, supervisor  # noqa: E402
from test_systemd_status_and_rollback import (  # noqa: E402
    KEYRING, WS, adopt, adopt_kr, clean_env, env_for, keyring_host, workspace_host,
)


class TestJournalSchemaValidation(unittest.TestCase):
    """Test strict fail-closed validation of workspace and keyring journals."""

    def _valid_workspace_journal(self) -> dict:
        return {
            "schemaVersion": 1,
            "workspace": "audit",
            "phase": "inventory",
            "containers": {
                "agent": {
                    "id": "a" * 64,
                    "name": "asb-audit-agent",
                    "role": "agent",
                    "image": "alpine:latest",
                    "prior_state": "running",
                    "prior_restart_policy": "unless-stopped",
                    "prior_retry_count": 0,
                    "mounts": [],
                    "ports": [],
                    "unit_name": "asb-audit-agent.service",
                }
            },
            "prior_units": {
                "target_file": "/path/to/systemd/user/asb-audit.target",
                "target_existed": False,
                "target_content": None,
                "target_mode": None,
                "target_enabled": False,
                "target_active": False,
                "services": {
                    "asb-audit-agent.service": {
                        "file": "/path/to/systemd/user/asb-audit-agent.service",
                        "existed": False,
                        "content": None,
                        "mode": None,
                        "enabled": False,
                        "active": False,
                    }
                },
            },
            "runtime_manifest_baseline": {
                "file": "/path/to/state/runtime.json",
                "existed": False,
                "content": None,
                "mode": None,
            },
            "diagnostics": {
                "legacy_credentials_layout": False,
                "forwarder_needs_recreation": False,
                "rootless_netns_producers": [],
            },
        }

    def _valid_keyring_journal(self) -> dict:
        return {
            "schemaVersion": 1,
            "component": "keyring",
            "phase": "inventory",
            "container": {
                "id": "k" * 64,
                "name": "asb-keyring",
                "prior_state": "running",
                "prior_restart_policy": "unless-stopped",
                "prior_retry_count": 0,
                "image": "alpine:latest",
            },
            "prior_unit": {
                "file": "/path/to/systemd/user/asb-keyring.service",
                "existed": False,
                "content": None,
                "mode": None,
                "enabled": False,
                "active": False,
            },
            "prior_dropin": {
                "exists": False,
                "is_project_owned": False,
                "content": None,
                "mode": None,
                "intent_to_remove": False,
                "removed_by_adoption": False,
            },
        }

    def test_valid_workspace_journal_passes(self) -> None:
        j = self._valid_workspace_journal()
        supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_valid_keyring_journal_passes(self) -> None:
        j = self._valid_keyring_journal()
        supervisor._validate_journal_structure(j, "keyring")

    def test_workspace_extra_top_level_key_rejected(self) -> None:
        j = self._valid_workspace_journal()
        j["unexpected_extra"] = 123
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_keyring_extra_top_level_key_rejected(self) -> None:
        j = self._valid_keyring_journal()
        j["unexpected_extra"] = 123
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "keyring")

    def test_nested_key_sets_are_strict(self) -> None:
        """Chave a mais ou a menos DENTRO de prior_units/servico/prior_unit/prior_dropin, topo intacto."""
        svc = "asb-audit-agent.service"
        cases = {
            "prior_units extra": ("workspace", lambda j: j["prior_units"].update(rogue=1)),
            "prior_units missing": ("workspace", lambda j: j["prior_units"].pop("target_mode")),
            "service extra": ("workspace", lambda j: j["prior_units"]["services"][svc].update(rogue=1)),
            "service missing": ("workspace", lambda j: j["prior_units"]["services"][svc].pop("active")),
            "prior_unit extra": ("keyring", lambda j: j["prior_unit"].update(rogue=1)),
            "prior_dropin extra": ("keyring", lambda j: j["prior_dropin"].update(rogue=1)),
            "prior_dropin missing": ("keyring", lambda j: j["prior_dropin"].pop("removed_by_adoption")),
        }
        for name, (kind, mutate) in cases.items():
            with self.subTest(name):
                j = self._valid_workspace_journal() if kind == "workspace" else self._valid_keyring_journal()
                mutate(j)
                with self.assertRaises(ValueError) as cm:
                    if kind == "workspace":
                        supervisor._validate_journal_structure(j, "workspace", ws="audit")
                    else:
                        supervisor._validate_journal_structure(j, "keyring")
                self.assertIn("chaves invalidas ou ausentes", str(cm.exception))

    def test_workspace_missing_baseline_rejected(self) -> None:
        j = self._valid_workspace_journal()
        del j["runtime_manifest_baseline"]
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_workspace_missing_diagnostics_rejected(self) -> None:
        j = self._valid_workspace_journal()
        del j["diagnostics"]
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_invalid_phase_rejected(self) -> None:
        j = self._valid_workspace_journal()
        j["phase"] = "unknown_phase_xyz"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_rollback_error_is_allowed_in_both_journals(self) -> None:
        """I5: rollback_error must be accepted by allowed_keys and validated structurally."""
        jw = self._valid_workspace_journal()
        jw["rollback_error"] = {
            "type": "RuntimeError",
            "message": "fail",
            "phase": "inventory",
            "timestamp": "2026-09-10T12:00:00Z",
        }
        supervisor._validate_journal_structure(jw, "workspace", ws="audit")

        jk = self._valid_keyring_journal()
        jk["rollback_error"] = {
            "type": "RuntimeError",
            "message": "fail",
            "phase": "inventory",
            "timestamp": "2026-09-10T12:00:00Z",
        }
        supervisor._validate_journal_structure(jk, "keyring")

    def test_malformed_error_structure_rejected(self) -> None:
        jw = self._valid_workspace_journal()
        jw["error"] = {"type": "RuntimeError"}  # missing message, phase, timestamp
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(jw, "workspace", ws="audit")

    def test_traversal_path_in_target_file_rejected(self) -> None:
        """C3: paths with .. like ../../asb-audit.target must be rejected."""
        j = self._valid_workspace_journal()
        j["prior_units"]["target_file"] = "../../asb-audit.target"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_traversal_path_in_manifest_baseline_rejected(self) -> None:
        j = self._valid_workspace_journal()
        j["runtime_manifest_baseline"]["file"] = "../../runtime.json"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_traversal_path_in_keyring_unit_rejected(self) -> None:
        """C3: paths with .. like ../../asb-keyring.service must be rejected."""
        j = self._valid_keyring_journal()
        j["prior_unit"]["file"] = "../../asb-keyring.service"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "keyring")

    def test_relative_path_in_keyring_unit_rejected(self) -> None:
        j = self._valid_keyring_journal()
        j["prior_unit"]["file"] = "asb-keyring.service"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "keyring")

    def test_workspace_services_must_strictly_match_containers(self) -> None:
        """C3: services={} when containers is present must fail."""
        j = self._valid_workspace_journal()
        j["prior_units"]["services"] = {}
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_workspace_prior_unit_existed_requires_content_and_mode(self) -> None:
        """C3: existed=True requires content (str) and mode (int); content=None must fail."""
        j = self._valid_workspace_journal()
        j["prior_units"]["services"]["asb-audit-agent.service"]["existed"] = True
        j["prior_units"]["services"]["asb-audit-agent.service"]["content"] = None
        j["prior_units"]["services"]["asb-audit-agent.service"]["mode"] = 0o644
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_workspace_prior_unit_not_existed_requires_none_content_and_mode(self) -> None:
        """C3: existed=False requires content=None and mode=None."""
        j = self._valid_workspace_journal()
        j["prior_units"]["services"]["asb-audit-agent.service"]["existed"] = False
        j["prior_units"]["services"]["asb-audit-agent.service"]["content"] = "residual"
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_keyring_prior_unit_existed_requires_content_and_mode(self) -> None:
        """C3: keyring prior_unit existed=True requires content and mode."""
        j = self._valid_keyring_journal()
        j["prior_unit"]["existed"] = True
        j["prior_unit"]["content"] = None
        j["prior_unit"]["mode"] = 0o644
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "keyring")

    def test_keyring_prior_dropin_exists_requires_content_and_mode(self) -> None:
        """C3: keyring prior_dropin exists=True requires content and mode."""
        j = self._valid_keyring_journal()
        j["prior_dropin"]["exists"] = True
        j["prior_dropin"]["content"] = None
        j["prior_dropin"]["mode"] = 0o644
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "keyring")

    def test_container_missing_required_fields_rejected(self) -> None:
        """C3: missing prior_retry_count or mounts must fail."""
        j = self._valid_workspace_journal()
        del j["containers"]["agent"]["prior_retry_count"]
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_container_extra_fields_rejected(self) -> None:
        """C3: unknown fields in container dict must fail."""
        j = self._valid_workspace_journal()
        j["containers"]["agent"]["unknown_prop"] = 42
        with self.assertRaises(ValueError):
            supervisor._validate_journal_structure(j, "workspace", ws="audit")

    def test_workspace_journal_non_derived_target_path_rejected(self) -> None:
        """C1: target_file with valid basename but in non-derived root (e.g. /tmp/evil/asb-audit.target) must be rejected."""
        j = self._valid_workspace_journal()
        j["prior_units"]["target_file"] = "/tmp/evil/asb-audit.target"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("caminho", str(cm.exception).lower())

    def test_workspace_journal_non_derived_service_path_rejected(self) -> None:
        """C1: service file with valid basename in non-derived root must be rejected."""
        j = self._valid_workspace_journal()
        j["prior_units"]["services"]["asb-audit-agent.service"]["file"] = "/tmp/evil/asb-audit-agent.service"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("caminho", str(cm.exception).lower())

    def test_workspace_journal_non_derived_manifest_path_rejected(self) -> None:
        """C1: runtime.json file in non-derived root must be rejected."""
        j = self._valid_workspace_journal()
        j["runtime_manifest_baseline"]["file"] = "/tmp/evil/runtime.json"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("caminho", str(cm.exception).lower())

    def test_keyring_journal_non_derived_unit_path_rejected(self) -> None:
        """C1: keyring prior_unit file in non-derived root must be rejected."""
        j = self._valid_keyring_journal()
        j["prior_unit"]["file"] = "/tmp/evil/asb-keyring.service"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "keyring",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("caminho", str(cm.exception).lower())

    def test_workspace_journal_incoherent_supervision_configured_phase_rejected(self) -> None:
        """C1: supervision_configured phase is incoherent if containers were running."""
        j = self._valid_workspace_journal()
        j["phase"] = "supervision_configured"
        j["containers"]["agent"]["prior_state"] = "running"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("incoerente", str(cm.exception).lower())

    def test_workspace_journal_incoherent_supervision_started_all_stopped_rejected(self) -> None:
        """C1: supervision_started phase is incoherent if all containers were stopped."""
        j = self._valid_workspace_journal()
        j["phase"] = "supervision_started"
        j["containers"]["agent"]["prior_state"] = "stopped"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
    def test_workspace_journal_incoherent_readiness_verified_all_stopped_rejected(self) -> None:
        """C1: readiness_verified phase is incoherent if all containers were stopped."""
        j = self._valid_workspace_journal()
        j["phase"] = "readiness_verified"
        j["containers"]["agent"]["prior_state"] = "stopped"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "workspace", ws="audit",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("incoerente", str(cm.exception).lower())

    def test_keyring_journal_incoherent_supervision_configured_phase_rejected(self) -> None:
        """C1: keyring supervision_configured is incoherent if container was running."""
        j = self._valid_keyring_journal()
        j["phase"] = "supervision_configured"
        j["container"]["prior_state"] = "running"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "keyring",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("incoerente", str(cm.exception).lower())

    def test_keyring_journal_incoherent_supervision_started_stopped_rejected(self) -> None:
        """C1: keyring supervision_started is incoherent if container was stopped."""
        j = self._valid_keyring_journal()
        j["phase"] = "supervision_started"
        j["container"]["prior_state"] = "stopped"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "keyring",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("incoerente", str(cm.exception).lower())

    def test_keyring_journal_incoherent_readiness_verified_stopped_rejected(self) -> None:
        """C1: keyring readiness_verified is incoherent if container was stopped."""
        j = self._valid_keyring_journal()
        j["phase"] = "readiness_verified"
        j["container"]["prior_state"] = "stopped"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(
                j, "keyring",
                target_path=Path("/path/to/systemd/user"),
                state_path=Path("/path/to/state"),
            )
        self.assertIn("incoerente", str(cm.exception).lower())

    def test_workspace_journal_workspace_name_mismatch_rejected(self) -> None:
        """I6: workspace name in journal differing from expected ws parameter must fail."""
        j = self._valid_workspace_journal()
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(j, "workspace", ws="different_ws")
        self.assertIn("incompativel", str(cm.exception).lower())

    def test_keyring_journal_component_mismatch_rejected(self) -> None:
        """I6: journal component differing from 'keyring' must fail."""
        j = self._valid_keyring_journal()
        j["component"] = "other_component"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(j, "keyring")
        self.assertIn("incompativel", str(cm.exception).lower())

    def test_workspace_journal_role_mismatch_rejected(self) -> None:
        """I6: container entry with role field differing from dict key must fail."""
        j = self._valid_workspace_journal()
        j["containers"]["agent"]["role"] = "proxy"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(j, "workspace", ws="audit")
        self.assertIn("role divergente", str(cm.exception).lower())

    def test_workspace_journal_unit_name_mismatch_rejected(self) -> None:
        """I6: container entry with unit_name differing from canonical name must fail."""
        j = self._valid_workspace_journal()
        j["containers"]["agent"]["unit_name"] = "asb-audit-custom.service"
        with self.assertRaises(ValueError) as cm:
            supervisor._validate_journal_structure(j, "workspace", ws="audit")
        self.assertIn("unit_name invalido", str(cm.exception).lower())


class TestPhaseArtifactMatrix(unittest.TestCase):
    """C1: a fase gravada so e aceita se os artefatos e pos-condicoes que ela promete existem.

    Cada fase e produzida de verdade (adocao interrompida logo apos gravar o
    checkpoint) e depois um artefato prometido por ela e desfeito. A retomada
    tem de recusar ANTES de qualquer mutacao; sem adulteracao, tem de concluir.
    """

    PHASES = ("units_prepared", "policies_updated", "supervision_started", "readiness_verified")
    WS_TAMPERS = {
        "unit_removed": ("units_prepared", lambda h, u, s: (u / f"asb-{WS}-agent.service").unlink()),
        "target_edited": ("units_prepared", lambda h, u, s: (u / f"asb-{WS}.target").write_text("[Unit]\n")),
        "manifest_removed": ("units_prepared", lambda h, u, s: (s / "runtime.json").unlink()),
        "policy_reverted": ("policies_updated",
                            lambda h, u, s: h.containers[f"asb-{WS}-agent"].update(policy="unless-stopped")),
        "target_disabled": ("supervision_started", lambda h, u, s: h.enabled.pop(f"asb-{WS}.target")),
        "service_stopped": ("supervision_started", lambda h, u, s: h._stop(f"asb-{WS}-agent.service")),
    }
    KR_TAMPERS = {
        "unit_removed": ("units_prepared", lambda h, u, s: (u / f"{KEYRING}.service").unlink()),
        "policy_reverted": ("policies_updated", lambda h, u, s: h.containers[KEYRING].update(policy="always")),
        "unit_disabled": ("supervision_started", lambda h, u, s: h.enabled.pop(f"{KEYRING}.service")),
        "unit_stopped": ("supervision_started", lambda h, u, s: h._stop(f"{KEYRING}.service")),
    }

    def _fresh(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        return self.tmp

    def _crashed(self, build, run, journal_name: str, phase: str):
        host, unit_dir, state_dir = build(self._fresh())
        host.crash_at_phase = phase
        with self.assertRaises(SystemExit):
            run(host, self.tmp, unit_dir, state_dir)
        host.crash_at_phase = None
        self.assertEqual(json.loads((state_dir / journal_name).read_text())["phase"], phase)
        return host, unit_dir, state_dir

    def _assert_matrix(self, build, run, journal_name: str, tampers: dict) -> None:
        for phase in self.PHASES:
            with self.subTest(phase=phase, tamper=None):
                host, unit_dir, state_dir = self._crashed(build, run, journal_name, phase)
                self.assertEqual(run(host, self.tmp, unit_dir, state_dir)["phase"], "readiness_verified")
            for name, (since, tamper) in tampers.items():
                if self.PHASES.index(phase) < self.PHASES.index(since):
                    continue
                with self.subTest(phase=phase, tamper=name):
                    host, unit_dir, state_dir = self._crashed(build, run, journal_name, phase)
                    tamper(host, unit_dir, state_dir)
                    before = len(host.events)
                    with self.assertRaises(ValueError) as cm:
                        run(host, self.tmp, unit_dir, state_dir)
                    self.assertIn(phase, str(cm.exception))
                    self.assertEqual(host.events[before:], [], "mutacao antes da recusa")

    def test_workspace_phase_matrix(self) -> None:
        self._assert_matrix(workspace_host, adopt, "journal.json", self.WS_TAMPERS)

    def test_keyring_phase_matrix(self) -> None:
        self._assert_matrix(keyring_host, adopt_kr, "keyring-journal.json", self.KR_TAMPERS)

    def test_stopped_container_started_externally_is_refused_at_supervision_configured(self) -> None:
        """C1: `supervision_configured` promete container parado; rodando, ele esta sem supervisao.

        A adocao viva ja recusa esse estado (`deveria permanecer parado apos
        adocao`). A matriz de retomada nao: `supervision_configured` escapa
        antes das pos-condicoes e o laco so olha containers cujo `prior_state`
        era "running". Um workspace adotado parado, iniciado por fora, volta a
        ser aceito — rodando sem unit ativa.
        """
        tmp = self._fresh()
        host, unit_dir, state_dir = workspace_host(tmp, running=False)
        host.crash_at_phase = "supervision_configured"
        with self.assertRaises(SystemExit):
            adopt(host, tmp, unit_dir, state_dir)
        host.crash_at_phase = None
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "supervision_configured")

        # Os dois containers: com so o agente rodando, a guarda de estado misto
        # (`supervisor.py:1796`) recusa antes de a matriz de fase ser consultada,
        # e o teste passaria pelo motivo errado.
        for name in (f"asb-{WS}-proxy", f"asb-{WS}-agent"):
            host.containers[name].update(running=True)
        before = len(host.events)
        with self.assertRaises(ValueError) as cm:
            adopt(host, tmp, unit_dir, state_dir)
        self.assertIn("supervision_configured", str(cm.exception))
        # Fixa QUAL container foi recusado: sem isto, recusar o container errado
        # — ou deixar de examinar um dos dois — passaria despercebido.
        self.assertIn(f"asb-{WS}-", str(cm.exception))
        self.assertIn("fora da supervisao", str(cm.exception))
        self.assertEqual(host.events[before:], [], "mutacao antes da recusa")

    def test_policies_updated_does_not_check_stopped_containers(self) -> None:
        """Discrimina o `if rank < 3: return`: em `policies_updated` a checagem NAO roda.

        O teste da matriz retoma essa fase com `running=True`, e ai a condicao
        do laco seria falsa de qualquer modo — apagar o `return` antecipado nao
        mudaria o resultado, entao ele nao prova nada sobre a linha. Aqui os
        containers foram adotados parados e um esta em execucao: sem o `return`,
        a retomada recusaria. Ela tem de concluir.
        """
        tmp = self._fresh()
        host, unit_dir, state_dir = workspace_host(tmp, running=False)
        host.crash_at_phase = "policies_updated"
        with self.assertRaises(SystemExit):
            adopt(host, tmp, unit_dir, state_dir)
        host.crash_at_phase = None
        # So o proxy: com o agente rodando e o proxy parado, a guarda de estado
        # misto recusaria antes, e o teste passaria pelo motivo errado.
        host.containers[f"asb-{WS}-proxy"].update(running=True)
        self.assertEqual(adopt(host, tmp, unit_dir, state_dir)["phase"], "supervision_configured")
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"],
                         "supervision_configured")

    def test_readiness_verified_journal_without_artifacts_is_refused_before_any_mutation(self) -> None:
        tmp = self._fresh()
        host, unit_dir, state_dir = workspace_host(tmp)
        with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
            journal = supervisor.adopt_workspace(WS, apply=False, target_dir=unit_dir, state_dir=state_dir)["inventory"]
        journal["phase"] = "readiness_verified"
        state_dir.mkdir(parents=True)
        text = json.dumps(journal)
        (state_dir / "journal.json").write_text(text)
        with self.assertRaises(ValueError) as cm:
            adopt(host, tmp, unit_dir, state_dir)
        self.assertIn("readiness_verified", str(cm.exception))
        self.assertEqual(host.mutation_events(), [])
        self.assertEqual((state_dir / "journal.json").read_text(), text)

    def test_keyring_readiness_verified_journal_without_artifacts_is_refused(self) -> None:
        tmp = self._fresh()
        host, unit_dir, state_dir = keyring_host(tmp)
        with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
            journal = supervisor.adopt_keyring(apply=False, target_dir=unit_dir, state_dir=state_dir)["inventory"]
        journal["phase"] = "readiness_verified"
        state_dir.mkdir(parents=True)
        (state_dir / "keyring-journal.json").write_text(json.dumps(journal))
        with self.assertRaises(ValueError) as cm:
            adopt_kr(host, tmp, unit_dir, state_dir)
        self.assertIn("readiness_verified", str(cm.exception))
        self.assertEqual(host.mutation_events(), [])

    def test_workspace_readiness_is_rechecked_before_trusting_readiness_verified(self) -> None:
        def run(h, t, u, s):
            return adopt(h, t, u, s)

        for failure in (1, "timeout"):
            with self.subTest(failure=failure):
                host, unit_dir, state_dir = self._crashed(workspace_host, run, "journal.json", "readiness_verified")
                self.assertEqual([c[:2] for c in host.readiness_calls], [["--role", "proxy"], ["--role", "agent"]])
                host.readiness_rc = failure
                text = (state_dir / "journal.json").read_text()
                before = len(host.events)
                with self.assertRaises(ValueError) as cm:
                    run(host, self.tmp, unit_dir, state_dir)
                self.assertIn("readiness_verified", str(cm.exception))
                self.assertIn("prontidao", str(cm.exception))
                self.assertEqual(len(host.readiness_calls), 3, "a retomada tem de sondar de novo")
                self.assertEqual(host.events[before:], [], "mutacao antes da recusa")
                self.assertEqual((state_dir / "journal.json").read_text(), text)

    def test_keyring_readiness_verified_requires_the_project_dropin_to_stay_removed(self) -> None:
        from asb.install import PROJECT_DROPIN_HEADER
        content = PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"

        def build(tmp: Path):
            dropin = tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
            dropin.parent.mkdir(parents=True)
            dropin.write_text(content)
            return keyring_host(tmp)

        for reappeared in (False, True):
            with self.subTest(reappeared=reappeared):
                host, unit_dir, state_dir = self._crashed(build, adopt_kr, "keyring-journal.json", "readiness_verified")
                dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
                self.assertFalse(dropin.exists(), "a adocao deveria ter removido o drop-in")
                self.assertTrue(json.loads((state_dir / "keyring-journal.json").read_text())
                                ["prior_dropin"]["removed_by_adoption"])
                if not reappeared:
                    self.assertEqual(adopt_kr(host, self.tmp, unit_dir, state_dir)["phase"], "readiness_verified")
                    continue
                dropin.parent.mkdir(parents=True, exist_ok=True)  # a remocao apaga o diretorio vazio
                dropin.write_text(content)
                before = len(host.events)
                with self.assertRaises(ValueError) as cm:
                    adopt_kr(host, self.tmp, unit_dir, state_dir)
                self.assertIn("drop-in do projeto deveria ter sido removido", str(cm.exception))
                self.assertEqual(host.events[before:], [], "mutacao antes da recusa")
                self.assertEqual(dropin.read_text(), content)

    def test_keyring_readiness_is_rechecked_before_trusting_readiness_verified(self) -> None:
        host, unit_dir, state_dir = self._crashed(keyring_host, adopt_kr, "keyring-journal.json", "readiness_verified")
        self.assertEqual(host.probe.call_count, 1)
        host.probe_result = readiness.ProbeResult("keyring", "failed", "keyring_unavailable", 1, "consulte logs")
        text = (state_dir / "keyring-journal.json").read_text()
        before = len(host.events)
        with self.assertRaises(ValueError) as cm:
            adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertIn("readiness_verified", str(cm.exception))
        self.assertIn("keyring_unavailable", str(cm.exception))
        self.assertEqual(host.probe.call_count, 2, "a retomada tem de sondar de novo")
        self.assertEqual(host.probe.call_args.kwargs["container"], KEYRING)
        self.assertEqual(host.events[before:], [], "mutacao antes da recusa")
        self.assertEqual((state_dir / "keyring-journal.json").read_text(), text)


if __name__ == "__main__":
    unittest.main()
