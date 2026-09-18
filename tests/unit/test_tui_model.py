"""Testes de `asb.interfaces.tui_model` (Tarefa 10): a arvore pura da TUI.

`build_tree` nao toca disco, Git, Podman, SSH nem curses: recebe projetos,
checkouts ja enriquecidos e sessoes ja reconciliadas, e devolve linhas
prontas para desenhar.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.model import CheckoutId, CheckoutKind  # noqa: E402
from asb.interfaces.tui_model import (  # noqa: E402
    CheckoutView, RowKind, TreeRow, UnregisteredView, build_tree, sanitize,
)
from asb.projects.model import Project, ProjectId  # noqa: E402
from asb.runtime.sandbox import WorkspaceStatus  # noqa: E402
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, SessionId, SessionState,
)

P_ALPHA = ProjectId("p-alpha")
P_BETA = ProjectId("p-beta")


def _project(pid: ProjectId, primary: str) -> Project:
    return Project(id=pid, primary=Path(primary), integration_branch="main",
                   worktree_root=Path(primary + "-worktrees"))


def _checkout(cid: str, pid: ProjectId, path: str, *,
              kind=CheckoutKind.PRIMARY, branch="main", detached=False,
              host_branch=False, status=WorkspaceStatus.READY, reason=None,
              error=None) -> CheckoutView:
    return CheckoutView(
        checkout_id=CheckoutId(cid), project_id=pid, source_path=Path(path),
        workspace=f"ws-{cid}", kind=kind, status=status, branch=branch,
        detached=detached, host_branch=host_branch, reason=reason,
        error=error)


def _session(sid: str, cid: str, title: str,
             state=SessionState.RUNNING,
             agent=AgentKind.CODEX) -> AgentSession:
    return AgentSession(
        id=SessionId(sid), checkout_id=CheckoutId(cid), agent=agent,
        cwd=Path("/sandbox/repo"), title=title, state=state,
        terminal_id=None, provider_session_id=None, last_healthy_at=None)


def _keys(rows) -> list[str]:
    return [row.key for row in rows]


class TestTreeShape(unittest.TestCase):
    def test_projects_are_ordered_by_primary_path_not_input_order(self):
        rows = build_tree(
            [_project(P_BETA, "/src/zeta"), _project(P_ALPHA, "/src/alpha")],
            [], [])
        projects = [r for r in rows if r.kind is RowKind.PROJECT]
        self.assertEqual([r.project_id for r in projects], [P_ALPHA, P_BETA])
        self.assertIn("alpha", projects[0].text)

    def test_primary_badge_comes_from_the_kind_never_the_branch(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-wt", P_ALPHA, "/src/alpha-worktrees/x",
                       kind=CheckoutKind.WORKTREE, branch="main"),
             _checkout("c-pri", P_ALPHA, "/src/alpha", branch="feature/x")],
            [])
        checkouts = [r for r in rows if r.kind is RowKind.CHECKOUT]
        self.assertEqual([r.checkout_id for r in checkouts], ["c-pri", "c-wt"])
        self.assertIn("[primary]", checkouts[0].text)
        self.assertIn("feature/x", checkouts[0].text)
        self.assertIn("[worktree]", checkouts[1].text)
        self.assertNotIn("[primary]", checkouts[1].text)

    def test_linked_worktrees_follow_the_primary_sorted_by_path(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-wtb", P_ALPHA, "/src/alpha-worktrees/b",
                       kind=CheckoutKind.WORKTREE, branch="b"),
             _checkout("c-wta", P_ALPHA, "/src/alpha-worktrees/a",
                       kind=CheckoutKind.WORKTREE, branch="a"),
             _checkout("c-pri", P_ALPHA, "/src/alpha")],
            [])
        self.assertEqual(_keys(rows), ["p:p-alpha", "c:c-pri", "c:c-wta",
                                       "c:c-wtb"])
        self.assertEqual({r.depth for r in rows[1:]}, {1})
        self.assertIn("/src/alpha-worktrees/a", rows[2].text)

    def test_many_sessions_nest_under_their_checkout(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-pri", P_ALPHA, "/src/alpha")],
            [_session("s-2", "c-pri", "second", agent=AgentKind.CLAUDE),
             _session("s-1", "c-pri", "first"),
             _session("s-9", "c-unknown", "orphan")])
        sessions = [r for r in rows if r.kind is RowKind.SESSION]
        self.assertEqual([r.session_id for r in sessions], ["s-1", "s-2"])
        self.assertEqual({r.depth for r in sessions}, {2})
        self.assertEqual({r.checkout_id for r in sessions}, {"c-pri"})
        self.assertIn("claude", sessions[1].text)
        self.assertNotIn("orphan", " ".join(r.text for r in rows))

    def test_detached_head_shows_the_commit(self):
        [_, row] = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-pri", P_ALPHA, "/src/alpha", branch="abc1234",
                       detached=True)], [])
        self.assertIn("(detached abc1234)", row.text)
        self.assertIn("[primary]", row.text)

    def test_unknown_and_host_branches_are_marked(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-pri", P_ALPHA, "/src/alpha", branch=None),
             _checkout("c-wt", P_ALPHA, "/src/alpha-worktrees/x",
                       kind=CheckoutKind.WORKTREE, branch="topic",
                       host_branch=True, status=WorkspaceStatus.ABSENT)],
            [])
        self.assertIn("(branch ?)", rows[1].text)
        self.assertIn("topic (host)", rows[2].text)
        self.assertIn("absent", rows[2].text)

    def test_unavailable_reason_and_error_marker_are_shown(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-pri", P_ALPHA, "/src/alpha",
                       status=WorkspaceStatus.UNAVAILABLE,
                       reason="container parado", error="reconcile: boom")],
            [], project_errors={})
        self.assertIn("unavailable: container parado", rows[1].text)
        self.assertIn("!! reconcile: boom", rows[1].text)

    def test_a_project_error_marks_the_project_row(self):
        rows = build_tree([_project(P_ALPHA, "/src/alpha")], [], [],
                          project_errors={P_ALPHA: "registry broke"})
        self.assertIn("!! registry broke", rows[0].text)

    def test_an_empty_project_shows_a_note_that_cannot_be_selected(self):
        rows = build_tree([_project(P_ALPHA, "/src/alpha")], [], [])
        self.assertEqual([r.kind for r in rows],
                         [RowKind.PROJECT, RowKind.NOTE])
        self.assertTrue(rows[0].selectable)
        self.assertFalse(rows[1].selectable)
        self.assertIn("no checkouts", rows[1].text)


class TestCollapse(unittest.TestCase):
    def setUp(self):
        self.args = (
            [_project(P_ALPHA, "/src/alpha"), _project(P_BETA, "/src/beta")],
            [_checkout("c-a", P_ALPHA, "/src/alpha"),
             _checkout("c-b", P_BETA, "/src/beta")],
            [_session("s-a", "c-a", "a"), _session("s-b", "c-b", "b")])

    def test_everything_is_expanded_by_default(self):
        rows = build_tree(*self.args)
        self.assertEqual(_keys(rows), ["p:p-alpha", "c:c-a", "s:s-a",
                                       "p:p-beta", "c:c-b", "s:s-b"])
        self.assertTrue(rows[0].expanded)
        self.assertIsNone(rows[2].expanded)

    def test_a_collapsed_project_hides_its_checkouts_and_sessions(self):
        rows = build_tree(*self.args, collapsed=frozenset({"p:p-alpha"}))
        self.assertEqual(_keys(rows), ["p:p-alpha", "p:p-beta", "c:c-b",
                                       "s:s-b"])
        self.assertFalse(rows[0].expanded)

    def test_a_collapsed_checkout_hides_only_its_sessions(self):
        rows = build_tree(*self.args, collapsed=frozenset({"c:c-b"}))
        self.assertEqual(_keys(rows), ["p:p-alpha", "c:c-a", "s:s-a",
                                       "p:p-beta", "c:c-b"])
        self.assertFalse(rows[-1].expanded)


class TestStateAndStability(unittest.TestCase):
    def test_rows_show_the_reconciled_state_they_are_given(self):
        """A arvore mostra o estado que o refresh reconciliou, nao o que o
        store tinha antes: o registro reconciliado substitui o antigo."""
        project = [_project(P_ALPHA, "/src/alpha")]
        checkout = [_checkout("c-a", P_ALPHA, "/src/alpha")]
        stale = build_tree(project, checkout,
                           [_session("s-a", "c-a", "t",
                                     state=SessionState.RUNNING)])
        fresh = build_tree(project, checkout,
                           [_session("s-a", "c-a", "t",
                                     state=SessionState.EXITED_RESUMABLE)])
        self.assertEqual(stale[-1].session_state, SessionState.RUNNING)
        self.assertEqual(fresh[-1].session_state,
                         SessionState.EXITED_RESUMABLE)
        self.assertIn("exited_resumable", fresh[-1].text)

    def test_keys_are_stable_across_rebuilds_with_new_rows(self):
        project = [_project(P_ALPHA, "/src/alpha")]
        checkout = [_checkout("c-a", P_ALPHA, "/src/alpha")]
        before = build_tree(project, checkout, [_session("s-b", "c-a", "b")])
        after = build_tree(project, checkout, [_session("s-a", "c-a", "a"),
                                               _session("s-b", "c-a", "b")])
        self.assertIn("s:s-b", _keys(before))
        self.assertIn("s:s-b", _keys(after))
        self.assertNotEqual(_keys(before).index("s:s-b"),
                            _keys(after).index("s:s-b"))

    def test_rows_are_immutable_values(self):
        [row] = build_tree([_project(P_ALPHA, "/src/alpha")], [], [])[:1]
        self.assertIsInstance(row, TreeRow)
        with self.assertRaises(Exception):
            row.text = "x"  # type: ignore[misc]


class TestWorktreeMarkers(unittest.TestCase):
    """Contexto §G: worktree criado fora da TUI e checkout sumido aparecem,
    marcados, em vez de sumir da arvore."""

    def test_an_unregistered_worktree_follows_the_registered_ones(self):
        loose = UnregisteredView(P_ALPHA, Path("/src/alpha-worktrees/ext\n"),
                                 "ext")
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")],
            [_checkout("c-a", P_ALPHA, "/src/alpha")], [],
            unregistered=[loose])
        row = rows[-1]
        self.assertEqual(row.key, "u:p-alpha:/src/alpha-worktrees/ext\n")
        self.assertIs(row.kind, RowKind.CHECKOUT)
        self.assertIsNone(row.checkout_id)
        self.assertEqual(row.project_id, P_ALPHA)
        self.assertEqual(row.source_path, loose.path)
        self.assertEqual(row.text,
                         "[worktree]  ext  unregistered  "
                         "/src/alpha-worktrees/ext?")
        self.assertEqual(rows[1].source_path, Path("/src/alpha"))

    def test_an_unregistered_worktree_alone_is_not_no_checkouts(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/alpha")], [], [],
            unregistered=[UnregisteredView(P_ALPHA, Path("/w/x"), None,
                                           missing=True, prunable=True)])
        self.assertEqual(_keys(rows), ["p:p-alpha", "u:p-alpha:/w/x"])
        self.assertIn("(branch ?)", rows[1].text)
        self.assertTrue(rows[1].text.endswith("missing  prunable"))

    def test_a_detached_unregistered_worktree(self):
        [_, row] = build_tree(
            [_project(P_ALPHA, "/src/alpha")], [], [],
            unregistered=[UnregisteredView(P_ALPHA, Path("/w/x"), "abc1234",
                                           detached=True)])
        self.assertIn("(detached abc1234)", row.text)

    def test_a_registered_checkout_whose_path_is_gone_is_missing(self):
        view = CheckoutView(
            checkout_id=CheckoutId("c-a"), project_id=P_ALPHA,
            source_path=Path("/w/gone"), workspace="ws", kind=CheckoutKind.WORKTREE,
            status=WorkspaceStatus.ABSENT, branch=None, missing=True)
        [_, row] = build_tree([_project(P_ALPHA, "/src/alpha")], [view], [])
        self.assertTrue(row.text.endswith("/w/gone  missing"))

    def test_a_merged_worktree_offers_cleanup(self):
        view = CheckoutView(
            checkout_id=CheckoutId("c-a"), project_id=P_ALPHA,
            source_path=Path("/w/done"), workspace="ws",
            kind=CheckoutKind.WORKTREE, status=WorkspaceStatus.ABSENT,
            branch="topic", merged=True)
        [_, row] = build_tree([_project(P_ALPHA, "/src/alpha")], [view], [])
        self.assertTrue(row.text.endswith(
            "/w/done  merged / cleanup available"))
        [_, plain] = build_tree([_project(P_ALPHA, "/src/alpha")],
                                [replace(view, merged=False)], [])
        self.assertNotIn("merged", plain.text)


class TestSanitize(unittest.TestCase):
    def test_control_characters_become_a_visible_placeholder(self):
        self.assertEqual(sanitize("a\nb\tc\x1b[31md\x7f\x9be‮f"),
                         "a?b?c?[31md??e?f")

    def test_a_hostile_title_reaches_no_row_raw(self):
        rows = build_tree(
            [_project(P_ALPHA, "/src/al\x1bpha")],
            [_checkout("c-a", P_ALPHA, "/src/alpha", branch="ma\rin",
                       reason="r\x07", status=WorkspaceStatus.UNAVAILABLE)],
            [_session("s-a", "c-a", "evil\n\x1b[2Jtitle")])
        for row in rows:
            with self.subTest(key=row.key):
                self.assertFalse(
                    any(ord(ch) < 32 or 127 <= ord(ch) < 160
                        for ch in row.text), repr(row.text))
        self.assertIn("evil??[2Jtitle", rows[-1].text)


if __name__ == "__main__":
    unittest.main()
