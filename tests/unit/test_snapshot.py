"""Testes de `asb.interfaces.snapshot`: a leitura pura da arvore,
extraida de `TuiController.refresh` (Tarefa 10).

Reusa as mesmas fakes de `test_tui_controller.py` (`_Case`: registro,
runtime e gerente falsos; `SessionStore` REAL num diretorio temporario) em
vez de inventar novos mocks — a prova de que a extracao preservou o
comportamento e `test_tui_controller.py` passando sem alteracao; aqui so
testamos `read_snapshot` isolado, pelos resultados do `Snapshot`.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.git import Worktree  # noqa: E402
from asb.checkouts.manager import CheckoutError, ListedCheckout  # noqa: E402
from asb.checkouts.model import CheckoutKind  # noqa: E402
from asb.podman import PodmanError  # noqa: E402
from asb.projects.model import Project  # noqa: E402
from asb.interfaces.snapshot import read_snapshot  # noqa: E402

from test_tui_controller import (  # noqa: E402
    C_PRI, C_WT, OTHER_PROJECT, PROJECT, WORKTREE, _Case,
)


class TestReadSnapshot(_Case):
    """Cada caso chama `read_snapshot` direto (sem `TuiController`) e
    confere o `Snapshot` devolvido."""

    def snapshot(self):
        return read_snapshot(self.services(), self.checkouts,
                             self.read_branch)

    def test_a_registry_failure_returns_a_bare_reason_and_empty_collections(self):
        self.registry.list.side_effect = PodmanError("registro corrompido")
        snap = self.snapshot()
        self.assertEqual(snap.registry_error, "registro corrompido")
        self.assertEqual(snap.projects, ())
        self.assertEqual(snap.checkouts, ())
        self.assertEqual(snap.sessions, ())
        self.assertEqual(snap.unregistered, ())
        self.assertEqual(snap.project_errors, {})

    def test_a_store_failure_marks_every_checkout_but_is_not_fatal(self):
        with mock.patch.object(self.store, "list",
                               side_effect=PodmanError("store\nindisponivel")):
            snap = self.snapshot()
        self.assertIsNone(snap.registry_error)
        views = {v.checkout_id: v for v in snap.checkouts}
        self.assertIn("sessions: store", views[C_PRI].error)
        self.assertIn("sessions: store", views[C_WT].error)

    def test_one_failing_project_lands_in_project_errors_not_an_exception(self):
        self.projects.append(Project(id=OTHER_PROJECT, primary=Path("/src/b"),
                                     integration_branch="main",
                                     worktree_root=Path("/src/b-wts")))
        self.discovered[OTHER_PROJECT] = PodmanError("podman\nausente")
        snap = self.snapshot()
        self.assertEqual(snap.project_errors[OTHER_PROJECT], "podman")
        # O projeto que discovery derrubou nao esconde o outro.
        self.assertTrue(any(v.project_id == PROJECT for v in snap.checkouts))

    def test_a_checkout_missing_from_the_worktree_listing_is_flagged(self):
        self.checkouts.list.return_value = [
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True),
        ]
        snap = self.snapshot()
        views = {v.checkout_id: v for v in snap.checkouts}
        self.assertTrue(views[C_WT].missing)
        self.assertFalse(views[C_PRI].missing)

    def test_merged_evidence_is_fresh_from_the_checkout_manager_each_read(self):
        self.checkouts.merged.return_value = True
        snap = self.snapshot()
        views = {v.checkout_id: v for v in snap.checkouts}
        self.assertEqual(views[C_WT].kind, CheckoutKind.WORKTREE)
        self.assertTrue(views[C_WT].merged)
        # Primario nunca consulta `merged`: fica no padrao.
        self.assertFalse(views[C_PRI].merged)
        self.checkouts.merged.assert_called_once_with(C_WT, "main")

    def test_an_unregistered_worktree_is_collected_without_a_binding(self):
        external = Path("/src/alpha-worktrees/external")
        self.checkouts.list.return_value = [ListedCheckout(
            external, None,
            Worktree(external, "abc123", "external", False, False), False)]
        snap = self.snapshot()
        self.assertEqual(len(snap.unregistered), 1)
        [view] = snap.unregistered
        self.assertEqual(view.project_id, PROJECT)
        self.assertEqual(view.path, external)
        self.assertEqual(view.branch, "external")
        self.assertFalse(view.detached)

    def test_a_failing_worktree_listing_marks_the_project_not_the_checkouts(self):
        self.checkouts.list.side_effect = CheckoutError("git\nquebrou")
        snap = self.snapshot()
        self.assertEqual(snap.project_errors[PROJECT], "git")
        # Os checkouts descobertos pelo runtime continuam presentes.
        self.assertEqual({v.checkout_id for v in snap.checkouts},
                         {C_PRI, C_WT})


class TestSnapshotImportsWithoutCurses(unittest.TestCase):
    """§A: `snapshot.py` e o que o futuro daemon importa; nunca pode
    arrastar `curses`, direta ou transitivamente, porque `tui.py` o
    importa no topo do arquivo (Tarefa 10)."""

    def test_the_module_imports_cleanly_when_curses_is_unavailable(self):
        cli_path = str(Path(__file__).resolve().parents[2] / "cli")
        sys.path.insert(0, cli_path)
        import asb.interfaces as interfaces
        had = hasattr(interfaces, "snapshot")
        saved = getattr(interfaces, "snapshot", None)
        with mock.patch.dict(sys.modules, {"curses": None, "_curses": None}):
            sys.modules.pop("asb.interfaces.snapshot", None)
            if had:
                delattr(interfaces, "snapshot")
            try:
                import importlib
                module = importlib.import_module("asb.interfaces.snapshot")
                self.assertTrue(hasattr(module, "read_snapshot"))
                # A prova: com `curses`/`_curses` mascarados (qualquer
                # `import curses` levantaria ImportError), o import acima
                # nao levantou — `snapshot.py` nao arrasta curses.
                self.assertIsNone(sys.modules["curses"])
            finally:
                sys.modules.pop("asb.interfaces.snapshot", None)
                if had:
                    interfaces.snapshot = saved
                elif hasattr(interfaces, "snapshot"):
                    delattr(interfaces, "snapshot")


if __name__ == "__main__":
    unittest.main()
