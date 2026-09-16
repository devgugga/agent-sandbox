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


if __name__ == "__main__":
    unittest.main()
