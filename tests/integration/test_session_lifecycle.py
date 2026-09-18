"""tests/integration/test_session_lifecycle.py — sessao persistente real (Tarefa 9).

Num workspace `asb-test-` de verdade (imagem `localhost/agent-sandbox:latest`,
que ja traz tmux), pelo mesmo caminho do CLI (`asb.interfaces.sessions`):

1. `project add` registra o checkout; o nome do workspace e o deterministico
   do caminho, que aqui comeca com o prefixo da fixture;
2. `session start` sobe o workspace via `SandboxRuntime.ensure()` e lanca o
   comando inofensivo `sh -lc 'printf ready; exec sleep 60'` (driver de
   teste, nunca um provedor real) numa sessao tmux desanexada;
3. `session list --json` a mostra `running`;
4. `session attach` anexa em tela cheia num pty, ve `ready`, desanexa com
   `C-b d` e o controle volta com exit 0; a sessao continua viva;
5. `session stop` a encerra: o tmux confirma a ausencia e nao sobra servidor;
6. `purge` remove o workspace; o teardown da fixture prova que nenhum
   recurso `asb-test-` ficou.

Registro e store vivem sob a raiz temporaria da fixture, nunca em
`~/.local/state/agent-sandbox/`. Quem escreve ali e o proprio `asb-agent up`
(o marcador `<ws>/origin`, comportamento existente), que `down` remove.
"""
from __future__ import annotations

import fcntl
import getpass
import io
import json
import os
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))

from asb import lifecycle  # noqa: E402
from asb.agents.base import AgentDriver, LaunchCommand, SessionEvidence  # noqa: E402
from asb.interfaces import sessions  # noqa: E402
from asb.runtime.connection import resolve_connection  # noqa: E402
from asb.sessions.model import AgentKind  # noqa: E402
from asb.sessions.terminal import Liveness, TmuxTerminal  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402

HARMLESS = ("sh", "-lc", "printf ready; exec sleep 60")
STORED_KEYS = sorted(["id", "checkoutId", "agent", "title", "cwd",
                      "terminalId", "providerSessionId", "state",
                      "lastHealthyAt", "revision"])


class HarmlessDriver(AgentDriver):
    """Driver de teste: lanca so o comando inofensivo; sem id de provedor,
    entao nunca ha probe nem resume nativo."""

    kind = AgentKind.CODEX
    binary = "sh"
    resume_argv_prefix = ()
    version_pattern = re.compile(r"(?!)")
    resume_option_pattern = re.compile(r"(?!)")
    session_id_provable = False

    def launch(self, cwd: Path) -> LaunchCommand:
        return LaunchCommand(argv=HARMLESS)

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        return None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _attach_in_pty(file: str, argv: list[str], captured: bytearray) -> int:
    """`execute` do `session attach` para teste: roda o argv num pty 80x24,
    espera `ready` na tela, desanexa com C-b d e devolve o exit status."""
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    env = dict(os.environ, TERM="xterm-256color")
    proc = subprocess.Popen([file, *argv[1:]], stdin=slave, stdout=slave,
                            stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    detached = False
    next_detach = None
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if master in ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:  # EIO: o lado escravo fechou
                    break
                if not chunk:
                    break
                captured += chunk
            elif proc.poll() is not None:
                break
            if next_detach is None and b"ready" in captured:
                # Deixa o cliente tmux terminar de negociar o terminal:
                # teclas enviadas cedo demais caem no pane, nao no prefixo.
                next_detach = time.monotonic() + 1.0
            if next_detach is not None and time.monotonic() >= next_detach:
                os.write(master, b"\x02")
                time.sleep(0.2)
                os.write(master, b"d")
                detached = True
                next_detach = time.monotonic() + 3.0
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"attach nao terminou (C-b d enviado: {detached}); "
                f"tela: {bytes(captured[-2000:])!r}") from None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        os.close(master)


class TestSessionLifecycle(unittest.TestCase):
    def test_start_list_attach_detach_and_stop_a_real_session(self) -> None:
        with SandboxFixture("sess", auto_setup=False) as sandbox:
            # O basename vira o prefixo do workspace deterministico:
            # test-sess-<uid>-<hash8>, dentro do escopo da fixture.
            repo = sandbox.state_root / sandbox.workspace
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "config", "user.email", "test@example.com")
            (repo / "README.md").write_text("# session lifecycle\n",
                                            encoding="utf-8")
            _git(repo, "add", "README.md")
            _git(repo, "commit", "-q", "-m", "initial commit")

            services = sessions.session_services(
                ROOT, state_dir=sandbox.state_root / "control",
                drivers=lambda ws: {AgentKind.CODEX: HarmlessDriver()},
                sleep=lambda _: None)

            # 1. Registro: nunca cria workspace.
            out = io.StringIO()
            self.assertEqual(sessions.project_add(
                str(repo), "main", None, services=services, out=out), 0)
            added = json.loads(out.getvalue())
            ws = added["workspace"]
            checkout = added["checkoutId"]
            self.assertTrue(ws.startswith(f"{sandbox.workspace}-"), ws)

            agent = sandbox.register_container(f"asb-{ws}-agent")
            sandbox.register_container(f"asb-{ws}-proxy")
            sandbox.register_network(f"asb-{ws}")
            sandbox.register_network(f"asb-{ws}-out")
            for unit in (f"asb-{ws}.target", f"asb-{ws}-agent.service",
                         f"asb-{ws}-proxy.service",
                         f"asb-{ws}-forwarder.service",
                         f"asb-{ws}-docker.service"):
                sandbox.register_unit(unit)
            sandbox.register_volume(f"asb-{ws}-session")
            sandbox.register_volume(f"asb-{ws}-containers")
            home = Path(os.path.expanduser("~"))
            project_dir = home / "asb-agent" / repo.name
            state_dir = home / ".local" / "state" / "agent-sandbox" / ws
            self.addCleanup(shutil.rmtree, project_dir, True)
            self.addCleanup(shutil.rmtree, state_dir, True)
            self.assertFalse(sandbox._podman_exists("container", agent))

            with mock.patch.dict(os.environ, sandbox.cli_env()), \
                    mock.patch.object(lifecycle, "SSH_KEY",
                                      sandbox.config_dir / "id_ed25519"):
                # 2. start sobe o workspace e lanca a sessao desanexada.
                out = io.StringIO()
                code = sessions.session_start(checkout, "codex", "harmless",
                                              services=services, out=out)
                self.assertEqual(code, 0, out.getvalue())
                session_id, state = out.getvalue().split()
                self.assertEqual(state, "running")
                terminal_id = f"asb-{session_id}"
                sandbox.register_tmux_session(agent, terminal_id,
                                              getpass.getuser())

                # 3. list: offline, schema 1, so campos de relacionamento.
                out = io.StringIO()
                sessions.session_list(checkout, as_json=True,
                                      services=services, out=out)
                listed = json.loads(out.getvalue())
                self.assertEqual(listed["schemaVersion"], 1)
                [entry] = listed["sessions"]
                self.assertEqual(sorted(entry), STORED_KEYS)
                self.assertEqual((entry["id"], entry["checkoutId"],
                                  entry["state"], entry["terminalId"]),
                                 (session_id, checkout, "running", terminal_id))
                connection = resolve_connection(ws)
                self.assertEqual(entry["cwd"], str(connection.project_root))

                # 4. attach em tela cheia; C-b d devolve o controle.
                screen = bytearray()
                exits = []
                code = sessions.session_attach(
                    session_id, services=services,
                    execute=lambda file, argv: exits.append(
                        _attach_in_pty(file, argv, screen)))
                self.assertEqual(code, 0)
                self.assertEqual(exits, [0], bytes(screen))
                self.assertIn(b"ready", screen)
                self.assertIn(b"detached", screen)

                terminal = TmuxTerminal(connection)
                self.assertIs(terminal.probe(terminal_id), Liveness.ALIVE)
                out = io.StringIO()
                sessions.session_list(None, as_json=False, services=services,
                                      out=out)
                self.assertEqual(
                    out.getvalue(),
                    f"{session_id}  {checkout}  codex  detached  harmless\n")

                # 5. stop: tmux confirma a ausencia e nenhum servidor sobra.
                out = io.StringIO()
                self.assertEqual(sessions.session_stop(
                    session_id, services=services, out=out), 0)
                self.assertEqual(out.getvalue(), f"{session_id} completed\n")
                self.assertIs(terminal.probe(terminal_id), Liveness.DEAD)
                ls = subprocess.run(
                    connection.ssh_argv(("tmux", "ls"), interactive=False),
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=30)
                self.assertEqual(ls.returncode, 1, ls.stdout + ls.stderr)
                self.assertIn("no server running", ls.stderr)

            # 6. purge: containers, redes, units, volumes e arquivos.
            res = sandbox.cli("purge", "--workspace", ws, "--yes")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse(sandbox._podman_exists("container", agent))
            self.assertFalse(state_dir.exists())


if __name__ == "__main__":
    unittest.main()
