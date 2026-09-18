"""tests/integration/test_tui_acceptance.py — end-to-end TUI acceptance (Task 13).

Two real `asb-test-` workspaces (image `localhost/agent-sandbox:latest`),
driven through the same boundaries the TUI uses (`TuiController`,
`handle_key`, `asb.interfaces.sessions`, `CheckoutManager`). Every agent is a
harmless fake command (`sh -lc ...`), never a real provider.

Workspace 1, on a primary checkout (`test_sessions_*`):

1. two sessions of different agents (codex, claude) run in ONE checkout;
2. the TUI refreshes, `q` closes it: nothing is written and both tmux panes
   keep the same process;
3. a new TUI reattaches (Enter) to the SAME tmux process and `C-b d`
   returns control;
4. uncertain liveness (a second pane makes the probe UNKNOWN) shows
   `recovery_required`, and attach launches nothing; once the evidence is
   clear again the session returns to `detached`;
5. a command that exits 0 on its own is `completed` (voluntary completion),
   never relaunched;
6. `session stop` ends the rest; `purge` removes the workspace.

Workspace 2, on a worktree (`test_worktree_*`):

1. the worktree row shows the SANDBOX branch, and a `git switch` made by
   the agent inside the sandbox updates the label on the next refresh;
2. the primary checkout is refused by finish, cleanup and the TUI `f`;
3. a dirty worktree is refused by finish and cleanup;
4. a merge conflict preserves worktree, branch, binding, sandbox and Git's
   conflict state;
5. an external merge (`asb-agent pull` + `git merge`) is labelled
   `merged / cleanup available`;
6. an active session blocks that cleanup;
7. after `session stop`, the TUI `f` + `y` cleans up: sandbox purged,
   worktree removed, binding gone, local branch kept (default NO).

The fixture teardown proves no `asb-test-` resource survives. Registry and
store live under the fixture's temporary root; `asb-agent up` itself writes
`~/.local/state/agent-sandbox/<ws>/origin` (existing behaviour), which
`purge` removes.
"""
from __future__ import annotations

import getpass
import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))

from asb import lifecycle  # noqa: E402
from asb.agents.base import AgentDriver, LaunchCommand, SessionEvidence  # noqa: E402
from asb.checkouts.manager import CreateCheckout  # noqa: E402
from asb.checkouts.model import FinishCheckout, FinishState  # noqa: E402
from asb.interfaces import sessions, tui  # noqa: E402
from asb.interfaces.tui_model import MERGED_LABEL, RowKind  # noqa: E402
from asb.projects.registry import ProjectRegistryError  # noqa: E402
from asb.sessions.model import AgentKind, SessionId, SessionState  # noqa: E402
from asb.sessions.terminal import Liveness, TmuxTerminal  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402
from tests.integration.test_session_lifecycle import _attach_in_pty  # noqa: E402

ENTER = 10


class _Harmless(AgentDriver):
    """Test driver: launches only its fixed harmless command. No provider
    id is ever discovered, so no probe and no native resume happen."""

    binary = "sh"
    resume_argv_prefix = ()
    session_id_provable = False
    command: tuple[str, ...] = ()

    def launch(self, cwd: Path) -> LaunchCommand:
        return LaunchCommand(argv=self.command)

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        return None


class CodexFake(_Harmless):
    kind = AgentKind.CODEX
    command = ("sh", "-lc", "printf codex-ready; exec sleep 600")


class ClaudeFake(_Harmless):
    kind = AgentKind.CLAUDE
    command = ("sh", "-lc", "printf claude-ready; exec sleep 600")


def completing_driver(flag: str) -> _Harmless:
    """Stays alive until `flag` exists inside the sandbox, then exits 0:
    alive at the start probe, voluntary completion afterwards."""

    class Completing(_Harmless):
        kind = AgentKind.ANTIGRAVITY
        command = ("sh", "-lc",
                   f"printf waiting; while [ ! -e {flag} ]; do sleep 0.2; "
                   "done; exit 0")

    return Completing()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()


def _remote(connection, *argv: str) -> str:
    """Runs `argv` INSIDE the sandbox over the non-interactive SSH channel."""
    result = subprocess.run(
        connection.ssh_argv(tuple(argv), interactive=False),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _pane_pids(connection, terminal_id: str) -> str:
    return _remote(connection, "tmux", "list-panes", "-s", "-t",
                   f"={terminal_id}:", "-F", "#{pane_pid}")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Operator")
    _git(path, "config", "user.email", "operator@example.com")
    (path / "README.md").write_text("# acceptance\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial commit")


def _register_workspace(test: unittest.TestCase, sandbox: SandboxFixture,
                        ws: str, mount_name: str) -> tuple[str, Path]:
    """Registers every resource `asb-agent up` creates for `ws` so the
    fixture teardown removes it and proves it absent."""
    agent = sandbox.register_container(f"asb-{ws}-agent")
    sandbox.register_container(f"asb-{ws}-proxy")
    sandbox.register_network(f"asb-{ws}")
    sandbox.register_network(f"asb-{ws}-out")
    for unit in (f"asb-{ws}.target", f"asb-{ws}-agent.service",
                 f"asb-{ws}-proxy.service", f"asb-{ws}-forwarder.service",
                 f"asb-{ws}-docker.service"):
        sandbox.register_unit(unit)
    sandbox.register_volume(f"asb-{ws}-session")
    sandbox.register_volume(f"asb-{ws}-containers")
    home = Path(os.path.expanduser("~"))
    state_dir = home / ".local" / "state" / "agent-sandbox" / ws
    test.addCleanup(shutil.rmtree, home / "asb-agent" / mount_name, True)
    test.addCleanup(shutil.rmtree, state_dir, True)
    return agent, state_dir


def _row(controller: tui.TuiController, *, session_id: str | None = None,
         checkout_id: str | None = None):
    for row in controller.rows:
        if session_id is not None and row.session_id == session_id:
            return row
        if (checkout_id is not None and row.kind is RowKind.CHECKOUT
                and row.checkout_id == checkout_id):
            return row
    raise AssertionError(
        f"no row for {session_id or checkout_id}: "
        f"{[r.text for r in controller.rows]}")


def _select(controller: tui.TuiController, row) -> None:
    controller.selected = controller.rows.index(row)


class TestTuiAcceptance(unittest.TestCase):
    def test_sessions_close_reattach_uncertain_and_completion(self) -> None:
        with SandboxFixture("tuiacc", auto_setup=False) as sandbox:
            # The basename becomes the deterministic workspace prefix.
            repo = sandbox.state_root / sandbox.workspace
            _init_repo(repo)
            flag = f"/tmp/{sandbox.workspace}-done"
            completing = completing_driver(flag)
            services = sessions.session_services(
                ROOT, state_dir=sandbox.state_root / "control",
                drivers=lambda ws: {AgentKind.CODEX: CodexFake(),
                                    AgentKind.CLAUDE: ClaudeFake(),
                                    AgentKind.ANTIGRAVITY: completing},
                sleep=lambda _: None)

            out = io.StringIO()
            self.assertEqual(sessions.project_add(
                str(repo), "main", None, services=services, out=out), 0)
            added = json.loads(out.getvalue())
            ws, checkout = added["workspace"], added["checkoutId"]
            self.assertTrue(ws.startswith(f"{sandbox.workspace}-"), ws)
            agent, state_dir = _register_workspace(self, sandbox, ws,
                                                   repo.name)
            self.assertFalse(sandbox._podman_exists("container", agent))
            user = getpass.getuser()

            def start(kind: str, title: str) -> str:
                out = io.StringIO()
                code = sessions.session_start(checkout, kind, title,
                                              services=services, out=out)
                session_id, state = out.getvalue().split()
                sandbox.register_tmux_session(agent, f"asb-{session_id}",
                                              user)
                self.assertEqual((code, state), (0, "running"), out.getvalue())
                return session_id

            def stored(session_id: str):
                return services.store.get(SessionId(session_id))

            with mock.patch.dict(os.environ, sandbox.cli_env()), \
                    mock.patch.object(lifecycle, "SSH_KEY",
                                      sandbox.config_dir / "id_ed25519"):
                # 1. Two agents in the same checkout.
                codex = start("codex", "accept-codex")
                claude = start("claude", "accept-claude")
                connection = services.resolve(ws)
                terminal = TmuxTerminal(connection)
                out = io.StringIO()
                sessions.session_list(checkout, as_json=True,
                                      services=services, out=out)
                listed = {s["id"]: s for s in
                          json.loads(out.getvalue())["sessions"]}
                self.assertEqual(set(listed), {codex, claude})
                self.assertEqual(
                    {(s["checkoutId"], s["agent"], s["terminalId"])
                     for s in listed.values()},
                    {(checkout, "codex", f"asb-{codex}"),
                     (checkout, "claude", f"asb-{claude}")})
                pids = {sid: _pane_pids(connection, f"asb-{sid}")
                        for sid in (codex, claude)}
                self.assertNotEqual(pids[codex], pids[claude])
                for sid in (codex, claude):
                    self.assertIs(terminal.probe(f"asb-{sid}"),
                                  Liveness.ALIVE)

                # 2. The TUI sees both; `q` closes it and changes nothing.
                controller = tui.TuiController(services)
                controller.refresh()
                self.assertIn("[primary]  main  ready",
                              _row(controller, checkout_id=checkout).text)
                self.assertEqual(
                    _row(controller, session_id=codex).text,
                    "codex  detached  accept-codex")
                self.assertEqual(
                    _row(controller, session_id=claude).text,
                    "claude  detached  accept-claude")
                revisions = {sid: stored(sid).revision
                             for sid in (codex, claude)}
                tui.handle_key(controller, ord("q"))
                self.assertFalse(controller.running)
                self.assertEqual({sid: stored(sid).revision
                                  for sid in (codex, claude)}, revisions)
                for sid in (codex, claude):
                    self.assertIs(terminal.probe(f"asb-{sid}"),
                                  Liveness.ALIVE)
                    self.assertEqual(_pane_pids(connection, f"asb-{sid}"),
                                     pids[sid])

                # 3. A new TUI reattaches to the SAME tmux process.
                screen = bytearray()
                children: list[list[str]] = []

                def run_child(argv: list[str]) -> int:
                    children.append(argv)
                    return _attach_in_pty(argv[0], argv, screen)

                reopened = tui.TuiController(services, run_child=run_child)
                reopened.refresh()
                _select(reopened, _row(reopened, session_id=codex))
                tui.handle_key(reopened, ENTER)
                self.assertEqual(len(children), 1)
                self.assertEqual(reopened.message, "detached", bytes(screen))
                self.assertIn(b"codex-ready", screen)
                self.assertEqual(_pane_pids(connection, f"asb-{codex}"),
                                 pids[codex])
                self.assertIs(terminal.probe(f"asb-{codex}"), Liveness.ALIVE)

                # 4. Uncertain liveness: a second pane makes the probe
                #    UNKNOWN; nothing is launched or attached.
                extra = _remote(connection, "tmux", "split-window", "-d",
                                "-P", "-F", "#{pane_id}", "-t",
                                f"=asb-{claude}:", "sleep 600")
                self.assertIs(terminal.probe(f"asb-{claude}"),
                              Liveness.UNKNOWN)
                reopened.refresh()
                self.assertEqual(
                    _row(reopened, session_id=claude).text,
                    "claude  recovery_required  accept-claude")
                self.assertEqual(
                    _row(reopened, session_id=codex).text,
                    "codex  detached  accept-codex")
                _select(reopened, _row(reopened, session_id=claude))
                tui.handle_key(reopened, ENTER)
                self.assertEqual(
                    reopened.message,
                    "session is recovery_required; nothing to attach")
                err = io.StringIO()
                executed: list[list[str]] = []
                self.assertEqual(sessions.session_attach(
                    claude, services=services, err=err,
                    execute=lambda f, argv: executed.append(argv)), 2)
                self.assertEqual((executed, len(children)), ([], 1))
                self.assertIn("recovery_required", err.getvalue())
                _remote(connection, "tmux", "kill-pane", "-t", extra)
                reopened.refresh()
                self.assertEqual(
                    _row(reopened, session_id=claude).text,
                    "claude  detached  accept-claude")
                self.assertEqual(_pane_pids(connection, f"asb-{claude}"),
                                 pids[claude])

                # 5. Voluntary completion: exit 0 on its own is `completed`.
                done = start("antigravity", "accept-done")
                _remote(connection, "touch", flag)
                deadline = time.monotonic() + 30
                while terminal.probe(f"asb-{done}") is not Liveness.DEAD:
                    self.assertLess(time.monotonic(), deadline,
                                    "the completing command never exited")
                    time.sleep(0.2)
                self.assertEqual(terminal.capture_exit_status(f"asb-{done}"),
                                 0)
                reopened.refresh()
                self.assertEqual(
                    _row(reopened, session_id=done).text,
                    "antigravity  completed  accept-done")
                self.assertIs(stored(done).state, SessionState.COMPLETED)
                self.assertEqual(sessions.session_attach(
                    done, services=services, err=io.StringIO(),
                    execute=lambda f, argv: executed.append(argv)), 2)
                self.assertEqual(executed, [])
                # Never relaunched: the dead pane is still the only one.
                self.assertIs(terminal.probe(f"asb-{done}"), Liveness.DEAD)

                # 6. Stop the rest.
                for sid in (codex, claude):
                    out = io.StringIO()
                    self.assertEqual(sessions.session_stop(
                        sid, services=services, out=out), 0)
                    self.assertEqual(out.getvalue(), f"{sid} completed\n")
                    self.assertIs(terminal.probe(f"asb-{sid}"),
                                  Liveness.DEAD)

            res = sandbox.cli("purge", "--workspace", ws, "--yes")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse(sandbox._podman_exists("container", agent))
            self.assertFalse(state_dir.exists())

    def test_worktree_label_refusals_conflict_merge_and_cleanup(self) -> None:
        with SandboxFixture("tuiwt", auto_setup=False) as sandbox:
            primary = sandbox.state_root / "primary"
            _init_repo(primary)
            services = sessions.session_services(
                ROOT, state_dir=sandbox.state_root / "control",
                drivers=lambda ws: {AgentKind.CODEX: CodexFake()},
                sleep=lambda _: None)
            project = services.registry.add(primary, "main",
                                            sandbox.state_root / "wts")
            primary_id = services.registry.register_checkout(
                project.id, primary).checkout_id
            checkouts = tui.default_checkouts(services)
            worktree = sandbox.state_root / "wts" / sandbox.workspace
            checkout = checkouts.create(CreateCheckout(
                project.id, "topic", "main", worktree))
            binding = services.registry.checkout(checkout.id)
            ws = binding.workspace
            self.assertTrue(ws.startswith(f"{sandbox.workspace}-"), ws)
            agent, state_dir = _register_workspace(self, sandbox, ws,
                                                   worktree.name)
            self.assertFalse(sandbox._podman_exists("container", agent))
            base = _git(primary, "rev-parse", "main")

            def branches() -> list[str]:
                return _git(primary, "branch",
                            "--format=%(refname:short)").split()

            def assert_preserved() -> None:
                self.assertTrue(worktree.is_dir())
                self.assertIn("topic", branches())
                self.assertEqual(services.registry.checkout(checkout.id),
                                 binding)
                self.assertTrue(sandbox._podman_exists("container", agent))

            with mock.patch.dict(os.environ, sandbox.cli_env()), \
                    mock.patch.object(lifecycle, "SSH_KEY",
                                      sandbox.config_dir / "id_ed25519"):
                connection = services.runtime.ensure(binding)
                root = connection.project_root
                controller = tui.TuiController(services, checkouts=checkouts)

                # 1. Branch label: the sandbox branch, refreshed.
                controller.refresh()
                self.assertIn("[primary]  main (host)  absent",
                              _row(controller, checkout_id=primary_id).text)
                self.assertIn("[worktree]  topic  ready",
                              _row(controller, checkout_id=checkout.id).text)
                _remote(connection, "git", "-C", str(root), "switch", "-q",
                        "-c", "agent-label")
                controller.refresh()
                self.assertIn("[worktree]  agent-label  ready",
                              _row(controller, checkout_id=checkout.id).text)
                _remote(connection, "git", "-C", str(root), "switch", "-q",
                        "topic")
                controller.refresh()
                self.assertIn("[worktree]  topic  ready",
                              _row(controller, checkout_id=checkout.id).text)

                # 2. The primary checkout is refused everywhere.
                result = checkouts.finish(FinishCheckout(primary_id, "main"))
                self.assertIs(result.state, FinishState.BLOCKED)
                self.assertIn("primary checkout is never finished",
                              result.message)
                result = checkouts.cleanup(primary_id)
                self.assertIs(result.state, FinishState.BLOCKED)
                self.assertIn("primary checkout is never cleaned up",
                              result.message)
                _select(controller, _row(controller, checkout_id=primary_id))
                tui.handle_key(controller, ord("f"))
                self.assertIsNone(controller.prompt)
                self.assertEqual(controller.message,
                                 "the primary checkout is never finished")
                self.assertEqual(_git(primary, "rev-parse", "main"), base)
                self.assertEqual(_git(primary, "status", "--porcelain"), "")

                # 3. A dirty worktree is refused before any mutation.
                scratch = worktree / "scratch.txt"
                scratch.write_text("uncommitted\n", encoding="utf-8")
                for result in (
                        checkouts.finish(FinishCheckout(
                            checkout.id, "main", cleanup_after_merge=True)),
                        checkouts.cleanup(checkout.id)):
                    self.assertIs(result.state, FinishState.BLOCKED)
                    self.assertIn("uncommitted changes", result.message)
                self.assertEqual(_git(primary, "for-each-ref", "refs/asb"),
                                 "")
                assert_preserved()
                scratch.unlink()

                # 4. A merge conflict preserves everything.
                _remote(connection, "sh", "-c", (
                    f"cd {root} && printf 'agent\\n' > shared.txt && "
                    "git add shared.txt && git -c user.name=Agent "
                    "-c user.email=agent@example.com commit -q -m agent"))
                agent_commit = _git(root, "rev-parse", "HEAD")
                (primary / "shared.txt").write_text("operator\n",
                                                    encoding="utf-8")
                _git(primary, "add", "shared.txt")
                _git(primary, "commit", "-q", "-m", "operator")
                result = checkouts.finish(FinishCheckout(
                    checkout.id, "main", cleanup_after_merge=True,
                    delete_merged_branch=True))
                self.assertIs(result.state, FinishState.CONFLICT,
                              result.message)
                self.assertIn("shared.txt", result.message)
                self.assertTrue((primary / ".git" / "MERGE_HEAD").exists())
                self.assertNotEqual(_git(primary, "ls-files", "-u"), "")
                assert_preserved()
                _git(primary, "merge", "--abort")
                _git(primary, "reset", "-q", "--hard", "HEAD~1")

                # 5. External merge: `asb-agent pull` + `git merge`.
                res = sandbox.cli("pull", "--workspace", ws)
                self.assertEqual(res.returncode, 0, res.stderr)
                _git(primary, "merge", "-q", "--no-edit",
                     f"refs/asb/{ws}/topic")
                _git(primary, "merge-base", "--is-ancestor", agent_commit,
                     "main")
                controller.refresh()
                self.assertIn(MERGED_LABEL,
                              _row(controller, checkout_id=checkout.id).text)

                # 6. An active session blocks the cleanup.
                out = io.StringIO()
                self.assertEqual(sessions.session_start(
                    checkout.id, "codex", "accept-busy", services=services,
                    out=out), 0, out.getvalue())
                busy = out.getvalue().split()[0]
                sandbox.register_tmux_session(agent, f"asb-{busy}",
                                              getpass.getuser())
                result = checkouts.cleanup(checkout.id)
                self.assertIs(result.state, FinishState.BLOCKED)
                self.assertIn(f"active session {busy}", result.message)
                assert_preserved()
                self.assertEqual(sessions.session_stop(
                    busy, services=services, out=io.StringIO()), 0)

                # 7. The TUI `f` on the labelled row, then `y`, cleans up.
                controller.refresh()
                row = _row(controller, checkout_id=checkout.id)
                self.assertIn(MERGED_LABEL, row.text)
                _select(controller, row)
                tui.handle_key(controller, ord("f"))
                self.assertIsNotNone(controller.prompt)
                self.assertTrue(controller.prompt.text.startswith(
                    "clean up? y clean up"), controller.prompt.text)
                tui.handle_key(controller, ord("y"))
                self.assertEqual(controller.message, "cleanup: cleaned",
                                 controller.notice)
                self.assertFalse(sandbox._podman_exists("container", agent))
                self.assertTrue(services.runtime.sandbox_absent(binding))
                self.assertFalse(worktree.exists())
                with self.assertRaises(ProjectRegistryError):
                    services.registry.checkout(checkout.id)
                # Local branch deletion defaults to NO.
                self.assertIn("topic", branches())
                _git(primary, "merge-base", "--is-ancestor", agent_commit,
                     "main")
                self.assertNotIn(checkout.id,
                                 [r.checkout_id for r in controller.rows])
            self.assertFalse(state_dir.exists())


if __name__ == "__main__":
    unittest.main()
