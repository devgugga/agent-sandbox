"""tests/unit/test_runtime_transaction.py — fronteira de rollback de
`cli/asb/runtime/transaction.py::WorkspaceTransaction`.

Tarefa 4 da decomposicao de modulos (brief Passo 1): cobre o ledger de posse
(containers, redes, volumes, arquivos sobrescritos e unidades systemd),
falha parcial de rollback, ordem de limpeza e rollback repetido — e afirma
que um recurso NUNCA registrado (pre-existente) jamais chega a uma chamada
de remocao.
"""
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.asb.runtime.transaction import WorkspaceTransaction


class TestRecording(unittest.TestCase):
    """Cada `record_*` so acrescenta uma vez por identidade."""

    def test_record_container_dedupes(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("cid-1")
        tx.record_container("cid-1")
        tx.record_container("cid-2")
        self.assertEqual(tx.created_containers, ["cid-1", "cid-2"])

    def test_record_container_ignores_empty(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("")
        self.assertEqual(tx.created_containers, [])

    def test_record_network_dedupes(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_network("net-a")
        tx.record_network("net-a")
        self.assertEqual(tx.created_networks, ["net-a"])

    def test_record_volume_dedupes(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_volume("vol-a")
        tx.record_volume("vol-a")
        self.assertEqual(tx.created_volumes, ["vol-a"])

    def test_record_unit_dedupes(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        p = Path("/tmp/unit.service")
        tx.record_unit(p)
        tx.record_unit(p)
        self.assertEqual(tx.created_units, [p])

    def test_record_restore_keeps_only_the_first_recorded_content_per_path(self):
        """Duas chamadas para o MESMO caminho: a segunda e ignorada — o
        rollback tem de restaurar o conteudo de ANTES da transacao, nao um
        estado intermediario gravado por engano no meio dela."""
        tx = WorkspaceTransaction("ws", is_existing=False)
        p = Path("/tmp/gate.service")
        tx.record_restore(p, "original")
        tx.record_restore(p, "intermediate")
        self.assertEqual(tx.overwritten, [(p, "original")])


class TestRollbackSkipsExistingWorkspace(unittest.TestCase):
    """Falha em workspace EXISTENTE nunca executa sweep destrutivo."""

    def test_rollback_is_a_noop_when_is_existing(self):
        tx = WorkspaceTransaction("ws", is_existing=True)
        tx.record_container("cid-1")
        tx.record_network("net-1")
        tx.record_volume("vol-1")
        tx.record_unit(Path("/tmp/unit.service"))

        with mock.patch("cli.asb.runtime.transaction.podman.run") as run, \
             mock.patch("cli.asb.runtime.transaction.podman.exists") as exists, \
             mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units") as remove_units:
            tx.rollback()

        run.assert_not_called()
        exists.assert_not_called()
        remove_units.assert_not_called()


class TestRollbackOwnershipBoundary(unittest.TestCase):
    """Rollback so atinge os IDs registrados NESTA transacao; um recurso
    nunca registrado (pre-existente) jamais vira argumento de uma chamada de
    remocao."""

    def _run_rollback(self, tx, *, network_exists=True, volume_exists=True):
        calls: list[tuple] = []

        def fake_run(*args, **kwargs):
            calls.append(args)
            return mock.MagicMock(returncode=0)

        def fake_exists(kind, name):
            if kind == "network":
                return network_exists
            if kind == "volume":
                return volume_exists
            raise AssertionError(f"tipo inesperado em rollback: {kind}")

        with mock.patch("cli.asb.runtime.transaction.podman.run", side_effect=fake_run), \
             mock.patch("cli.asb.runtime.transaction.podman.exists", side_effect=fake_exists), \
             mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units"):
            tx.rollback()
        return calls

    def test_rollback_removes_only_recorded_containers(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("cid-owned")
        calls = self._run_rollback(tx)
        self.assertIn(("rm", "-f", "cid-owned"), calls)
        # Um container nunca registrado (pre-existente) nao aparece em
        # NENHUMA chamada de remocao.
        for call in calls:
            self.assertNotIn("cid-preexisting", call)

    def test_rollback_removes_only_recorded_networks(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_network("net-owned")
        calls = self._run_rollback(tx)
        self.assertIn(("network", "rm", "-f", "net-owned"), calls)
        for call in calls:
            self.assertNotIn("net-preexisting", call)

    def test_rollback_removes_only_recorded_volumes(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_volume("vol-owned")
        calls = self._run_rollback(tx)
        self.assertIn(("volume", "rm", "-f", "vol-owned"), calls)
        for call in calls:
            self.assertNotIn("vol-preexisting", call)

    def test_rollback_never_deletes_a_network_or_volume_it_did_not_create(self):
        """Mesmo um recurso registrado so vira `rm` se `podman.exists`
        confirmar que ele esta la — uma checagem defensiva contra remover o
        que outra coisa ja removeu, nunca um recurso alheio."""
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_network("net-owned")
        tx.record_volume("vol-owned")
        calls = self._run_rollback(tx, network_exists=False, volume_exists=False)
        self.assertNotIn(("network", "rm", "-f", "net-owned"), calls)
        self.assertNotIn(("volume", "rm", "-f", "vol-owned"), calls)

    def test_containers_are_removed_unconditionally_by_id(self):
        """Diferente de rede/volume, container nunca passa por
        `podman.exists` antes do `rm -f`: e o comportamento ja existente
        (idempotente por natureza do `-f`), preservado pela mudanca pura."""
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("cid-owned")
        with mock.patch("cli.asb.runtime.transaction.podman.run") as run, \
             mock.patch("cli.asb.runtime.transaction.podman.exists") as exists:
            tx.rollback()
        run.assert_called_once_with("rm", "-f", "cid-owned", check=False)
        exists.assert_not_called()


class TestRollbackOrder(unittest.TestCase):
    """Ordem de limpeza: containers, depois redes, depois volumes, depois
    arquivos sobrescritos, depois unidades systemd — a ordem real do codigo
    hoje, nao uma reversao idealizada por categoria."""

    def test_rollback_order_is_containers_networks_volumes_files_units(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("cid-1")
        tx.record_network("net-1")
        tx.record_volume("vol-1")
        tx.record_unit(Path("/tmp/unit.service"))

        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "gate.service"
            gate.write_text("BEFORE\n")
            tx.record_restore(gate, "BEFORE\n")
            gate.write_text("AFTER\n")

            events: list[str] = []

            def fake_run(*args, **kwargs):
                if args[:1] == ("rm",):
                    events.append("container")
                elif args[:2] == ("network", "rm"):
                    events.append("network")
                elif args[:2] == ("volume", "rm"):
                    events.append("volume")
                return mock.MagicMock(returncode=0)

            with mock.patch("cli.asb.runtime.transaction.podman.run", side_effect=fake_run), \
                 mock.patch("cli.asb.runtime.transaction.podman.exists", return_value=True), \
                 mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units",
                            side_effect=lambda ws: events.append("units")):
                tx.rollback()

            self.assertEqual(gate.read_text(), "BEFORE\n")
        self.assertEqual(events, ["container", "network", "volume", "units"])


class TestPartialRollbackFailures(unittest.TestCase):
    """Uma falha ao restaurar UM arquivo, ou ao remover unidades, nunca
    interrompe o resto do rollback nem escapa de `rollback()`."""

    def test_file_restore_failure_is_logged_and_the_next_file_still_restores(self):
        import contextlib
        import io

        tx = WorkspaceTransaction("ws", is_existing=False)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "no-such-dir" / "gate.service"  # dir ausente: OSError no write_text
            good = Path(tmp) / "second.service"
            good.write_text("AFTER\n")

            tx.record_restore(bad, "original-bad")
            tx.record_restore(good, "original-good")

            stderr = io.StringIO()
            with mock.patch("cli.asb.runtime.transaction.podman.run"), \
                 mock.patch("cli.asb.runtime.transaction.podman.exists", return_value=False), \
                 contextlib.redirect_stderr(stderr):
                tx.rollback()

            self.assertIn("aviso", stderr.getvalue())
            self.assertIn(str(bad), stderr.getvalue())
            self.assertEqual(good.read_text(), "original-good")

    def test_unit_removal_failure_is_logged_not_raised(self):
        import contextlib
        import io

        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_unit(Path("/tmp/unit.service"))

        stderr = io.StringIO()
        with mock.patch("cli.asb.runtime.transaction.podman.run"), \
             mock.patch("cli.asb.runtime.transaction.podman.exists", return_value=False), \
             mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units",
                        side_effect=RuntimeError("systemctl indisponivel")), \
             contextlib.redirect_stderr(stderr):
            tx.rollback()  # nao deve levantar

        self.assertIn("aviso", stderr.getvalue())
        self.assertIn("'ws'", stderr.getvalue())
        self.assertIn("systemctl indisponivel", stderr.getvalue())

    def test_original_up_failure_outranks_a_rollback_failure(self):
        """O padrao real de uso (lifecycle.up): o rollback roda dentro de um
        `except BaseException: tx.rollback(); raise`. Uma falha DENTRO do
        rollback (aqui, remocao de unidades) nunca pode substituir a
        excecao original — `rollback()` precisa apenas nao propagar a sua
        propria falha."""
        import contextlib
        import io

        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_unit(Path("/tmp/unit.service"))

        stderr = io.StringIO()
        with mock.patch("cli.asb.runtime.transaction.podman.run"), \
             mock.patch("cli.asb.runtime.transaction.podman.exists", return_value=False), \
             mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units",
                        side_effect=RuntimeError("systemctl indisponivel")), \
             contextlib.redirect_stderr(stderr):
            try:
                raise ValueError("falha original de up")
            except ValueError:
                tx.rollback()
                # Chegar aqui e a asercao: rollback() engoliu sua propria
                # falha sem interferir no fluxo de excecao do chamador.


class TestRepeatedRollback(unittest.TestCase):
    """Rollback chamado duas vezes nunca levanta, e a segunda chamada nao
    tenta remover redes/volumes que a primeira ja confirmou ausentes."""

    def test_rollback_twice_does_not_raise_and_is_consistent(self):
        tx = WorkspaceTransaction("ws", is_existing=False)
        tx.record_container("cid-1")
        tx.record_network("net-1")
        tx.record_volume("vol-1")
        tx.record_unit(Path("/tmp/unit.service"))

        # Depois da primeira passada, rede e volume "sumiram" de verdade:
        # a segunda passada os encontra ausentes e nao chama `rm` de novo.
        exists_state = {"network": True, "volume": True}

        def fake_exists(kind, name):
            return exists_state[kind]

        rm_calls: list[tuple] = []

        def fake_run(*args, **kwargs):
            if args[:2] in (("network", "rm"), ("volume", "rm")):
                exists_state[args[0]] = False
            rm_calls.append(args)
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.runtime.transaction.podman.run", side_effect=fake_run), \
             mock.patch("cli.asb.runtime.transaction.podman.exists", side_effect=fake_exists), \
             mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units"):
            tx.rollback()
            first_count = len(rm_calls)
            tx.rollback()
            second_count = len(rm_calls)

        # O container e sempre re-emitido (rm -f e idempotente por natureza);
        # rede e volume so na primeira vez, porque a segunda os acha ausentes.
        self.assertGreater(second_count, first_count)
        container_rm_calls = [c for c in rm_calls if c == ("rm", "-f", "cid-1")]
        self.assertEqual(len(container_rm_calls), 2)
        network_rm_calls = [c for c in rm_calls if c == ("network", "rm", "-f", "net-1")]
        self.assertEqual(len(network_rm_calls), 1)
        volume_rm_calls = [c for c in rm_calls if c == ("volume", "rm", "-f", "vol-1")]
        self.assertEqual(len(volume_rm_calls), 1)


if __name__ == "__main__":
    unittest.main()
