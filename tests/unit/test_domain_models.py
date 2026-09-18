import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.model import (  # noqa: E402
    Checkout, CheckoutId, CheckoutKind, CheckoutState,
)
from asb.projects.model import Project, ProjectId  # noqa: E402
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, ProviderSessionId, SessionId, SessionState,
    TerminalId,
)


class TestIdentifiers(unittest.TestCase):
    def test_rejects_paths_whitespace_and_shell_text(self):
        for value in ("", "../x", "a/b", "two words", "x;rm"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SessionId(value)

    def test_accepts_generated_identifier(self):
        self.assertEqual(str(SessionId("s-0123456789abcdef")),
                         "s-0123456789abcdef")

    def test_project_id_rejects_and_accepts(self):
        with self.assertRaises(ValueError):
            ProjectId("../x")
        self.assertEqual(str(ProjectId("p-1")), "p-1")

    def test_checkout_id_rejects_and_accepts(self):
        with self.assertRaises(ValueError):
            CheckoutId("a/b")
        self.assertEqual(str(CheckoutId("c-1")), "c-1")

    def test_terminal_id_rejects_and_accepts(self):
        with self.assertRaises(ValueError):
            TerminalId("tmux 2")
        self.assertEqual(str(TerminalId("tmux-2")), "tmux-2")

    def test_provider_session_id_rejects_empty_whitespace_and_shell_text(self):
        for value in ("", "   ", "two words", "x;rm", "x`y`", "x$(y)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ProviderSessionId(value)

    def test_provider_session_id_accepts_values_the_id_regex_would_reject(self):
        # Provider-native ids are not lowercase-64 like our own ids: mixed
        # case and length above 64 must still be accepted.
        value = "Session_ABC-123-" + ("x" * 60)
        self.assertEqual(str(ProviderSessionId(value)), value)

    def test_provider_session_id_rejects_leading_dash(self):
        # A value beginning with "-" would be parsed as a CLI flag once it
        # lands in a driver's resume() argv (e.g. "--dangerously-skip-
        # permissions"). The id comes from agent-writable files, so this
        # must be rejected here, not left to callers.
        for value in ("-x", "--flag"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ProviderSessionId(value)


class TestEnumMembership(unittest.TestCase):
    def test_session_state_is_exactly_the_named_set(self):
        self.assertEqual(
            {member.value for member in SessionState},
            {"starting", "running", "detached", "suspended",
             "exited_resumable", "completed", "recovery_required", "failed"},
        )

    def test_checkout_state_is_exactly_the_named_set(self):
        self.assertEqual({member.value for member in CheckoutState},
                          {"clean", "dirty", "detached"})

    def test_checkout_kind_is_exactly_the_named_set(self):
        self.assertEqual({member.value for member in CheckoutKind},
                          {"primary", "worktree"})

    def test_agent_kind_is_exactly_the_named_set(self):
        self.assertEqual({member.value for member in AgentKind},
                          {"codex", "claude", "antigravity"})


class TestDomainRelationships(unittest.TestCase):
    def test_primary_is_a_checkout_kind_not_a_branch(self):
        project = Project(ProjectId("p-1"), Path("/repo"), "develop",
                          Path("/worktrees"))
        checkout = Checkout(CheckoutId("c-1"), project.id, Path("/repo"),
                            CheckoutKind.PRIMARY, "feat/x",
                            CheckoutState.CLEAN, "ws-1")
        self.assertEqual(checkout.branch, "feat/x")
        self.assertEqual(checkout.kind, CheckoutKind.PRIMARY)

    def test_new_session_starts_clean_with_no_terminal_or_provider_link(self):
        session = AgentSession.new(CheckoutId("c-1"), AgentKind.CODEX,
                                   Path("/repo"), "Plan work")
        self.assertTrue(str(session.id).startswith("s-"))
        self.assertEqual(session.state, SessionState.STARTING)
        self.assertIsNone(session.terminal_id)
        self.assertIsNone(session.provider_session_id)
        self.assertIsNone(session.last_healthy_at)

    def test_session_identity_is_independent_of_terminal(self):
        session = AgentSession.new(CheckoutId("c-1"), AgentKind.CODEX,
                                   Path("/repo"), "Plan work")
        changed = session.with_state(SessionState.DETACHED,
                                     terminal_id="tmux-2")
        self.assertEqual(changed.id, session.id)
        self.assertNotEqual(changed.terminal_id, session.terminal_id)
        self.assertIsInstance(changed.terminal_id, TerminalId)
        # with_state never mutates the record it was called on.
        self.assertIsNone(session.terminal_id)
        self.assertEqual(session.state, SessionState.STARTING)

    def test_with_state_wraps_a_raw_provider_session_id(self):
        session = AgentSession.new(CheckoutId("c-1"), AgentKind.CODEX,
                                   Path("/repo"), "Plan work")
        changed = session.with_state(SessionState.RUNNING,
                                     provider_session_id="raw-provider-id")
        self.assertIsInstance(changed.provider_session_id, ProviderSessionId)
        self.assertEqual(changed.provider_session_id, "raw-provider-id")
        self.assertIsNone(session.provider_session_id)

    def test_with_state_rejects_an_invalid_provider_session_id(self):
        session = AgentSession.new(CheckoutId("c-1"), AgentKind.CODEX,
                                   Path("/repo"), "Plan work")
        with self.assertRaises(ValueError):
            session.with_state(SessionState.RUNNING, provider_session_id="x;rm")


if __name__ == "__main__":
    unittest.main()
