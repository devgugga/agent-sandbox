"""tests/unit/test_id_swap_protection.py — C2: ID revalidado antes de CADA mutacao.

Para cada posicao k, o container e recriado por fora (mesmo nome, ID novo)
logo depois da k-esima mutacao comprovada. A proxima mutacao — escrita ou
remocao de arquivo, `systemctl` mutante ou `podman update/start/stop` — nao
pode acontecer. A varredura cobre todas as posicoes da adocao e do rollback,
de workspace e de keyring; o numero de posicoes vem de uma execucao sem troca,
entao uma mutacao nova no codigo entra na varredura sozinha.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb.podman import PodmanError  # noqa: E402
from test_systemd_status_and_rollback import (  # noqa: E402
    KEYRING, WS, adopt, adopt_kr, keyring_host, rollback, rollback_kr, workspace_host,
)

IDENTITY_STOP = r"ID divergente|no such container"


def _noop(*_args) -> None:
    return None


class TestIdSwapBeforeEveryMutation(unittest.TestCase):
    def _sweep(self, build, prefix, target, victims, journal_name):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            host, unit_dir, state_dir = build(tmp)
            prefix(host, tmp, unit_dir, state_dir)
            start = host.mutations
            target(host, tmp, unit_dir, state_dir)
            total = host.mutations - start
        self.assertGreater(total, 3, "execucao sem troca nao produziu mutacoes suficientes")

        for victim in victims:
            for k in range(1, total):
                with self.subTest(victim=victim, k=k), tempfile.TemporaryDirectory() as t:
                    tmp = Path(t)
                    host, unit_dir, state_dir = build(tmp)
                    prefix(host, tmp, unit_dir, state_dir)
                    host.swap_after = (host.mutations + k, victim)
                    with self.assertRaises((ValueError, RuntimeError, PodmanError)) as cm:
                        target(host, tmp, unit_dir, state_dir)
                    self.assertIsNotNone(host.swapped_at, "a troca nao foi injetada")
                    self.assertEqual(host.mutations_after_swap(), [],
                                     f"mutacao executada depois da troca na posicao {k}")
                    # A parada vem da identidade: ou a revalidacao do ID antes
                    # da mutacao, ou uma leitura pelo ID antigo, que o host ja
                    # nao conhece (o container foi recriado).
                    self.assertRegex(str(cm.exception), IDENTITY_STOP)
                    journal = json.loads((state_dir / journal_name).read_text())
                    self.assertRegex(journal["error"]["message"], IDENTITY_STOP)

    def test_workspace_adoption_running(self) -> None:
        victims = (f"asb-{WS}-proxy", f"asb-{WS}-agent")
        self._sweep(workspace_host, _noop, adopt, victims, "journal.json")

    def test_workspace_adoption_stopped(self) -> None:
        def build(tmp):
            return workspace_host(tmp, running=False)
        victims = (f"asb-{WS}-proxy", f"asb-{WS}-agent")
        self._sweep(build, _noop, adopt, victims, "journal.json")

    def test_workspace_rollback(self) -> None:
        victims = (f"asb-{WS}-proxy", f"asb-{WS}-agent")
        self._sweep(workspace_host, adopt, rollback, victims, "journal.json")

    def test_unlink_events_are_actually_recorded(self) -> None:
        """A contabilidade do patch de `_remove_file` precisa ser observada.

        O patch e incondicional, entao sua INSTALACAO falha alto se a producao
        renomear a funcao. Mas o corpo dele podia perder os
        `_before_mutation`/`_after_mutation` e continuar chamando `real_remove`:
        os `unlink` sumiriam de `host.mutations`, `total` encolheria, e a
        varredura acima perderia em silencio todas as posicoes de remocao —
        `assertGreater(total, 3)` seguiria passando. Uma asserção fecha isso.
        """
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            host, unit_dir, state_dir = workspace_host(tmp)
            adopt(host, tmp, unit_dir, state_dir)
            rollback(host, tmp, unit_dir, state_dir)
            unlinks = [e for e in host.events if e[0] == "unlink"]
        self.assertTrue(unlinks, "nenhum evento de unlink foi contabilizado")
        self.assertTrue(any(str(unit_dir) in e[1] for e in unlinks),
                        f"unlink nao registrou caminho sob {unit_dir}: {unlinks}")

    def test_keyring_adoption(self) -> None:
        self._sweep(keyring_host, _noop, adopt_kr, (KEYRING,), "keyring-journal.json")

    def test_keyring_adoption_with_project_dropin(self) -> None:
        """O bloco de remocao do drop-in tem de entrar na varredura.

        Sem drop-in, `prior_dropin["exists"]` e False e a adocao nunca executa
        os dois `_verify_ids` soltos nem o `verify=` interno — exatamente o
        trecho do achado Spec 1 do gate. A lacuna era estrutural: nenhum valor
        de `k` alcancava esse codigo enquanto a fixture nao criasse o arquivo.
        """
        def build(tmp):
            return keyring_host(tmp, with_dropin=True)
        self._sweep(build, _noop, adopt_kr, (KEYRING,), "keyring-journal.json")

    def test_keyring_rollback(self) -> None:
        self._sweep(keyring_host, adopt_kr, rollback_kr, (KEYRING,), "keyring-journal.json")


if __name__ == "__main__":
    unittest.main()
