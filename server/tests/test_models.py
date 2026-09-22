"""server/tests/test_models.py — the wire contract (Task 3).

Covers: every model serializes and deserializes with all required fields
present; `Snapshot` -> `TreeResponse` for a snapshot carrying a per-project
error, a per-checkout error, a missing checkout, both merged-evidence
labels (`merged / cleanup available` vs. `merged / cleanup pending`,
tui_model.MERGED_LABEL / PENDING_LABEL) and an unregistered worktree; and
the sanitization proof, with genuinely hostile strings (a bidi override,
a control character) rather than clean data.

Deliberately named to collide with `tests/unit/test_models.py`-shaped
suites elsewhere: `--import-mode=importlib` (Task 1) is what lets this
file and any same-named `tests/unit` file coexist.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from asb.checkouts.model import CheckoutId, CheckoutKind
from asb.interfaces.snapshot import Snapshot
from asb.interfaces.tui_model import (
    MERGED_LABEL,
    PENDING_LABEL,
    CheckoutView,
    UnregisteredView,
)
from asb.projects.model import Project, ProjectId
from asb.runtime.sandbox import WorkspaceStatus
from asb.sessions.model import AgentKind, AgentSession, SessionId, SessionState
from asb_server.models import (
    CheckoutNode,
    ProjectNode,
    SessionNode,
    TreeResponse,
    UnregisteredNode,
    tree_response,
)

# A right-to-left override: invisible, reorders whatever follows it on
# screen. React's HTML escaping does not neutralize it — only `sanitize`
# does (spec Section 7.3). Built with chr() rather than a literal escape so
# the raw character never sits in this source file.
BIDI_OVERRIDE = chr(0x202E)
# BEL: a plain C0 control character.
CONTROL_CHAR = chr(0x07)

PROJECT_ID = ProjectId("p-aaaaaaaa")
CHECKOUT_ID = CheckoutId("c-aaaaaaaa")
SESSION_ID = SessionId("s-aaaaaaaa")


def _project(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "id": PROJECT_ID, "primary": Path("/repo/p"),
        "integration_branch": "main", "worktree_root": Path("/repo/worktrees")}
    defaults.update(overrides)
    return Project(**defaults)


def _checkout(**overrides: object) -> CheckoutView:
    defaults: dict[str, object] = {
        "checkout_id": CHECKOUT_ID, "project_id": PROJECT_ID,
        "source_path": Path("/repo/p"), "workspace": "ws-1",
        "kind": CheckoutKind.PRIMARY, "status": WorkspaceStatus.READY,
        "branch": "main"}
    defaults.update(overrides)
    return CheckoutView(**defaults)


def _session(**overrides: object) -> AgentSession:
    defaults: dict[str, object] = {
        "id": SESSION_ID, "checkout_id": CHECKOUT_ID, "agent": AgentKind.CLAUDE,
        "cwd": Path("/repo/p"), "title": "review PR", "state": SessionState.RUNNING,
        "terminal_id": None, "provider_session_id": None, "last_healthy_at": None}
    defaults.update(overrides)
    return AgentSession(**defaults)


def _snapshot(**overrides: object) -> Snapshot:
    defaults: dict[str, object] = {
        "projects": (), "checkouts": (), "sessions": (), "unregistered": (),
        "project_errors": {}, "registry_error": None}
    defaults.update(overrides)
    return Snapshot(**defaults)


def _label_for(*, merged: bool, missing: bool) -> str | None:
    """The exact decision `tui_model.build_tree`/`_checkout_text` makes
    (cli/asb/interfaces/tui_model.py): only from `merged` and `missing`,
    both present on `CheckoutNode` — the finding this test proves."""
    if not merged:
        return None
    return PENDING_LABEL if missing else MERGED_LABEL


class TestModelsSerializeAndDeserialize(unittest.TestCase):
    """Every model round-trips through JSON with every field present."""

    def test_session_node_round_trips(self):
        node = SessionNode(
            id="s-aaaaaaaa", agent=AgentKind.CODEX, state=SessionState.RUNNING,
            title="t", cwd="/repo", terminal_id="t-aaaaaaaa",
            started_at=datetime(2026, 1, 1, tzinfo=UTC), ended_at=None,
            last_healthy_at=None)
        restored = SessionNode.model_validate_json(node.model_dump_json())
        self.assertEqual(restored, node)

    def test_checkout_node_round_trips(self):
        node = CheckoutNode(
            id="c-aaaaaaaa", kind=CheckoutKind.WORKTREE, path="/repo/wt",
            workspace="ws-1", status=WorkspaceStatus.UNAVAILABLE,
            reason="offline", branch="feature", detached=False,
            host_branch=False, missing=False, merged=False, error=None,
            sessions=[])
        restored = CheckoutNode.model_validate_json(node.model_dump_json())
        self.assertEqual(restored, node)

    def test_unregistered_node_round_trips(self):
        node = UnregisteredNode(
            path="/repo/loose", branch="wip", detached=False,
            missing=False, prunable=True)
        restored = UnregisteredNode.model_validate_json(node.model_dump_json())
        self.assertEqual(restored, node)

    def test_project_node_round_trips(self):
        node = ProjectNode(
            id="p-aaaaaaaa", name="p", primary_path="/repo/p",
            integration_branch="main", error=None, checkouts=[],
            unregistered=[])
        restored = ProjectNode.model_validate_json(node.model_dump_json())
        self.assertEqual(restored, node)

    def test_tree_response_round_trips(self):
        response = TreeResponse(read_at=datetime(2026, 1, 1, tzinfo=UTC), projects=[])
        restored = TreeResponse.model_validate_json(response.model_dump_json())
        self.assertEqual(restored, response)

    def test_required_fields_are_actually_required(self):
        # Every field on the wire contract's leaf model is required: a
        # response missing one is a contract violation, not a default.
        schema = SessionNode.model_json_schema()
        self.assertEqual(
            set(schema["required"]),
            {"id", "agent", "state", "title", "cwd", "terminal_id",
             "started_at", "ended_at", "last_healthy_at"})


class TestSnapshotConversion(unittest.TestCase):
    """`tree_response`: a snapshot carrying a per-project error, a
    per-checkout error, a missing checkout, both merged labels, and an
    unregistered worktree."""

    def test_covers_every_conversion_scenario(self):
        project = _project()
        checkout_ready = _checkout(
            checkout_id=CheckoutId("c-ready0001"), kind=CheckoutKind.PRIMARY,
            status=WorkspaceStatus.READY, branch="main")
        checkout_error = _checkout(
            checkout_id=CheckoutId("c-error0001"), kind=CheckoutKind.WORKTREE,
            status=WorkspaceStatus.UNAVAILABLE, reason="podman down",
            error="reconcile failed")
        checkout_missing = _checkout(
            checkout_id=CheckoutId("c-missing01"), kind=CheckoutKind.WORKTREE,
            status=WorkspaceStatus.ABSENT, missing=True)
        checkout_merged_available = _checkout(
            checkout_id=CheckoutId("c-merged001"), kind=CheckoutKind.WORKTREE,
            merged=True, missing=False)
        checkout_merged_pending = _checkout(
            checkout_id=CheckoutId("c-pending01"), kind=CheckoutKind.WORKTREE,
            merged=True, missing=True)
        session = _session(checkout_id=CheckoutId("c-ready0001"))
        unregistered = UnregisteredView(
            project_id=PROJECT_ID, path=Path("/repo/loose"), branch="wip",
            detached=False, missing=False, prunable=True)
        snapshot = _snapshot(
            projects=(project,),
            checkouts=(checkout_ready, checkout_error, checkout_missing,
                       checkout_merged_available, checkout_merged_pending),
            sessions=(session,),
            unregistered=(unregistered,),
            project_errors={PROJECT_ID: "discover failed"})

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        self.assertEqual(len(response.projects), 1)
        node = response.projects[0]
        self.assertEqual(node.error, "discover failed")
        self.assertEqual(len(node.unregistered), 1)
        self.assertTrue(node.unregistered[0].prunable)
        by_id = {c.id: c for c in node.checkouts}
        self.assertEqual(len(by_id), 5)

        self.assertEqual(by_id["c-error0001"].error, "reconcile failed")
        self.assertEqual(by_id["c-error0001"].reason, "podman down")

        self.assertTrue(by_id["c-missing01"].missing)
        self.assertFalse(by_id["c-missing01"].merged)

        # The client reproduces MERGED_LABEL vs. PENDING_LABEL purely from
        # `merged` and `missing` (see tui_model.build_tree's own logic) —
        # both are present on CheckoutNode.
        available = by_id["c-merged001"]
        self.assertTrue(available.merged)
        self.assertFalse(available.missing)
        self.assertEqual(
            _label_for(merged=available.merged, missing=available.missing),
            MERGED_LABEL)
        pending = by_id["c-pending01"]
        self.assertTrue(pending.merged)
        self.assertTrue(pending.missing)
        self.assertEqual(
            _label_for(merged=pending.merged, missing=pending.missing),
            PENDING_LABEL)

        self.assertEqual(len(by_id["c-ready0001"].sessions), 1)
        self.assertEqual(by_id["c-ready0001"].sessions[0].title, "review PR")

    def test_registry_error_is_the_callers_503_not_a_field(self):
        # A registry failure is spec Section 7.6's 503, decided by the
        # caller before it ever reaches tree_response; Snapshot's empty
        # collections convert to an empty tree either way.
        snapshot = _snapshot(registry_error="boom")
        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(response.projects, [])


class TestSanitization(unittest.TestCase):
    """Proves sanitize() runs on every operator-/Git-sourced string with a
    genuinely hostile input, not by calling the converter on clean data."""

    def test_branch_with_bidi_override_is_sanitized(self):
        # read_branch never sanitizes (cli/asb/interfaces/snapshot.py's
        # `_checkout` stores Git's branch name verbatim) — this field is
        # unprotected until the converter runs.
        hostile = f"main{BIDI_OVERRIDE}evil"
        checkout = _checkout(branch=hostile)
        snapshot = _snapshot(projects=(_project(),), checkouts=(checkout,))

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        branch = response.projects[0].checkouts[0].branch
        self.assertNotIn(BIDI_OVERRIDE, branch)
        self.assertEqual(branch, "main?evil")

    def test_workspace_with_bidi_override_is_sanitized(self):
        # CheckoutBinding.workspace is read verbatim from the on-disk
        # registry file (cli/asb/projects/registry.py's loader does not
        # validate its content) — an operator-editable field, not an
        # internally generated id, so it is unprotected until the
        # converter runs (review finding, Task 3 fix round 1).
        hostile = f"ws{BIDI_OVERRIDE}-1"
        checkout = _checkout(workspace=hostile)
        snapshot = _snapshot(projects=(_project(),), checkouts=(checkout,))

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        workspace = response.projects[0].checkouts[0].workspace
        self.assertNotIn(BIDI_OVERRIDE, workspace)
        self.assertEqual(workspace, "ws?-1")

    def test_session_title_with_control_character_is_sanitized(self):
        hostile = f"bell{CONTROL_CHAR}here"
        checkout = _checkout()
        session = _session(title=hostile)
        snapshot = _snapshot(
            projects=(_project(),), checkouts=(checkout,), sessions=(session,))

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        title = response.projects[0].checkouts[0].sessions[0].title
        self.assertNotIn(CONTROL_CHAR, title)
        self.assertEqual(title, "bell?here")

    def test_project_and_checkout_paths_are_sanitized(self):
        hostile_primary = Path(f"/repo/{BIDI_OVERRIDE}p")
        hostile_checkout = Path(f"/repo/{CONTROL_CHAR}wt")
        project = _project(primary=hostile_primary)
        checkout = _checkout(source_path=hostile_checkout)
        snapshot = _snapshot(projects=(project,), checkouts=(checkout,))

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        node = response.projects[0]
        self.assertNotIn(BIDI_OVERRIDE, node.primary_path)
        self.assertNotIn(BIDI_OVERRIDE, node.name)
        self.assertNotIn(CONTROL_CHAR, node.checkouts[0].path)

    def test_unregistered_branch_is_sanitized(self):
        hostile = f"wip{BIDI_OVERRIDE}"
        unregistered = UnregisteredView(
            project_id=PROJECT_ID, path=Path("/repo/loose"), branch=hostile)
        snapshot = _snapshot(
            projects=(_project(),), unregistered=(unregistered,))

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        self.assertNotIn(BIDI_OVERRIDE, response.projects[0].unregistered[0].branch)

    def test_per_project_and_per_checkout_errors_are_sanitized(self):
        hostile_project_error = f"registry{BIDI_OVERRIDE}broke"
        hostile_checkout_error = f"reconcile{CONTROL_CHAR}failed"
        checkout = _checkout(error=hostile_checkout_error)
        snapshot = _snapshot(
            projects=(_project(),), checkouts=(checkout,),
            project_errors={PROJECT_ID: hostile_project_error})

        response = tree_response(snapshot, read_at=datetime(2026, 1, 1, tzinfo=UTC))

        node = response.projects[0]
        self.assertNotIn(BIDI_OVERRIDE, node.error)
        self.assertNotIn(CONTROL_CHAR, node.checkouts[0].error)


if __name__ == "__main__":
    unittest.main()
