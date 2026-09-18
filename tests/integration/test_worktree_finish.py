"""tests/integration/test_worktree_finish.py — finish real de um worktree (Tarefa 12).

Num workspace `asb-test-` de verdade (imagem `localhost/agent-sandbox:latest`),
pelas mesmas fronteiras da TUI (`CheckoutManager` com o `SandboxRuntime` e a
composicao de `asb.interfaces.sessions`):

1. um projeto temporario (primario em `main`) e um worktree `topic` criado
   pelo `CheckoutManager`, cujo nome de pasta e o prefixo da fixture;
2. `SandboxRuntime.ensure()` sobe o workspace a partir do worktree (o mesmo
   `asb-agent up` que o Orca chama);
3. o "agente" commita DENTRO do sandbox, por SSH, um arquivo que o `main`
   do operador tambem mudou: `finish` devolve CONFLICT, deixa o estado de
   conflito do Git no primario e nao remove nada (worktree, branch,
   registro e container continuam);
4. o operador aborta o merge e desfaz o proprio commit no `main` temporario;
   `finish` com limpeza e remocao do branch local devolve CLEANED: o commit
   do sandbox esta no `main`, o sandbox foi purgado pelo `asb-agent purge`
   e esta ausente, o worktree e o branch `topic` sumiram e o vinculo saiu do
   registro;
5. o teardown da fixture prova que nenhum recurso `asb-test-` ficou.

Registro e store vivem sob a raiz temporaria da fixture. Quem escreve em
`~/.local/state/agent-sandbox/<ws>` e o proprio `asb-agent up` (o marcador
`origin`, comportamento existente), que o `purge` remove.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))

from asb import lifecycle  # noqa: E402
from asb.checkouts.manager import CreateCheckout  # noqa: E402
from asb.checkouts.model import FinishCheckout, FinishState  # noqa: E402
from asb.interfaces import sessions, tui  # noqa: E402
from asb.projects.registry import ProjectRegistryError  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()


def _in_sandbox(connection, script: str) -> None:
    """O agente trabalha DENTRO do container, pelo SSH do workspace."""
    result = subprocess.run(
        connection.ssh_argv(("sh", "-c", script), interactive=False),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


class TestWorktreeFinish(unittest.TestCase):
    def test_conflict_preserves_everything_then_finish_cleans_up(self) -> None:
        with SandboxFixture("fin", auto_setup=False) as sandbox:
            primary = sandbox.state_root / "primary"
            primary.mkdir()
            _git(primary, "init", "-q", "-b", "main")
            _git(primary, "config", "user.name", "Operator")
            _git(primary, "config", "user.email", "operator@example.com")
            (primary / "README.md").write_text("# finish\n", encoding="utf-8")
            _git(primary, "add", "README.md")
            _git(primary, "commit", "-q", "-m", "initial commit")

            services = sessions.session_services(
                ROOT, state_dir=sandbox.state_root / "control")
            project = services.registry.add(primary, "main",
                                            sandbox.state_root / "wts")
            services.registry.register_checkout(project.id, primary)
            checkouts = tui.default_checkouts(services)
            # O basename vira o prefixo do workspace deterministico.
            worktree = sandbox.state_root / "wts" / sandbox.workspace
            checkout = checkouts.create(CreateCheckout(
                project.id, "topic", "main", worktree))
            binding = services.registry.checkout(checkout.id)
            ws = binding.workspace
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
            project_dir = home / "asb-agent" / worktree.name
            state_dir = home / ".local" / "state" / "agent-sandbox" / ws
            self.addCleanup(shutil.rmtree, project_dir, True)
            self.addCleanup(shutil.rmtree, state_dir, True)
            self.assertFalse(sandbox._podman_exists("container", agent))

            with mock.patch.dict(os.environ, sandbox.cli_env()), \
                    mock.patch.object(lifecycle, "SSH_KEY",
                                      sandbox.config_dir / "id_ed25519"):
                connection = services.runtime.ensure(binding)
                root = connection.project_root
                _in_sandbox(connection, (
                    f"cd {root} && printf 'agent\\n' > shared.txt && "
                    "git add shared.txt && git -c user.name=Agent "
                    "-c user.email=agent@example.com commit -q -m agent"))
                agent_commit = _git(root, "rev-parse", "HEAD")
                (primary / "shared.txt").write_text("operator\n",
                                                    encoding="utf-8")
                _git(primary, "add", "shared.txt")
                _git(primary, "commit", "-q", "-m", "operator")

                # 3. Conflito: nada removido, estado de conflito intacto.
                result = checkouts.finish(FinishCheckout(
                    checkout.id, "main", cleanup_after_merge=True,
                    delete_merged_branch=True))
                self.assertIs(result.state, FinishState.CONFLICT,
                              result.message)
                self.assertEqual(result.source_commit, agent_commit)
                self.assertIn("shared.txt", result.message)
                self.assertTrue((primary / ".git" / "MERGE_HEAD").exists())
                self.assertNotEqual(_git(primary, "ls-files", "-u"), "")
                self.assertTrue(worktree.is_dir())
                self.assertIn("topic", _git(
                    primary, "branch", "--format=%(refname:short)").split())
                self.assertEqual(services.registry.checkout(checkout.id),
                                 binding)
                self.assertTrue(sandbox._podman_exists("container", agent))

                # 4. Recuperacao do operador, depois finish com limpeza.
                _git(primary, "merge", "--abort")
                _git(primary, "reset", "-q", "--hard", "HEAD~1")
                result = checkouts.finish(FinishCheckout(
                    checkout.id, "main", cleanup_after_merge=True,
                    delete_merged_branch=True))
                self.assertIs(result.state, FinishState.CLEANED,
                              result.message)
                self.assertEqual(result.source_commit, agent_commit)
                subprocess.run(
                    ["git", "-C", str(primary), "merge-base",
                     "--is-ancestor", agent_commit, "main"], check=True)
                self.assertFalse(sandbox._podman_exists("container", agent))
                self.assertTrue(services.runtime.sandbox_absent(binding))
                self.assertFalse(worktree.exists())
                self.assertNotIn("topic", _git(
                    primary, "branch", "--format=%(refname:short)").split())
                with self.assertRaises(ProjectRegistryError):
                    services.registry.checkout(checkout.id)
            self.assertFalse(state_dir.exists())


if __name__ == "__main__":
    unittest.main()
