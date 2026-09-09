"""tests/integration/test_provider_auth.py — verificacao real e piloto (A4).

Duas categorias de teste, deliberadamente separadas:

1. `TestProviderClientPlumbing` — SINTETICO, roda sempre com
   `python3 -m unittest discover -s tests/integration`. Prova que
   `SandboxFixture.provider_client` cria, nomeia, isola e limpa clientes
   corretamente. NENHUMA chamada a fornecedor algum; nenhuma credencial,
   sintetica ou real, e usada.

2. `TestLiveProviderVerification` — as chamadas REAIS que o brief pede.
   Exigem seleção EXPLICITA deste arquivo (`-p test_provider_auth.py`) E
   `ASB_LIVE_AUTH=1` no ambiente; a ausência de qualquer um dos dois faz
   `skipTest`. Alem disso, exigem `ASB_LIVE_AUTH_WORKSPACE=<workspace>`
   apontando para um workspace que o OPERADOR ja autenticou manualmente via
   `asb-agent login` — esta suite nunca inicia login, e nunca cria volume
   ou container proprio: so chama `auth.verify_client()` (uma chamada real,
   sem retry, por metodo de teste) contra o container que o operador ja tem
   de pe. SKIP aqui NAO e evidencia de aprovacao (ver brief); o relatorio
   final do piloto tem de declarar SKIP explicitamente, nunca silenciar um
   fornecedor deslogado como se tivesse passado.

O cenario completo do piloto (login, cliente novo, concorrencia, apos boot,
descrito no brief) e um runbook operacional do operador, como o de A1
(`docs/validation/2026-09-07-auth-pilot-live.md`) — nao uma suite
automatica que este arquivo tenta reconstruir. O que este arquivo garante e
que a PECA nova (`verify_client`, com orcamento observavel) funciona contra
infraestrutura real quando, e somente quando, o operador optar
explicitamente por isso.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.integration.sandbox_fixture import SandboxFixture

IMAGE_NAME = "localhost/agent-sandbox:latest"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import auth  # noqa: E402

_LIVE_WORKSPACE_ENV = "ASB_LIVE_AUTH_WORKSPACE"


def get_test_image() -> str:
    """Returns the local agent-sandbox image name if available, else ''."""
    res = subprocess.run(
        ["podman", "image", "exists", IMAGE_NAME], capture_output=True)
    return IMAGE_NAME if res.returncode == 0 else ""


def _live_auth_file_selected(argv: list[str] | None = None) -> bool:
    """Exige selecao deliberada deste arquivo, nao apenas env herdado.

    Aceita o padrao exato de `unittest discover -p` usado no runbook e a
    selecao explicita pelo nome de modulo/arquivo. Descoberta ampla nunca
    satisfaz este portao, mesmo com `ASB_LIVE_AUTH=1` esquecido no ambiente.
    """
    args = list(sys.argv if argv is None else argv)
    for index, arg in enumerate(args):
        if arg in ("-p", "--pattern") and index + 1 < len(args):
            if args[index + 1] == "test_provider_auth.py":
                return True
        if arg in ("--pattern=test_provider_auth.py",
                   "test_provider_auth.py",
                   "tests.integration.test_provider_auth"):
            return True
        if Path(arg).name == "test_provider_auth.py":
            return True
        if arg.startswith("tests.integration.test_provider_auth."):
            return True
    return False


def _live_auth_enabled() -> bool:
    return (os.environ.get("ASB_LIVE_AUTH") == "1"
            and _live_auth_file_selected())


class TestProviderClientPlumbing(unittest.TestCase):
    """Sintetico: prova a INFRAESTRUTURA de `provider_client` — nomeacao,
    isolamento `asb-test-`, reaproveitamento sob `fresh=False`, limpeza no
    teardown. Nenhum fornecedor real e tocado; os containers sobem com
    `sleep infinity`, nunca executam `claude`/`codex`/`agy`."""

    def test_fresh_always_creates_a_new_asb_test_prefixed_container(self):
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")
        with SandboxFixture("provclifr", image=IMAGE_NAME,
                            auto_setup=False) as sandbox:
            first = sandbox.provider_client("claude", fresh=True)
            second = sandbox.provider_client("claude", fresh=True)
            self.assertNotEqual(first, second)
            for name in (first, second):
                self.assertTrue(name.startswith("asb-test-"))
                self.assertTrue(name.startswith(sandbox._prefix))

    def test_non_fresh_reuses_the_same_client_per_provider(self):
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")
        with SandboxFixture("provclireuse", image=IMAGE_NAME,
                            auto_setup=False) as sandbox:
            first = sandbox.provider_client("codex", fresh=False)
            second = sandbox.provider_client("codex", fresh=False)
            self.assertEqual(first, second)

    def test_fresh_and_non_fresh_never_collide(self):
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")
        with SandboxFixture("provclimix", image=IMAGE_NAME,
                            auto_setup=False) as sandbox:
            login_client = sandbox.provider_client("agy", fresh=False)
            fresh_client = sandbox.provider_client("agy", fresh=True)
            self.assertNotEqual(login_client, fresh_client)

    def test_rejects_unknown_provider(self):
        # A validacao acontece antes de qualquer acesso a estado da fixture;
        # chamar o metodo real sem construir ambiente prova esse ramo sem
        # criar volumes/containers e sem depender da imagem local.
        with self.assertRaises(ValueError):
            SandboxFixture.provider_client(None, "gemini", fresh=True)

    def test_provider_client_container_never_mounts_production_credentials(self):
        """Guarda de isolamento: os volumes NOMEADOS nos mounts sao SOMENTE
        os desta fixture (prefixo `asb-test-`); o volume de producao
        `asb-credentials` nunca aparece como NOME de volume montado. (A
        string aparece de qualquer forma como caminho de DESTINO dentro do
        container — `/run/asb-credentials` — por isso o teste olha o campo
        `Name` de cada mount, nunca o JSON inteiro.)"""
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")
        with SandboxFixture("provclivol", image=IMAGE_NAME,
                            auto_setup=False) as sandbox:
            name = sandbox.provider_client("claude", fresh=True)
            inspect = subprocess.run(
                ["podman", "inspect", name, "--format",
                 "{{range .Mounts}}{{.Name}}\n{{end}}"],
                capture_output=True, text=True, check=True)
            mounted_volume_names = [
                line for line in inspect.stdout.splitlines() if line.strip()]
            self.assertIn(sandbox.credentials_volume, mounted_volume_names)
            self.assertNotIn("asb-credentials", mounted_volume_names)
            for volume_name in mounted_volume_names:
                self.assertTrue(
                    volume_name.startswith("asb-test-"),
                    f"volume nao prefixado montado: {volume_name!r}")

    def test_teardown_leaves_no_provider_client_running(self):
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")
        fixture = SandboxFixture("provclidown", image=IMAGE_NAME,
                                 auto_setup=False)
        with fixture as sandbox:
            name = sandbox.provider_client("agy", fresh=True)
            running = subprocess.run(
                ["podman", "ps", "--filter", f"name=^{name}$", "--quiet"],
                capture_output=True, text=True)
            self.assertTrue(running.stdout.strip(), "cliente nao subiu")

        after = subprocess.run(
            ["podman", "ps", "-a", "--filter", f"name=^{name}$", "--quiet"],
            capture_output=True, text=True)
        self.assertEqual(after.stdout.strip(), "",
                         "container sobreviveu ao teardown")


@unittest.skipUnless(
    _live_auth_enabled(),
    "chamada real ao fornecedor exige selecao explicita de "
    "test_provider_auth.py E ASB_LIVE_AUTH=1; SKIP nao e evidencia de "
    "aprovacao (ver task-A4-brief.md)")
class TestLiveProviderVerification(unittest.TestCase):
    """Chamadas REAIS via `auth.verify_client()`. So rodam com
    `ASB_LIVE_AUTH=1` E `ASB_LIVE_AUTH_WORKSPACE=<workspace ja autenticado>`
    explicitos. Esta suite nunca chama `auth.login`, nunca cria volume ou
    container: verifica o workspace que o operador ja subiu e autenticou.

    Uma chamada por fornecedor, sem retry (mesmo orcamento de
    `verify_client`); a contagem observada via `auth.call_budget()` e
    impressa no stderr para o operador colar no relatorio do piloto.
    """

    def setUp(self):
        self.ws = os.environ.get(_LIVE_WORKSPACE_ENV)
        if not self.ws:
            self.skipTest(
                f"defina {_LIVE_WORKSPACE_ENV}=<workspace ja autenticado "
                "via 'asb-agent login'> para exercitar a verificacao real")
        auth.reset_call_budget()

    def test_verify_client_makes_exactly_one_call_per_provider(self):
        names = auth.lifecycle.names(self.ws)
        container = names["agent"]
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                result = auth.verify_client(
                    provider, container, proxy_container=names["proxy"])
                print(f"[piloto A4] {provider}: {result.state} "
                     f"({result.evidence})", file=sys.stderr)
                spent = auth.call_budget().get(provider, 0)
                print(f"[piloto A4] {provider}: chamadas gastas = {spent}",
                     file=sys.stderr)
                self.assertEqual(
                    spent, 1,
                    f"{provider}: piloto live exige exatamente uma chamada "
                    "real; infraestrutura quebrada nao e evidencia")
                self.assertEqual(
                    result.state, "authenticated",
                    f"{provider}: somente sucesso autenticado constitui "
                    "evidencia live; estado recebido: {result.state}")


if __name__ == "__main__":
    unittest.main()
