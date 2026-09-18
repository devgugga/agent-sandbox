"""Testes de `asb.sessions.terminal` (Tarefa 7): backend tmux via SSH.

Cobre o argv EXATO de cada chamada remota (start, probe, attach, stop,
capture), cada saida de `probe` (vivo, pane morto, sessao ausente, sem
servidor, SSH 255, timeout, saida nao classificavel), terminal id invalido
e comando com espacos e metacaracteres. As strings de erro do tmux vieram
do tmux 3.3a da imagem (ver relatorio da tarefa).

Nenhum teste toca tmux, SSH ou Podman de verdade: `run` e sempre um mock.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.runtime.connection import ConnectionInfo  # noqa: E402
from asb.sessions.model import TerminalId  # noqa: E402
from asb.sessions.terminal import (  # noqa: E402
    Liveness, TerminalError, TmuxTerminal,
)

NAME = "asb-s-0123456789abcdef"

SSH_BATCH = [
    "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
    "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
    "-i", "/keys/id_ed25519", "-p", "2222", "--", "v@127.0.0.1",
]
SSH_TTY = [
    "ssh", "-tt", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
    "-i", "/keys/id_ed25519", "-p", "2222", "--", "v@127.0.0.1",
]
PROBE_REMOTE = (f"tmux list-panes -t ={NAME}: -F "
                "'#{pane_dead} #{pane_dead_status}'")


def _connection() -> ConnectionInfo:
    return ConnectionInfo(
        workspace="ws-1", host="127.0.0.1", port=2222, username="v",
        identity_file=Path("/keys/id_ed25519"),
        project_root=Path("/sandbox/repo"))


def _done(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _terminal(*results) -> tuple[TmuxTerminal, mock.Mock]:
    run = mock.Mock(side_effect=list(results))
    return TmuxTerminal(_connection(), run=run), run


class _RunContract:
    def assert_local_call(self, run: mock.Mock, argv: list[str]) -> None:
        args, kwargs = run.call_args
        self.assertEqual(args, (argv,))
        self.assertIsInstance(args[0], list)
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["check"], False)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertGreater(kwargs["timeout"], 0)


class TestStart(_RunContract, unittest.TestCase):
    def test_exact_remote_argv_for_a_one_word_command(self):
        terminal, run = _terminal(_done(0))
        terminal.start(TerminalId(NAME), Path("/sandbox/repo"), ("codex",))
        self.assert_local_call(run, [
            *SSH_BATCH,
            f"tmux new-session -d -s {NAME} -c /sandbox/repo -- codex "
            f"';' set-option -t ={NAME}: remain-on-exit on",
        ])

    def test_command_with_spaces_and_metacharacters_survives_as_argv(self):
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/my repo",
                       ("sh", "-c", "echo $HOME; exit 3", "x y"))
        self.assert_local_call(run, [
            *SSH_BATCH,
            f"tmux new-session -d -s {NAME} -c '/sandbox/my repo' -- "
            "sh -c 'echo $HOME; exit 3' 'x y' "
            f"';' set-option -t ={NAME}: remain-on-exit on",
        ])

    def test_single_element_with_a_space_is_quoted_for_tmux_shell(self):
        # tmux roda um comando de UM elemento via `sh -c`; sem aspas, o
        # caminho com espaco seria dividido pelo shell (pinado: status 127).
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/repo", ("/opt/my prog",))
        remote = run.call_args.args[0][-1]
        self.assertIn(" -- ''\"'\"'/opt/my prog'\"'\"'' ';' ", remote)

    def test_trailing_semicolon_is_escaped_so_tmux_does_not_split(self):
        # tmux trata argumento terminado em ";" como separador de comando
        # e devolve "\;" como ";" literal (pinado no tmux 3.3a).
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/d;", ("sh", "-c", "true;", ";"))
        remote = run.call_args.args[0][-1]
        self.assertIn("-c '/sandbox/d\\;' -- sh -c 'true\\;' '\\;' ';' ",
                      remote)

    def test_hash_in_cwd_is_escaped_against_format_expansion(self):
        # `new-session -c` expande formatos (#S etc.); "##" e "#" literal.
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/a#S", ("codex",))
        remote = run.call_args.args[0][-1]
        self.assertIn("-c '/sandbox/a##S' -- codex", remote)

    def test_remain_on_exit_is_never_global(self):
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/repo", ("codex",))
        remote = run.call_args.args[0][-1]
        self.assertNotIn(" -g", remote)
        self.assertIn(f"set-option -t ={NAME}: remain-on-exit on", remote)

    def test_tmux_failure_raises(self):
        terminal, _ = _terminal(_done(1, stderr=f"duplicate session: {NAME}\n"))
        with self.assertRaises(TerminalError):
            terminal.start(NAME, "/sandbox/repo", ("codex",))

    def test_ssh_failure_raises(self):
        terminal, _ = _terminal(_done(255, stderr="Connection refused\n"))
        with self.assertRaises(TerminalError):
            terminal.start(NAME, "/sandbox/repo", ("codex",))

    def test_timeout_raises(self):
        terminal, _ = _terminal(subprocess.TimeoutExpired("ssh", 30))
        with self.assertRaises(TerminalError):
            terminal.start(NAME, "/sandbox/repo", ("codex",))

    def test_rejects_empty_command_relative_cwd_and_non_str_elements(self):
        for cwd, command in (("/sandbox/repo", ()),
                             ("sandbox/repo", ("codex",)),
                             ("", ("codex",)),
                             ("/sandbox/repo", ("codex", 3))):
            terminal, run = _terminal()
            with self.subTest(cwd=cwd, command=command):
                with self.assertRaises(ValueError):
                    terminal.start(NAME, cwd, command)
                run.assert_not_called()


class TestProbe(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0, stdout="0 \n"))
        terminal.probe(NAME)
        self.assert_local_call(run, [*SSH_BATCH, PROBE_REMOTE])

    def test_live_pane_is_alive(self):
        terminal, _ = _terminal(_done(0, stdout="0 \n"))
        self.assertIs(terminal.probe(NAME), Liveness.ALIVE)

    def test_dead_pane_is_dead(self):
        terminal, _ = _terminal(_done(0, stdout="1 3\n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_dead_pane_killed_by_signal_is_dead(self):
        # Morte por sinal: tmux 3.3a deixa pane_dead_status vazio.
        terminal, _ = _terminal(_done(0, stdout="1 \n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_missing_session_is_dead(self):
        terminal, _ = _terminal(_done(1, stderr=f"can't find session: {NAME}\n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_no_server_running_is_dead(self):
        terminal, _ = _terminal(_done(
            1, stderr="no server running on /tmp/tmux-1000/default\n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_no_server_socket_is_dead(self):
        terminal, _ = _terminal(_done(1, stderr=(
            "error connecting to /tmp/tmux-1000/default "
            "(No such file or directory)\n")))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_missing_other_session_name_is_unknown(self):
        terminal, _ = _terminal(_done(1, stderr="can't find session: asb-x\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_tmux_exit_1_with_unrecognized_stderr_is_unknown(self):
        for stderr in ("server exited unexpectedly\n",
                       "error connecting to /tmp/tmux-1000/default "
                       "(Permission denied)\n",
                       ""):
            terminal, _ = _terminal(_done(1, stderr=stderr))
            with self.subTest(stderr=stderr):
                self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_ssh_exit_255_is_unknown(self):
        terminal, _ = _terminal(_done(255, stderr=f"can't find session: {NAME}\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_timeout_is_unknown(self):
        terminal, _ = _terminal(subprocess.TimeoutExpired("ssh", 30))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_ssh_binary_missing_is_unknown(self):
        terminal, _ = _terminal(FileNotFoundError("ssh"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_unparseable_output_is_unknown(self):
        for stdout in ("", "garbage\n", "0 \n1 2\n", "2 \n", "1 x\n"):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(stdout=stdout):
                self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_other_exit_code_is_unknown(self):
        terminal, _ = _terminal(_done(127, stderr="tmux: command not found\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)


class TestCaptureExitStatus(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0, stdout="1 3\n"))
        terminal.capture_exit_status(NAME)
        self.assert_local_call(run, [*SSH_BATCH, PROBE_REMOTE])

    def test_dead_pane_status_is_returned(self):
        for stdout, expected in (("1 3\n", 3), ("1 0\n", 0), ("1 7\n", 7)):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(stdout=stdout):
                self.assertEqual(terminal.capture_exit_status(NAME), expected)

    def test_none_when_status_is_not_observable(self):
        for result in (_done(0, stdout="0 \n"),            # pane vivo
                       _done(0, stdout="1 \n"),            # morto por sinal
                       _done(0, stdout="garbage\n"),
                       _done(1, stderr=f"can't find session: {NAME}\n"),
                       _done(255, stderr="Connection refused\n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, _ = _terminal(result)
            with self.subTest(result=result):
                self.assertIsNone(terminal.capture_exit_status(NAME))


class TestStop(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0))
        terminal.stop(NAME)
        self.assert_local_call(run, [*SSH_BATCH, f"tmux kill-session -t ={NAME}"])

    def test_already_gone_is_not_an_error(self):
        for stderr in (f"can't find session: {NAME}\n",
                       "no server running on /tmp/tmux-1000/default\n"):
            terminal, _ = _terminal(_done(1, stderr=stderr))
            with self.subTest(stderr=stderr):
                terminal.stop(NAME)

    def test_failures_raise(self):
        for result in (_done(255, stderr="Connection refused\n"),
                       _done(1, stderr="server exited unexpectedly\n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, _ = _terminal(result)
            with self.subTest(result=result):
                with self.assertRaises(TerminalError):
                    terminal.stop(NAME)


class TestAttachArgv(unittest.TestCase):
    def test_exact_interactive_argv(self):
        terminal, run = _terminal()
        self.assertEqual(terminal.attach_argv(NAME), [
            *SSH_TTY, f"tmux attach-session -t ={NAME}",
        ])
        run.assert_not_called()


class TestInvalidTerminalId(unittest.TestCase):
    def test_every_method_validates_before_running(self):
        for bad in ("", "Asb-UPPER", "-flag", "a;b", "a b", "=asb", None):
            calls = (
                lambda t: t.start(bad, "/sandbox/repo", ("codex",)),
                lambda t: t.probe(bad),
                lambda t: t.capture_exit_status(bad),
                lambda t: t.stop(bad),
                lambda t: t.attach_argv(bad),
            )
            for call in calls:
                terminal, run = _terminal()
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        call(terminal)
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
