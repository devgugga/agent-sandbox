"""tests/unit/test_diagnostic_report.py — Tarefa 5, Passos 1/2/4: `render_text`,
`render_json`, `aggregate_exit_code` e `text_exit_code` de
`cli/asb/diagnostics/report.py`, exercitados com `CheckResult` construidos
diretamente (sem passar por `diagnose()`)."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.diagnostics.checks import CheckResult  # noqa: E402
from asb.diagnostics.report import (  # noqa: E402
    aggregate_exit_code,
    render_json,
    render_text,
    text_exit_code,
)


def _diag(checks, workspaces=(), healthy=True, providers=None):
    """Monta o pacote completo que `render_text`/`render_json` recebem — o
    mesmo formato que `diagnose()` sempre devolveu."""
    return {
        "schemaVersion": 1,
        "healthy": healthy,
        "infrastructure": {
            "healthy": healthy,
            "checks": [c.to_dict() if isinstance(c, CheckResult) else c for c in checks],
            "workspaces": list(workspaces),
        },
        "providers": providers if providers is not None else {
            "claude": {"state": "unknown", "healthy": True, "remediation": "x"},
        },
    }


class TestRenderTextChecks(unittest.TestCase):
    def test_healthy_check_line_has_three_spaces_after_ok(self):
        diag = _diag([CheckResult("podman_installed", True, "podman instalado", "")])
        text = render_text(diag)
        self.assertIn("  ok   podman instalado", text)

    def test_unhealthy_check_line_names_the_remediation(self):
        diag = _diag([CheckResult("git_installed", False, "git instalado", "instale o git")])
        text = render_text(diag)
        self.assertIn("  FALTA git instalado  ->  instale o git", text)

    def test_check_order_is_preserved_verbatim(self):
        diag = _diag([
            CheckResult("a", True, "primeiro", ""),
            CheckResult("b", True, "segundo", ""),
            CheckResult("c", True, "terceiro", ""),
        ])
        text = render_text(diag)
        self.assertLess(text.index("primeiro"), text.index("segundo"))
        self.assertLess(text.index("segundo"), text.index("terceiro"))

    def test_multiline_remediation_is_not_reformatted(self):
        """Nao ha checagem real com remediacao multilinha hoje, mas `_line`
        nunca faz `strip()`/reformatacao — o texto passa por ela intacto."""
        diag = _diag([CheckResult("x", False, "algo", "linha um\nlinha dois")])
        text = render_text(diag)
        self.assertIn("linha um\nlinha dois", text)

    def test_unicode_label_renders_verbatim_in_text(self):
        diag = _diag([CheckResult("x", True, "conexão não íntegra 🐛", "")])
        text = render_text(diag)
        self.assertIn("conexão não íntegra 🐛", text)

    def test_docker_broker_mark_comes_from_remediation_not_healthy_field(self):
        """`docker_broker.healthy` e sempre True (recurso opcional); a marca
        exibida vem de `not remediation` — sem sondar o socket de novo."""
        present = _diag([CheckResult("docker_broker", True, "broker", "")])
        absent = _diag([CheckResult(
            "docker_broker", True, "broker", "asb-agent install-broker")])
        self.assertIn("  ok   broker", render_text(present))
        self.assertIn("  FALTA broker  ->  asb-agent install-broker", render_text(absent))


class TestRenderTextWorkspaces(unittest.TestCase):
    def test_empty_workspaces_still_prints_the_header(self):
        text = render_text(_diag([], workspaces=[]))
        self.assertTrue(text.endswith("\n\nworkspaces:\n"))

    def test_missing_container_workspace(self):
        ws = {"workspace": "demo", "healthy": True, "status": "missing_container",
              "legacy_reason": "", "remediation": "asb-agent up", "services": []}
        text = render_text(_diag([], workspaces=[ws]))
        self.assertIn("demo: SEM CONTAINER  ->  asb-agent up", text)

    def test_legacy_container_workspace(self):
        ws = {"workspace": "demo", "healthy": False,
              "status": "legacy_container: mount ausente",
              "legacy_reason": "mount ausente", "remediation": "asb-agent up",
              "services": []}
        text = render_text(_diag([], workspaces=[ws]))
        self.assertIn(
            "FALTA workspace demo: container legado (mount ausente)  ->  asb-agent up",
            text)

    def test_service_unhealthy_line(self):
        ws = {"workspace": "demo", "healthy": False, "status": "running",
              "legacy_reason": "", "remediation": "", "services": [
                  {"name": "redis", "container": "asb-demo-svc-redis",
                   "state": "unhealthy", "healthy": False,
                   "remediation": "podman logs asb-demo-svc-redis"}]}
        text = render_text(_diag([], workspaces=[ws]))
        self.assertIn(
            "FALTA demo: servico redis (unhealthy)  ->  podman logs asb-demo-svc-redis",
            text)


class TestRenderJson(unittest.TestCase):
    def test_json_is_the_full_bundle_unmodified(self):
        diag = _diag([CheckResult("podman_installed", True, "podman instalado", "")],
                      workspaces=[{"workspace": "demo", "healthy": True,
                                   "status": "running", "legacy_reason": "",
                                   "remediation": "", "services": []}])
        text = render_json(diag)
        self.assertEqual(json.loads(text), diag)

    def test_json_key_set_at_every_level(self):
        diag = _diag([CheckResult("podman_installed", True, "podman instalado", "")])
        data = json.loads(render_json(diag))
        self.assertEqual(set(data), {"schemaVersion", "healthy", "infrastructure", "providers"})
        self.assertEqual(set(data["infrastructure"]), {"healthy", "checks", "workspaces"})
        self.assertEqual(set(data["infrastructure"]["checks"][0]),
                          {"name", "healthy", "label", "remediation"})

    def test_non_ascii_is_escaped_the_same_way_json_dumps_always_did(self):
        """`json.dumps` sem `ensure_ascii=False` escapa acentos por padrao —
        comportamento preexistente, preservado (nao e um requisito desta
        Tarefa mudar)."""
        diag = _diag([CheckResult("x", True, "não íntegra", "")])
        text = render_json(diag)
        self.assertNotIn("ã", text)
        self.assertIn("n\\u00e3o", text)
        self.assertEqual(json.loads(text)["infrastructure"]["checks"][0]["label"],
                          "não íntegra")


class TestAggregateExitCode(unittest.TestCase):
    """Codigo agregado do modo --json: replica `infra_healthy` de
    `diagnose()` (achado empirico: exclui `network_gate`, `docker_broker`,
    `drift_*` e `netns_producers_third_party` do agregado — ver
    `report.py`)."""

    def test_all_healthy_is_zero(self):
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("git_installed", True, "y", "")]
        self.assertEqual(aggregate_exit_code(results), 0)

    def test_one_unhealthy_non_excluded_check_is_one(self):
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("git_installed", False, "y", "instale")]
        self.assertEqual(aggregate_exit_code(results), 1)

    def test_network_gate_failure_alone_does_not_flip_the_json_code(self):
        """Achado empirico preexistente (nao corrigido por esta Tarefa):
        `network_gate` nunca contou para `infra_healthy` em `diagnose()`."""
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("network_gate", False, "falhou", "journalctl")]
        self.assertEqual(aggregate_exit_code(results), 0)

    def test_docker_broker_failure_alone_does_not_flip_the_code(self):
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("docker_broker", False, "sem broker", "instale")]
        self.assertEqual(aggregate_exit_code(results), 0)

    def test_drift_failure_alone_does_not_flip_the_code(self):
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("drift_rtk", False, "defasado", "asb-agent build")]
        self.assertEqual(aggregate_exit_code(results), 0)

    def test_netns_producers_failure_alone_does_not_flip_the_code(self):
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("netns_producers_third_party", False, "y", "z")]
        self.assertEqual(aggregate_exit_code(results), 0)

    def test_a_stopped_web_unit_alone_does_not_flip_the_json_code(self):
        """Minor 8 (revisao final): as seis checagens web sao
        infraestrutura opcional, mesmo precedente de `docker_broker` e
        `network_gate` — um `asb-server.service` parado nao pode derrubar
        `infra_healthy` do sandbox inteiro."""
        for name in ("web_binary", "web_dist", "web_unit", "web_unit_active",
                     "web_token_mode", "web_health"):
            with self.subTest(name):
                results = [CheckResult("podman_installed", True, "x", ""),
                           CheckResult(name, False, "parado", "systemctl ...")]
                self.assertEqual(aggregate_exit_code(results), 0)

    def test_empty_results_is_infrastructure_failure_not_healthy(self):
        """R26: um conjunto vazio de checks nunca reporta saudavel — vale so
        para esta funcao pura (`doctor()` nunca a chama com lista vazia,
        ver `checks.py`/`doctor.py`: `check_podman_installed()` e sempre o
        primeiro item, incondicional)."""
        self.assertEqual(aggregate_exit_code([]), 1)


class TestTextExitCode(unittest.TestCase):
    """Codigo agregado do modo texto — DIVERGE do modo --json hoje: inclui
    `network_gate` no agregado (achado empirico preexistente, preservado tal
    como estava, ver `report.py::text_exit_code`)."""

    def test_all_healthy_is_zero(self):
        diag = _diag([CheckResult("podman_installed", True, "x", "")])
        self.assertEqual(text_exit_code(diag), 0)

    def test_network_gate_failure_flips_the_text_code(self):
        diag = _diag([CheckResult("network_gate", False, "falhou", "journalctl")])
        self.assertEqual(text_exit_code(diag), 1)

    def test_docker_broker_failure_does_not_flip_the_text_code(self):
        diag = _diag([CheckResult("docker_broker", False, "sem broker", "instale")])
        self.assertEqual(text_exit_code(diag), 0)

    def test_drift_failure_does_not_flip_the_text_code(self):
        diag = _diag([CheckResult("drift_rtk", False, "defasado", "asb-agent build")])
        self.assertEqual(text_exit_code(diag), 0)

    def test_a_stopped_web_unit_alone_does_not_flip_the_text_code(self):
        """Minor 8 (revisao final): a mesma exclusao vale no modo texto —
        e o sintoma que o achado descreve e exatamente `asb-agent doctor`
        (texto) saindo 1."""
        for name in ("web_binary", "web_dist", "web_unit", "web_unit_active",
                     "web_token_mode", "web_health"):
            with self.subTest(name):
                diag = _diag([CheckResult(name, False, "parado", "systemctl ...")])
                self.assertEqual(text_exit_code(diag), 0)

    def test_legacy_workspace_flips_the_text_code(self):
        ws = {"workspace": "demo", "healthy": False,
              "status": "legacy_container: motivo", "legacy_reason": "motivo",
              "remediation": "x", "services": []}
        diag = _diag([], workspaces=[ws])
        self.assertEqual(text_exit_code(diag), 1)

    def test_missing_stopped_and_running_workspaces_do_not_flip_the_code(self):
        for status in ("missing_container", "stopped", "running"):
            with self.subTest(status):
                ws = {"workspace": "demo", "healthy": True, "status": status,
                      "legacy_reason": "", "remediation": "", "services": []}
                diag = _diag([], workspaces=[ws])
                self.assertEqual(text_exit_code(diag), 0)

    def test_unhealthy_service_flips_the_code(self):
        ws = {"workspace": "demo", "healthy": False, "status": "running",
              "legacy_reason": "", "remediation": "", "services": [
                  {"name": "redis", "container": "c", "state": "unhealthy",
                   "healthy": False, "remediation": "podman logs c"}]}
        diag = _diag([], workspaces=[ws])
        self.assertEqual(text_exit_code(diag), 1)

    def test_json_and_text_codes_diverge_on_a_failed_network_gate(self):
        """Caracterizacao direta da divergencia preexistente entre os dois
        modos (verificada empiricamente antes desta Tarefa)."""
        results = [CheckResult("podman_installed", True, "x", ""),
                   CheckResult("network_gate", False, "falhou", "journalctl")]
        diag = _diag(results)
        self.assertEqual(aggregate_exit_code(results), 0)
        self.assertEqual(text_exit_code(diag), 1)


class TestBothRenderersReceiveTheSameImmutableResults(unittest.TestCase):
    """Passo 4: as duas funcoes de renderizacao recebem o MESMO pacote e
    nenhuma delas o modifica."""

    def test_render_text_does_not_mutate_the_diag(self):
        diag = _diag([CheckResult("podman_installed", True, "x", "")],
                      workspaces=[{"workspace": "demo", "healthy": True,
                                   "status": "running", "legacy_reason": "",
                                   "remediation": "", "services": []}])
        before = json.dumps(diag, sort_keys=True)
        render_text(diag)
        after = json.dumps(diag, sort_keys=True)
        self.assertEqual(before, after)

    def test_render_json_does_not_mutate_the_diag(self):
        diag = _diag([CheckResult("podman_installed", True, "x", "")])
        before = json.dumps(diag, sort_keys=True)
        render_json(diag)
        after = json.dumps(diag, sort_keys=True)
        self.assertEqual(before, after)

    def test_the_same_diag_feeds_both_renderers_with_matching_data(self):
        diag = _diag([CheckResult("podman_installed", True, "instalado", "")],
                      workspaces=[{"workspace": "demo", "healthy": True,
                                   "status": "running", "legacy_reason": "",
                                   "remediation": "", "services": []}])
        text = render_text(diag)
        data = json.loads(render_json(diag))
        self.assertIn("instalado", text)
        self.assertEqual(data["infrastructure"]["checks"][0]["label"], "instalado")
        self.assertIn("demo", text)
        self.assertEqual(data["infrastructure"]["workspaces"][0]["workspace"], "demo")


if __name__ == "__main__":
    unittest.main()
