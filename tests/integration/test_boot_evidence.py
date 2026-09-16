"""Forma minima do relatorio de evidencia de boot (T2).

O coletor e SOMENTE LEITURA: nao cria estado, nao inicia login e nunca chama
`auth verify`, cujo orcamento de A4 e de uma chamada real por fornecedor.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
sys.path.insert(0, str(ROOT))
from tests.integration import collect_boot_evidence  # noqa: E402

# Manifesto schema 1 como lifecycle.py o escreve, com os campos que NAO podem
# sair daqui: `ssh_key` e `ASB_KEYRING_PASS_FILE` sao caminhos de segredo.
SECRET_KEY_PATH = "/home/fulano/.local/state/agent-sandbox/ws/ssh/id_ed25519"
SECRET_PASS_PATH = "/home/fulano/.config/agent-sandbox/keyring.pass"
# Campo EXTRA dentro do container. Existe para que o teste de allowlist falhe
# se o coletor copiar a entrada inteira em vez de escolher campo a campo: sem
# ele, copiar tudo e escolher os tres campos dao o mesmo resultado, e a guarda
# passaria sem discriminar nada.
CONTAINER_EXTRA_PATH = "/home/fulano/.local/state/agent-sandbox/ws/agent.cid"
MANIFEST = {
    "schemaVersion": 1,
    "workspace": "test-pilot",
    "runtime_type": "systemd",
    "runtime_backend": "systemd",
    "containers": {
        "agent": {
            "name": "asb-test-pilot-agent",
            "id": "abc123def456",
            "unit": "asb-test-pilot-agent.service",
            "cidfile": CONTAINER_EXTRA_PATH,
        },
    },
    "ssh_key": SECRET_KEY_PATH,
    "ASB_KEYRING_PASS_FILE": SECRET_PASS_PATH,
    "ASB_CREDENTIALS_VOLUME": "asb-credentials",
    "config_dir": "/home/fulano/.config/agent-sandbox",
    "keyring_container": "asb-keyring",
}


class BootEvidenceShapeTest(unittest.TestCase):
    def test_relatorio_tem_forma_minima_e_nao_carrega_segredo(self):
        report = collect_boot_evidence.collect(workspace="test-pilot")
        self.assertEqual(report["schema"], 1)
        self.assertIn("boot_id", report)
        self.assertNotIn("environment", report)
        self.assertNotIn("credentials", report)


class BootEvidenceAllowlistTest(unittest.TestCase):
    """O manifesto carrega caminhos de segredo; o relatorio nao pode carregar."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        state = self.home / ".local" / "state" / "agent-sandbox" / "test-pilot"
        state.mkdir(parents=True)
        (state / "runtime.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _collect(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            return collect_boot_evidence.collect(workspace="test-pilot")

    def test_containers_expoem_somente_nome_id_e_unidade(self):
        report = self._collect()
        self.assertEqual(
            {"name": "asb-test-pilot-agent",
             "id": "abc123def456",
             "unit": "asb-test-pilot-agent.service"},
            report["containers"]["agent"],
        )

    def test_nenhum_caminho_de_segredo_aparece_no_relatorio(self):
        blob = json.dumps(self._collect())
        self.assertNotIn(SECRET_KEY_PATH, blob)
        self.assertNotIn(SECRET_PASS_PATH, blob)
        self.assertNotIn(CONTAINER_EXTRA_PATH, blob)

    def test_relatorio_nao_copia_chaves_do_manifesto_fora_da_allowlist(self):
        report = self._collect()
        self.assertNotIn("ssh_key", report)
        self.assertNotIn("config_dir", report)
        self.assertNotIn("keyring_container", report)
        self.assertEqual([], [k for k in report if k.startswith("ASB_")])

    def test_campos_exigidos_pelo_plano_estao_presentes(self):
        report = self._collect()
        for field in ("boot_id", "timestamp", "versions", "containers",
                      "port", "systemd", "network", "auth"):
            self.assertIn(field, report)


# Saida REAL de `auth status --json` no piloto: o comando sai com codigo 2
# quando algum fornecedor nao esta autenticado. O JSON e valido e e justamente
# o estado que o piloto precisa registrar.
AUTH_STATUS_PAYLOAD = json.dumps({
    "schemaVersion": 1,
    "workspace": "test-pilot",
    "results": [
        {"provider": "claude", "state": "unauthenticated",
         "evidence": "claude auth status --json reportou loggedIn=false"},
        {"provider": "codex", "state": "authenticated",
         "evidence": "codex login status reportou sessao ativa (codigo 0)"},
        {"provider": "agy", "state": "unknown",
         "evidence": "agy nao possui comando de status local comprovado"},
    ],
})


class BootEvidenceAuthExitCodeTest(unittest.TestCase):
    """`auth status` sai != 0 com fornecedor deslogado; o JSON segue valido."""

    def _collect_with_auth_exit(self, code: int) -> dict:
        import subprocess
        real_run = subprocess.run

        def fake_run(args, **kwargs):
            if "auth" in args and "status" in args:
                return subprocess.CompletedProcess(
                    args, code, AUTH_STATUS_PAYLOAD, "")
            return real_run(args, **kwargs)

        with mock.patch.object(collect_boot_evidence.subprocess, "run",
                               side_effect=fake_run):
            return collect_boot_evidence.collect(workspace="test-pilot")

    def test_estado_por_fornecedor_sobrevive_a_codigo_de_saida_nao_zero(self):
        auth = self._collect_with_auth_exit(2)["auth"]
        self.assertEqual(
            {"claude": "unauthenticated", "codex": "authenticated",
             "agy": "unknown"},
            auth["providers"],
        )

    def test_fornecedor_deslogado_domina_o_agregado_sobre_desconhecido(self):
        # Um "unauthenticated" definido e mais informativo que um "unknown":
        # o agregado nao pode esconder a falha real atras da incerteza.
        auth = self._collect_with_auth_exit(2)["auth"]
        self.assertEqual("incomplete", auth["aggregate"])

    def test_evidencia_do_fornecedor_nao_entra_no_relatorio(self):
        blob = json.dumps(self._collect_with_auth_exit(2))
        self.assertNotIn("loggedIn=false", blob)


if __name__ == "__main__":
    unittest.main()
