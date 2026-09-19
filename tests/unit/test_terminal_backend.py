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

import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.runtime.connection import ConnectionInfo  # noqa: E402
from asb.sessions import terminal as terminal_module  # noqa: E402
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
# M2: a sessao e achada pela TAG `@asb_session` (sobrevive a um rename) OU
# pelo nome (sessao antiga, sem tag), num filtro do proprio tmux; a saida
# traz o `session_id` ($N), que nenhum nome forjado imita. Pinado no tmux
# 3.3a da imagem (relatorio da fix wave 2).
FILTER = ("#{||:#{==:#{@asb_session}," + NAME + "},"
          "#{==:#{session_name}," + NAME + "}}")
PROBE_REMOTE = (f"tmux list-panes -a -f '{FILTER}' -F "
                "'#{session_id} #{pane_dead} #{pane_dead_status}'")
# Pilot round 1: o attach roda um script FIXO que cai para xterm-256color
# quando a imagem nao tem o terminfo do TERM do operador (Ghostty); o alvo
# e `$1`, argumento separado, nunca interpolado no script. Pilot round 2:
# `tmux -u` desenha UTF-8 mesmo sem locale na sessao SSH (o ssh do host nao
# repassa LANG, e um cliente sem locale UTF-8 troca acentos por "_").
ATTACH_SCRIPT = ('infocmp "$TERM" >/dev/null 2>&1 || '
                 'export TERM=xterm-256color; '
                 'exec tmux -u attach-session -t "$1"')


def attach_remote(quoted_target: str) -> str:
    return ("sh -c 'infocmp \"$TERM\" >/dev/null 2>&1 || "
            "export TERM=xterm-256color; "
            "exec tmux -u attach-session -t \"$1\"' asb-attach "
            + quoted_target)


START_TAIL = (f"';' set-option -t ={NAME}: remain-on-exit on "
              f"';' set-option -t ={NAME}: @asb_session {NAME}")


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
            + START_TAIL,
        ])

    def test_command_with_spaces_and_metacharacters_survives_as_argv(self):
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/my repo",
                       ("sh", "-c", "echo $HOME; exit 3", "x y"))
        self.assert_local_call(run, [
            *SSH_BATCH,
            f"tmux new-session -d -s {NAME} -c '/sandbox/my repo' -- "
            "sh -c 'echo $HOME; exit 3' 'x y' " + START_TAIL,
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

    def test_hash_in_a_command_element_is_passed_unchanged(self):
        # Argumentos do comando NAO passam por expansao de formato (pinado).
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/repo", ("sh", "-c", "echo #S #{x}"))
        remote = run.call_args.args[0][-1]
        self.assertIn(" -- sh -c 'echo #S #{x}' ';' ", remote)

    def test_backslash_before_a_trailing_semicolon_is_preserved(self):
        # "a\;" vira "a\\;"; o tmux devolve "a\;" literal (pinado).
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/repo", ("printf", "a\\;"))
        remote = run.call_args.args[0][-1]
        self.assertIn(" -- printf 'a\\\\;' ';' ", remote)

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


class TestTag(unittest.TestCase):
    def test_start_tags_the_session_in_the_same_tmux_call(self):
        terminal, run = _terminal(_done(0))
        terminal.start(NAME, "/sandbox/repo", ("codex",))
        remote = run.call_args.args[0][-1]
        self.assertTrue(remote.endswith(
            f"';' set-option -t ={NAME}: @asb_session {NAME}"))
        self.assertEqual(run.call_count, 1)


def _renamed_tmux(dead: str = "0", status: str = ""):
    """tmux falso de uma sessao RENOMEADA (o `C-b $` do operador, ou o
    proprio agente): o nome antigo nao acha nada, a tag ainda acha $7."""
    def run(argv, **_kwargs):
        remote = argv[-1]
        if f"-t ={NAME}" in remote:
            return _done(1, stderr=f"can't find session: {NAME}\n")
        if "list-panes -a -f" in remote and "@asb_session" in remote:
            return _done(0, stdout=f"$7 {dead} {status}\n")
        if "kill-session -t '$7'" in remote:
            return _done(0)
        return _done(1, stderr="unexpected\n")
    return mock.Mock(side_effect=run)


class TestRenamedSession(unittest.TestCase):
    def test_a_renamed_live_session_still_probes_alive(self):
        run = _renamed_tmux()
        terminal = TmuxTerminal(_connection(), run=run)
        self.assertIs(terminal.probe(NAME), Liveness.ALIVE)

    def test_a_renamed_dead_pane_still_reports_its_exit_status(self):
        run = _renamed_tmux(dead="1", status="3")
        terminal = TmuxTerminal(_connection(), run=run)
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)
        self.assertEqual(terminal.capture_exit_status(NAME), 3)

    def test_stop_and_attach_reach_a_renamed_session_by_its_id(self):
        run = _renamed_tmux()
        terminal = TmuxTerminal(_connection(), run=run)
        terminal.stop(NAME)
        self.assertEqual(run.call_args.args[0][-1], "tmux kill-session -t '$7'")
        self.assertEqual(terminal.attach_argv(NAME),
                         [*SSH_TTY, attach_remote("'$7'")])


class TestProbe(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0, stdout="$3 0 \n"))
        terminal.probe(NAME)
        self.assert_local_call(run, [*SSH_BATCH, PROBE_REMOTE])

    def test_live_pane_is_alive(self):
        terminal, _ = _terminal(_done(0, stdout="$3 0 \n"))
        self.assertIs(terminal.probe(NAME), Liveness.ALIVE)

    def test_dead_pane_is_dead(self):
        terminal, _ = _terminal(_done(0, stdout="$3 1 3\n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_dead_pane_killed_by_signal_is_dead(self):
        # Morte por sinal: tmux 3.3a deixa pane_dead_status vazio.
        terminal, _ = _terminal(_done(0, stdout="$3 1 \n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_no_tagged_or_named_session_on_a_running_server_is_dead(self):
        # Pinado: com o servidor vivo, o filtro sem casamento sai 0 e vazio
        # — o tmux listou TODAS as sessoes e nenhuma e esta.
        terminal, _ = _terminal(_done(0, stdout=""))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_no_server_running_is_dead(self):
        terminal, _ = _terminal(_done(
            1, stderr="no server running on /tmp/tmux-1000/default\n"))
        self.assertIs(terminal.probe(NAME), Liveness.DEAD)

    def test_deleted_or_never_created_socket_is_unknown(self):
        # Socket apagado com o servidor vivo, ou nunca criado (pinado: a
        # mesma mensagem): o agente pode continuar rodando.
        terminal, _ = _terminal(_done(1, stderr=(
            "error connecting to /tmp/tmux-1000/default "
            "(No such file or directory)\n")))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_two_sessions_carrying_the_tag_or_name_are_unknown(self):
        # Uma copia forjada da tag, ou uma sessao antiga com o nome e outra
        # renomeada com a tag: nunca escolhemos uma.
        terminal, _ = _terminal(_done(0, stdout="$3 0 \n$9 1 0\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_more_than_one_pane_is_unknown(self):
        for stdout in ("$3 1 4\n$3 0 \n", "$3 0 \n$3 0 \n"):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(stdout=stdout):
                self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_unparseable_output_is_unknown(self):
        for stdout in ("garbage\n", "0 \n", "$3 2 \n", "$3 1 x\n",
                       "$x 0 \n", "$3 1 \u0663\n", "3 0 \n",
                       "$3 0 \ngarbage\n"):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(stdout=stdout):
                self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_tmux_exit_1_with_unrecognized_stderr_is_unknown(self):
        for stderr in ("server exited unexpectedly\n",
                       f"can't find session: {NAME}\n",
                       "error connecting to /tmp/tmux-1000/default "
                       "(Permission denied)\n",
                       ""):
            terminal, _ = _terminal(_done(1, stderr=stderr))
            with self.subTest(stderr=stderr):
                self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_ssh_exit_255_is_unknown(self):
        terminal, _ = _terminal(_done(
            255, stderr="no server running on /tmp/tmux-1000/default\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_timeout_is_unknown(self):
        terminal, _ = _terminal(subprocess.TimeoutExpired("ssh", 30))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_ssh_binary_missing_is_unknown(self):
        terminal, _ = _terminal(FileNotFoundError("ssh"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)

    def test_other_exit_code_is_unknown(self):
        terminal, _ = _terminal(_done(127, stderr="tmux: command not found\n"))
        self.assertIs(terminal.probe(NAME), Liveness.UNKNOWN)


class TestCaptureExitStatus(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0, stdout="$3 1 3\n"))
        terminal.capture_exit_status(NAME)
        self.assert_local_call(run, [*SSH_BATCH, PROBE_REMOTE])

    def test_dead_pane_status_is_returned(self):
        for stdout, expected in (("$3 1 3\n", 3), ("$3 1 0\n", 0),
                                 ("$3 1 7\n", 7)):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(stdout=stdout):
                self.assertEqual(terminal.capture_exit_status(NAME), expected)

    def test_none_when_status_is_not_observable(self):
        for result in (_done(0, stdout="$3 0 \n"),          # pane vivo
                       _done(0, stdout="$3 1 4\n$3 0 \n"),  # dois panes
                       _done(0, stdout="$3 1 0\n$4 1 0\n"), # duas sessoes
                       _done(0, stdout="$3 1 \u0663\n"),    # nao ASCII
                       _done(1, stderr="error connecting to /tmp/tmux-1000/"
                                       "default (No such file or directory)\n"),
                       _done(0, stdout="$3 1 \n"),           # sinal
                       _done(0, stdout="garbage\n"),
                       _done(0, stdout=""),                   # ausente
                       _done(1, stderr="no server running on /tmp/x\n"),
                       _done(255, stderr="Connection refused\n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, _ = _terminal(result)
            with self.subTest(result=result):
                self.assertIsNone(terminal.capture_exit_status(NAME))


class TestStop(_RunContract, unittest.TestCase):
    def test_exact_remote_argv(self):
        terminal, run = _terminal(_done(0, stdout="$3 1 0\n"), _done(0))
        terminal.stop(NAME)
        self.assertEqual(run.call_args_list[0].args[0],
                         [*SSH_BATCH, PROBE_REMOTE])
        self.assert_local_call(run, [*SSH_BATCH, "tmux kill-session -t '$3'"])

    def test_already_gone_is_not_an_error_and_kills_nothing(self):
        for result in (_done(0, stdout=""),
                       _done(1, stderr="no server running on /tmp/x\n")):
            terminal, run = _terminal(result)
            with self.subTest(result=result):
                terminal.stop(NAME)
                self.assertEqual(run.call_count, 1)

    def test_a_session_gone_between_lookup_and_kill_is_not_an_error(self):
        for stderr in ("can't find session: $3\n",
                       "no server running on /tmp/tmux-1000/default\n"):
            terminal, _ = _terminal(_done(0, stdout="$3 0 \n"),
                                    _done(1, stderr=stderr))
            with self.subTest(stderr=stderr):
                terminal.stop(NAME)

    def test_an_uncertain_lookup_raises_and_kills_nothing(self):
        for result in (_done(0, stdout="$3 0 \n$4 0 \n"),
                       _done(1, stderr="error connecting to /tmp/tmux-1000/"
                                       "default (No such file or directory)\n"),
                       _done(255, stderr="Connection refused\n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, run = _terminal(result)
            with self.subTest(result=result):
                with self.assertRaises(TerminalError):
                    terminal.stop(NAME)
                self.assertEqual(run.call_count, 1)

    def test_kill_failures_raise(self):
        for result in (_done(255, stderr="Connection refused\n"),
                       _done(1, stderr=f"can't find session: {NAME}\n"),
                       _done(1, stderr="server exited unexpectedly\n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, _ = _terminal(_done(0, stdout="$3 0 \n"), result)
            with self.subTest(result=result):
                with self.assertRaises(TerminalError):
                    terminal.stop(NAME)

    def test_a_pane_by_pane_session_with_two_panes_is_still_one_session(self):
        # Varias linhas do MESMO $N: a sessao e uma so; o kill a encerra.
        terminal, run = _terminal(_done(0, stdout="$3 1 4\n$3 0 \n"),
                                  _done(0))
        terminal.stop(NAME)
        self.assert_local_call(run, [*SSH_BATCH, "tmux kill-session -t '$3'"])


class TestAttachArgv(unittest.TestCase):
    def test_attaches_to_the_located_session_id(self):
        terminal, run = _terminal(_done(0, stdout="$3 0 \n"))
        self.assertEqual(terminal.attach_argv(NAME), [
            *SSH_TTY, attach_remote("'$3'"),
        ])
        self.assertEqual(run.call_args.args[0], [*SSH_BATCH, PROBE_REMOTE])

    def test_falls_back_to_the_exact_name_when_not_located(self):
        for result in (_done(0, stdout=""), _done(0, stdout="$3 0 \n$4 0 \n"),
                       subprocess.TimeoutExpired("ssh", 30)):
            terminal, _ = _terminal(result)
            with self.subTest(result=result):
                self.assertEqual(terminal.attach_argv(NAME), [
                    *SSH_TTY, attach_remote(f"={NAME}"),
                ])

    def test_the_script_is_constant_and_the_target_its_last_argument(self):
        for stdout, target in (("$3 0 \n", "$3"), ("", f"={NAME}")):
            terminal, _ = _terminal(_done(0, stdout=stdout))
            with self.subTest(target=target):
                argv = terminal.attach_argv(NAME)
                self.assertEqual(argv[:-1], SSH_TTY)
                self.assertEqual(shlex.split(argv[-1]),
                                 ["sh", "-c", ATTACH_SCRIPT, "asb-attach",
                                  target])
                self.assertEqual(terminal_module.ATTACH_SCRIPT, ATTACH_SCRIPT)


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
