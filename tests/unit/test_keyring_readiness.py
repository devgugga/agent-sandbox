"""tests/unit/test_keyring_readiness.py — prontidao do Secret Service na adocao do keyring."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import readiness, supervisor  # noqa: E402
from test_systemd_status_and_rollback import KEYRING, adopt_kr, keyring_host, rollback_kr  # noqa: E402


class TestKeyringAdoptionReadiness(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _journal(self, state_dir: Path) -> dict:
        return json.loads((state_dir / "keyring-journal.json").read_text())

    def test_unhealthy_secret_service_rolls_back_automatically(self) -> None:
        host, unit_dir, state_dir = keyring_host(self.tmp)
        host.probe_result = readiness.ProbeResult("keyring", "failed", "keyring_unavailable", 1, "consulte logs")
        with self.assertRaises(RuntimeError) as cm:
            adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertIn("Secret Service", str(cm.exception))
        host.probe.assert_called()
        # O patch de `wait_until` e load-bearing neste caminho: com a sonda
        # permanentemente falha, o `wait_until` real giraria ate o timeout de
        # 10s antes de desistir. Sem asserção ele seria decoracao (R7).
        self.assertEqual(host.wait_until_calls, [10.0], host.wait_until_calls)
        journal = self._journal(state_dir)
        self.assertEqual(journal["phase"], "rolled_back")
        self.assertIn("keyring_unavailable", journal["error"]["message"])
        self.assertEqual(host.containers[KEYRING]["policy"], "unless-stopped")
        self.assertTrue(host.containers[KEYRING]["running"])
        self.assertEqual(list(unit_dir.iterdir()), [])
        self.assertEqual((host.enabled, host.active), ({}, {}))

    def test_healthy_secret_service_reaches_readiness_verified(self) -> None:
        host, unit_dir, state_dir = keyring_host(self.tmp)
        res = adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(res["phase"], "readiness_verified")
        host.probe.assert_called()
        unit = f"{KEYRING}.service"
        self.assertEqual(host.active.get(unit), "active")
        self.assertIn(unit, host.enabled)
        self.assertEqual(host.containers[KEYRING]["policy"], "no")
        self.assertNotIn("error", self._journal(state_dir))

    def test_dropin_removal_failure_rolls_back(self) -> None:
        from asb.install import PROJECT_DROPIN_HEADER
        dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        dropin.parent.mkdir(parents=True)
        dropin.write_text(PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
        host, unit_dir, state_dir = keyring_host(self.tmp)
        with mock.patch.object(supervisor, "remove_project_dropin", return_value=False) as remove, \
                self.assertRaises(RuntimeError) as cm:
            adopt_kr(host, self.tmp, unit_dir, state_dir)
        remove.assert_called_once()
        self.assertIn("drop-in", str(cm.exception))
        self.assertEqual(self._journal(state_dir)["phase"], "rolled_back")
        self.assertTrue(dropin.is_file())

    def test_dropin_swapped_during_adoption_is_kept_and_adoption_rolls_back(self) -> None:
        """I4 pelo chamador: troca entre a ultima validacao e a remocao, dentro de adopt_keyring."""
        import os
        from asb.install import PROJECT_DROPIN_HEADER
        dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        dropin.parent.mkdir(parents=True)
        dropin.write_text(PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
        foreign = "# drop-in de terceiro\n[Service]\nEnvironment=X=1\n"
        swapped: list[int] = []

        def swap_then(real):
            def hook(src, *args, **kwargs):
                if not swapped and os.fspath(src) in (dropin.name, str(dropin)):
                    tmp = dropin.parent / ".swap"
                    tmp.write_text(foreign)
                    os.replace(tmp, dropin)
                    swapped.append(dropin.stat().st_ino)
                return real(src, *args, **kwargs)
            return hook

        host, unit_dir, state_dir = keyring_host(self.tmp)
        with mock.patch("os.rename", side_effect=swap_then(os.rename)), \
                mock.patch("os.unlink", side_effect=swap_then(os.unlink)), \
                self.assertRaises(RuntimeError) as cm:
            adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue(swapped, "a troca nao foi provocada")
        self.assertIn("substitu", str(cm.exception))
        self.assertEqual(dropin.read_text(), foreign)
        self.assertEqual(dropin.stat().st_ino, swapped[0])
        journal = self._journal(state_dir)
        self.assertEqual(journal["phase"], "rolled_back")
        self.assertFalse(journal["prior_dropin"]["removed_by_adoption"])
        self.assertEqual(host.containers[KEYRING]["policy"], "unless-stopped")

    def test_id_swap_during_dropin_removal_blocks_reload_and_readiness_verified(self) -> None:
        """C2: o container trocado DEPOIS do `_verify_ids` que guarda a entrada da remocao.

        O `_verify_ids` da adocao roda imediatamente antes de
        `remove_project_dropin`. Dentro dela ainda vem o `unlink` da quarentena
        e um `daemon-reload`; ao voltar, a adocao grava `removed_by_adoption` e
        crava `readiness_verified`. Se o keyring for recriado por fora nessa
        janela, nada disso pode acontecer: a identidade que autorizou a mutacao
        deixou de existir.
        """
        import os
        from asb.install import PROJECT_DROPIN_HEADER
        dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        dropin.parent.mkdir(parents=True)
        dropin.write_text(PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
        host, unit_dir, state_dir = keyring_host(self.tmp)
        original_id = host.containers[KEYRING]["id"]
        swapped: list[str] = []
        real_unlink = os.unlink

        def unlink_then_swap(path, *a, **kw):
            # A quarentena tem nome ".<nome>.asb-remove-<pid>-<rand>": o unlink
            # dela e a ultima acao antes do daemon-reload de `install.py`.
            if not swapped and "asb-remove-" in os.fspath(path):
                real_unlink(path, *a, **kw)
                host.swap(KEYRING)
                swapped.append(host.containers[KEYRING]["id"])
                return
            return real_unlink(path, *a, **kw)

        with mock.patch("os.unlink", side_effect=unlink_then_swap):
            with self.assertRaises(ValueError) as cm:
                adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue(swapped, "a troca de ID nao foi provocada")
        self.assertNotEqual(swapped[0], original_id)
        self.assertIn("ID divergente", str(cm.exception))
        journal = self._journal(state_dir)
        self.assertNotEqual(journal["phase"], "readiness_verified")

    def test_id_swap_before_the_first_verify_blocks_the_unlink(self) -> None:
        """C2: a PRIMEIRA `verify()`, a que guarda o unlink da quarentena.

        O teste irmao troca o ID durante o `os.unlink`, quando essa primeira
        chamada ja passou. Aqui a troca cai logo apos o `rename`, antes dela: se
        ela faltasse, ou engolisse excecao, o unlink aconteceria sob identidade
        obsoleta e o arquivo ja estaria apagado quando a segunda `verify()`
        percebesse — desfecho estritamente pior.
        """
        import os
        from asb.install import PROJECT_DROPIN_HEADER
        dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        dropin.parent.mkdir(parents=True)
        content = PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        dropin.write_text(content)
        host, unit_dir, state_dir = keyring_host(self.tmp)
        original = host.containers[KEYRING]["id"]
        swapped: list[str] = []
        real_rename = os.rename

        def rename_then_swap(src, dst, *a, **kw):
            res = real_rename(src, dst, *a, **kw)
            if not swapped and "asb-remove-" in os.fspath(dst):
                host.swap(KEYRING)
                swapped.append(host.containers[KEYRING]["id"])
            return res

        with mock.patch("os.rename", side_effect=rename_then_swap):
            with self.assertRaises(ValueError) as cm:
                adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue(swapped, "a troca de ID nao foi provocada")
        self.assertNotEqual(swapped[0], original)
        self.assertIn("ID divergente", str(cm.exception))
        journal = self._journal(state_dir)
        self.assertNotEqual(journal["phase"], "readiness_verified")
        # O rollback tambem recusa: ele nao muta sob identidade trocada. O
        # drop-in fica na quarentena, mas nada se perde — o conteudo esta
        # intacto em disco e o diario registra os dois erros. Recuperacao e
        # manual, por decisao de contrato: o container que autorizava a
        # mutacao foi destruido por terceiro.
        self.assertIn("ID divergente", journal["rollback_error"]["message"])
        self.assertFalse(dropin.is_file())
        quarantena = [q for q in dropin.parent.iterdir() if "asb-remove-" in q.name]
        self.assertEqual(len(quarantena), 1, f"quarentena ausente: {list(dropin.parent.iterdir())}")
        self.assertEqual(quarantena[0].read_text(), content, "o conteudo do drop-in se perdeu")


class TestProbeContract(unittest.TestCase):
    def test_probe_keyring_maps_check_results(self) -> None:
        cases = (
            ((True, "ok", ""), ("healthy", "ok")),
            ((False, "keyring parado", "reinicie"), ("unreachable", "keyring_stopped")),
            ((False, "secret service indisponivel", "consulte logs"), ("failed", "keyring_unavailable")),
        )
        for result, expected in cases:
            with self.subTest(result=result), \
                    mock.patch("asb.lifecycle.check_keyring_service", return_value=result) as chk:
                res = readiness.probe_keyring("test-c")
                self.assertEqual((res.state, res.code), expected)
                chk.assert_called_once_with("test-c", timeout=5.0)

    def test_check_keyring_service_propagates_timeout_to_every_podman_call(self) -> None:
        from asb import keyring
        with mock.patch("asb.podman.exists", return_value=True) as exists, \
                mock.patch("asb.podman.running", return_value=True) as running, \
                mock.patch("asb.keyring._inspect_keyring_container", return_value=(keyring.KEYRING_SCHEMA, {})) as insp, \
                mock.patch("asb.keyring._keyring_mount_contract_issue", return_value="") as issue, \
                mock.patch("asb.podman.run", return_value=mock.Mock(returncode=0)) as run:
            ok, _, _ = keyring.check_keyring_service("asb-keyring", timeout=7.5)
        self.assertTrue(ok)
        exists.assert_called_once_with("container", "asb-keyring", timeout=7.5)
        running.assert_called_once_with("asb-keyring", timeout=7.5)
        insp.assert_called_once_with("asb-keyring", timeout=7.5)
        issue.assert_called_once_with({})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs.get("timeout"), 7.5)

    def test_podman_exists_forwards_timeout(self) -> None:
        from asb import podman
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(podman.exists("container", "c", timeout=4.2))
        self.assertEqual(run.call_args.kwargs.get("timeout"), 4.2)


class TestIdSwapDuringDropinRestoration(unittest.TestCase):
    """Bloqueador 2 do gate, lado da restauracao.

    `_rollback_keyring_from_journal` fazia UM `_verify_ids` e chamava
    `restore_project_dropin`, cujas quatro mutacoes — mkdir, escrita, chmod e
    daemon-reload — acontecem todas depois dele. Uma identidade que deixou de
    valer nesse intervalo ainda via o arquivo ser escrito e o manager
    recarregado.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_id_swap_between_the_authorization_and_the_write_stops_the_restoration(self) -> None:
        import os
        host, unit_dir, state_dir = keyring_host(self.tmp, with_dropin=True)
        dropin = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        self.assertTrue(dropin.is_file(), "fixture nao criou o drop-in")

        adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertFalse(dropin.exists(), "a adocao nao removeu o drop-in")
        original_id = host.containers[KEYRING]["id"]

        swapped: list[str] = []
        real_mkdir = os.mkdir

        def mkdir_then_swap(path, *a, **kw):
            # O `mkdir` do `.d` e a PRIMEIRA mutacao da restauracao. Trocar o
            # container aqui deixa a escrita, o chmod e o reload adiante sob
            # uma identidade que ja nao existe.
            real_mkdir(path, *a, **kw)
            if not swapped and "podman-restart.service.d" in os.fspath(path):
                host.swap(KEYRING)
                swapped.append(host.containers[KEYRING]["id"])

        with mock.patch("os.mkdir", side_effect=mkdir_then_swap), \
                self.assertRaises((ValueError, RuntimeError)) as cm:
            rollback_kr(host, self.tmp, unit_dir, state_dir)

        self.assertTrue(swapped, "a troca nao foi provocada")
        self.assertNotEqual(swapped[0], original_id)
        self.assertRegex(str(cm.exception), "ID divergente")
        # Nenhuma das mutacoes seguintes aconteceu: nada escrito no nome do
        # drop-in, e o manager nao foi recarregado depois da troca.
        self.assertFalse(dropin.exists(), "o drop-in foi escrito sob identidade obsoleta")
        self.assertEqual(host.mutations_after_swap(), [])



if __name__ == "__main__":
    unittest.main()
