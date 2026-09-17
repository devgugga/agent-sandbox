"""tests/integration/test_entrypoint_concurrency.py — agentes que partem juntos.

Boot A1 do piloto (docs/validation/startup-auth-pilot.md §6.9): com a espera
unica por rede, todos os workspaces partem no mesmo instante. O entrypoint
materializa o manifesto de configuracao dentro de `~/.claude`, que e volume
COMPARTILHADO, e nomeava a copia temporaria com `$$` — que vale 1 em todo
container, porque o entrypoint e PID 1. Um agente apagava a copia que o outro
fazia e morria com `rm: cannot remove ...asb-staging.1/...: Directory not empty`.

O teste roda o entrypoint REAL da imagem, varias vezes em pares simultaneos,
sobre um volume compartilhado, e exige que toda partida saia 0 e deixe o
destino inteiro e sem sobras.
"""
from __future__ import annotations

import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.integration.sandbox_fixture import SandboxFixture


IMAGE_NAME = "localhost/agent-sandbox:latest"
ROUNDS = 6
PARALLEL = 2
DIRS, FILES_PER_DIR = 30, 100


def _image_available() -> bool:
    return subprocess.run(["podman", "image", "exists", IMAGE_NAME]).returncode == 0


@unittest.skipUnless(_image_available(), "requer a imagem do agente")
class TestEntrypointConcurrentStart(unittest.TestCase):
    def test_simultaneous_starts_share_the_config_volume_safely(self) -> None:
        with SandboxFixture("stagerace", image=IMAGE_NAME, auto_setup=False) as sandbox:
            home = subprocess.run(
                ["podman", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                 IMAGE_NAME, "-c", "getent passwd 1000 | cut -d: -f6"],
                capture_output=True, text=True, check=True).stdout.strip()
            self.assertTrue(home.startswith("/"), home)

            volume = sandbox.register_volume(f"{sandbox._prefix}-sharedhome")
            subprocess.run(["podman", "volume", "create", volume],
                           capture_output=True, check=True)

            stage = sandbox.state_root / "stage"
            src = stage / "plugins"
            for d in range(DIRS):
                (src / f"d{d}").mkdir(parents=True)
                for f in range(FILES_PER_DIR):
                    (src / f"d{d}" / f"f{f}").write_text("x" * 64)
            dst = f"{home}/.claude/plugins"
            (stage / "manifest.tsv").write_text(f"plugins\t{dst}\n")

            def start(name: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["podman", "run", "--rm", "--name", name, "--network", "none",
                     "-v", f"{volume}:{home}/.claude",
                     "-v", f"{stage}:/run/asb-config:ro,Z",
                     IMAGE_NAME, "true"],
                    capture_output=True, text=True)

            failures: list[str] = []
            for r in range(ROUNDS):
                names = [sandbox.register_container(f"{sandbox._prefix}-r{r}-{i}")
                         for i in range(PARALLEL)]
                with ThreadPoolExecutor(PARALLEL) as pool:
                    results = list(pool.map(start, names))
                failures += [f"rodada {r}, {n}: rc={res.returncode} {res.stderr.strip()[-300:]}"
                             for n, res in zip(names, results) if res.returncode != 0]
            self.assertEqual(failures, [], "partida simultanea falhou")

            listing = subprocess.run(
                ["podman", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                 "-v", f"{volume}:{home}/.claude", IMAGE_NAME, "-c",
                 f"ls -A {home}/.claude; find {dst} -type f | wc -l"],
                capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(listing[-1], str(DIRS * FILES_PER_DIR),
                             "destino incompleto depois das partidas")
            leftovers = [e for e in listing[:-1] if ".asb-" in e]
            self.assertEqual(leftovers, [], "copias temporarias ficaram no volume")


if __name__ == "__main__":
    unittest.main()
