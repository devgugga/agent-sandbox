"""tests/unit/test_public_contracts.py — Tarefa 1: contrato observavel antes
da decomposicao de `lifecycle.py`, `auth.py` e `doctor.py`.

Este arquivo e a rede de seguranca das Tarefas 2-6: ele PRECISA continuar
verde, SEM ALTERACAO, enquanto aquelas tarefas movem codigo para
`cli/asb/agents/*`, `cli/asb/runtime/*` e o novo `cli/asb/diagnostics/*`. Por
isso nenhuma asercao aqui depende de qual modulo hoje contem um simbolo — so
do que e OBSERVAVEL de fora: os comandos que `cli/asb-agent` registra, as
chaves dos relatorios JSON, a precedencia dos codigos de saida agregados e a
ordem dos checks do `doctor`.

Duas consequencias para a forma como este arquivo injeta fakes:

1. Nunca importa `asb.lifecycle`, `asb.auth` ou `asb.doctor` diretamente.
   Em vez disso usa os NOMES que `cli/asb-agent` ja vincula no seu proprio
   namespace (`self.module.auth_status`, `self.module.auth_verify`,
   `self.module.doctor`, `self.module.PodmanError`) — vinculos que as
   Tarefas 2-5 tem de manter validos mesmo que troquem o import interno de
   onde essas funcoes vem, porque e daquele mesmo vinculo que `main()`
   despacha hoje.
2. So faz `mock.patch`/`mock.patch.object` em modulos que NAO sao alvo desta
   decomposicao — `asb.podman`, `asb.readiness`, `asb.runtime.connection` —
   porque essas chamadas continuam roteadas por eles depois de qualquer
   Tarefa 2-5 (decomposicao preserva comportamento, e nenhuma delas move
   `podman.py`/`readiness.py`).

Excecao unica, documentada: `check_keyring_service()` e chamado por
`diagnose()` como NOME LIVRE, vinculado hoje via
`from .lifecycle import check_keyring_service` dentro de `doctor.py` — um
`from X import Y` copia a referencia na hora do import, entao so
`mock.patch("asb.doctor.check_keyring_service", ...)` intercepta a chamada.
Se uma Tarefa futura apagar `cli/asb/doctor.py` em vez de deixar um modulo
com esse nome, so este patch (usado em `TestDoctorJsonContract`) precisa de
ajuste — nao as asercoes. Ver o relatorio da Tarefa 1 para mais detalhe.

Segue o padrao de carregamento de `tests/unit/test_cli_dispatch.py`
(`SourceFileLoader` para o `cli/asb-agent` sem sufixo `.py`), mas duplica os
helpers minimos (`_load_cli_module`, `_registered_commands`,
`_nested_subcommands`) em vez de reestruturar aquele arquivo so para
compartilha-los.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

import asb.podman as asb_podman  # noqa: E402  (modulo estavel: fora do escopo da decomposicao)
import asb.readiness as asb_readiness  # noqa: E402  (idem)
from asb.runtime.connection import ConnectionInfo  # noqa: E402  (idem)

CLI_PATH = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"


def _load_cli_module():
    """Carrega cli/asb-agent, que nao tem sufixo .py e por isso escapa do
    import normal. Duplicado de tests/unit/test_cli_dispatch.py: aquele
    arquivo ja cobre a paridade registro/despacho do parser e nao deveria
    ser reestruturado so para expor este helper a outro arquivo."""
    loader = importlib.machinery.SourceFileLoader(
        "asb_agent_cli_contracts", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _registered_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("asb-agent nao expoe subcomandos")


def _nested_subcommands(
        parser: argparse.ArgumentParser) -> dict[str, tuple[str, set[str]]]:
    """{comando de topo: (dest do subparser aninhado, nomes registrados)}."""
    nested: dict[str, tuple[str, set[str]]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            for inner in sub._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    nested[name] = (inner.dest, set(inner.choices))
    return nested


def _ok(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def _mixed_verify_ssh_response(argv, **_kwargs):
    """`subprocess.run` fake para `TestAuthJsonContract`'s 2-sobre-1: o
    portao de transporte (`[*ssh_base, "true"]`) sempre passa; a chamada
    REAL por fornecedor (`[*ssh_base, _verify_command(provider)]`, texto
    distinto por fornecedor) recebe uma resposta por fornecedor, sem
    depender de nenhuma constante privada de `asb.auth`."""
    tail = argv[-1]
    if tail == "true":
        return _ok(0)
    if "claude" in tail:
        return _ok(1, stdout="authentication_error: invalid x-api-key")
    if "codex" in tail:
        # 255: transporte SSH caiu durante a chamada (verify_client trata
        # isso como "unreachable" ANTES de olhar para classify_verification).
        return _ok(255)
    if "agy" in tail:
        return _ok(1, stdout="authentication required")
    raise AssertionError(f"comando SSH inesperado no fake: {tail!r}")


class TestRegisteredCliSurface(unittest.TestCase):
    """Comandos que `cli/asb-agent` registra hoje — o inventario que a
    Tarefa 1 (Passo 1) pede, congelado como conjunto para nao depender da
    ordem de registro."""

    def setUp(self):
        self.parser = _load_cli_module().build_parser()

    def test_top_level_commands_are_frozen(self):
        self.assertEqual(_registered_commands(self.parser), {
            "up", "down", "suspend", "resume", "reload-allowlist", "pull",
            "connect", "purge", "build", "login", "auth", "doctor", "list",
            "install-guards", "install-broker", "project", "session", "tui",
        })

    def test_nested_auth_project_session_commands_are_frozen(self):
        nested = _nested_subcommands(self.parser)
        self.assertEqual(nested["auth"], ("auth_command", {"status", "verify"}))
        self.assertEqual(nested["project"], ("project_command", {"add"}))
        self.assertEqual(
            nested["session"],
            ("session_command", {"list", "start", "attach", "stop", "resume"}))


class TestConnectionPayloadContract(unittest.TestCase):
    """`ConnectionInfo.lifecycle_payload` e o UNICO construtor da linha que
    `lifecycle.emit()` imprime para o Orca consumir (docstring do proprio
    metodo). `cli/asb/runtime/connection.py` ja e destino, nao origem, desta
    decomposicao."""

    def test_lifecycle_payload_key_set(self):
        payload = ConnectionInfo.lifecycle_payload(
            "demo", 2222, "operator", Path("/workspace/demo"))
        self.assertEqual(set(payload),
                         {"workspace", "port", "user", "project_root"})


class TestAuthJsonContract(unittest.TestCase):
    """Congela o schema JSON de `auth status`/`auth verify` e a precedencia
    de saida agregada (Passo 1). NOTA (achado empirico, nao um requisito do
    brief): o schema real tem UMA chave a mais do que o exemplo ilustrativo
    do brief em cada relatorio — `workspace` em ambos, e `callBudget` so em
    `verify` — ver o relatorio da Tarefa 1."""

    def setUp(self):
        self.module = _load_cli_module()

    def _status(self, ws: str, agent: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.module.auth_status(ws, agent, json_output=True)
        return code, json.loads(out.getvalue())

    def _verify(self, ws: str, agent: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.module.auth_verify(ws, agent, json_output=True)
        return code, json.loads(out.getvalue())

    def test_status_single_provider_authenticated_exits_zero(self):
        with mock.patch.object(asb_podman, "running", return_value=True), \
                mock.patch.object(asb_podman, "run", return_value=_ok(
                    0, json.dumps({"loggedIn": True}))):
            code, report = self._status("demo", "claude")
        self.assertEqual(set(report),
                         {"schemaVersion", "workspace", "checkedAt", "results"})
        self.assertEqual(code, 0)
        self.assertEqual(set(report["results"][0]), {
            "provider", "state", "checkedAt", "evidence", "remediation",
        })
        self.assertEqual(report["results"][0]["state"], "authenticated")

    def test_status_single_provider_unauthenticated_exits_one(self):
        with mock.patch.object(asb_podman, "running", return_value=True), \
                mock.patch.object(asb_podman, "run", return_value=_ok(
                    0, json.dumps({"loggedIn": False}))):
            code, report = self._status("demo", "claude")
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["state"], "unauthenticated")

    def test_status_infra_failure_exits_two(self):
        with mock.patch.object(
                asb_podman, "running",
                side_effect=self.module.PodmanError("podman indisponivel")):
            code, report = self._status("demo", "claude")
        self.assertEqual(code, 2)
        self.assertEqual(report["results"][0]["state"], "provider_error")

    def test_status_all_never_reaches_zero_or_one_today(self):
        """Achado empirico, nao um requisito do brief: `check_status("agy")`
        devolve `unknown` sem tocar podman (nenhum comando de status local
        comprovado) — estado fora de AUTHENTICATED e de ACCOUNT_MISSING —
        entao `--agent all` agrega SEMPRE para 2, mesmo com claude e codex
        autenticados. Congelado aqui para a Tarefa 6 nao reabrir
        silenciosamente um caminho de `all` para 0/1."""
        with mock.patch.object(asb_podman, "running", return_value=True), \
                mock.patch.object(asb_podman, "run", return_value=_ok(
                    0, json.dumps({"loggedIn": True}))):
            code, report = self._status("demo", "all")
        self.assertEqual(code, 2)
        states = {r["provider"]: r["state"] for r in report["results"]}
        self.assertEqual(states["agy"], "unknown")

    def test_verify_key_set_and_infra_precedence(self):
        unhealthy = asb_readiness.ProbeResult(
            "proxy", "unreachable", "no_route", 5,
            "podman unshare --rootless-netns true")
        with mock.patch.object(asb_podman, "running", return_value=True), \
                mock.patch.object(asb_readiness, "probe_proxy",
                                  return_value=unhealthy):
            code, report = self._verify("demo", "claude")
        self.assertEqual(set(report), {
            "schemaVersion", "workspace", "checkedAt", "callBudget", "results",
        })
        self.assertEqual(code, 2)
        self.assertEqual(report["results"][0]["state"], "unreachable")

    def test_verify_all_exercises_infrastructure_over_account_absence(self):
        """A precedencia 2 > 1 exige DOIS fornecedores no mesmo relatorio:
        um em estado de ausencia de conta (`unauthenticated`/`pending`,
        categoria 1) e outro em infraestrutura/desconhecido (`unknown`,
        `unreachable`, `provider_error`, categoria 2). Nenhuma chamada de
        fornecedor UNICO alcanca essa mistura — precisa de `--agent all`.

        `auth status --agent all` NAO serve: `check_status("agy")` devolve
        sempre `unknown` sem tocar podman (ver
        `test_status_all_never_reaches_zero_or_one_today`), entao todo `all`
        de `status` contamina para 2 antes mesmo de perguntar a claude ou
        codex — nunca sobra um 1 para competir.

        `auth verify --agent all` e diferente: `verify_client` NAO tem esse
        atalho para `agy` — os tres fornecedores passam pelo MESMO pipeline
        (portao de transporte SSH, depois uma chamada real), e
        `classify_verification` so trata `agy` de forma especial ao validar
        o FORMATO de sucesso, nunca para forcar um estado sem chamada (visto
        lendo `cli/asb/auth.py:975-1123` e `:860-940` por inteiro; confirmado
        empiricamente rodando este cenario antes de integra-lo). Por isso
        este teste forca claude e agy a `unauthenticated` (evidencia propria
        do fornecedor, mesmo marcador de
        `test_verify_key_set_and_infra_precedence`'s vizinho em
        `tests/unit/test_auth_verify.py`) e codex a `unreachable` (codigo
        255 do proprio `verify_client`, antes de chegar em
        `classify_verification`) — sem tocar `asb.auth` nem `asb.lifecycle`,
        so `asb.podman`, `asb.readiness` e `subprocess.run`/`Path.is_file`
        globais, como o resto deste arquivo."""
        healthy = asb_readiness.ProbeResult("proxy", "healthy", "ok", 5, "")
        with mock.patch.object(asb_podman, "running", return_value=True), \
                mock.patch.object(asb_podman, "out",
                                  return_value="0.0.0.0:2222"), \
                mock.patch.object(asb_readiness, "probe_proxy",
                                  return_value=healthy), \
                mock.patch("pathlib.Path.is_file", return_value=True), \
                mock.patch("subprocess.run",
                           side_effect=_mixed_verify_ssh_response):
            code, report = self._verify("demo", "all")

        states = {r["provider"]: r["state"] for r in report["results"]}
        self.assertEqual(states, {
            "claude": "unauthenticated",
            "codex": "unreachable",
            "agy": "unauthenticated",
        })
        self.assertEqual(code, 2)


class TestDoctorJsonContract(unittest.TestCase):
    """Congela o schema JSON do `doctor` e a ordem dos seus checks (Passo 1).

    NOTA (achado empirico, nao um requisito do brief): o schema real e
    `{schemaVersion, healthy, infrastructure, providers}` — nao
    `{schemaVersion, checkedAt, checks, summary}` como o exemplo ilustrativo
    do brief — e `doctor()` mapeia `healthy` para 0/1 (nunca 2 por conta
    propria; 2 so chega via excecao nao tratada escapando para `main()`, ver
    `TestDoctorExitPrecedenceViaMain`). Ver o relatorio da Tarefa 1.
    """

    def setUp(self):
        self.module = _load_cli_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake_home = Path(self.tmp.name) / "home"
        self.fake_home.mkdir()

    def _run_doctor(self, root: Path):
        out = io.StringIO()
        with mock.patch.object(asb_podman, "exists", return_value=True), \
                mock.patch.object(asb_podman, "out",
                                  return_value="podman version 5.0.0"), \
                mock.patch("shutil.which", return_value="/usr/bin/mock"), \
                mock.patch("subprocess.run",
                           return_value=mock.Mock(stdout="ok\n", returncode=0)), \
                mock.patch("pathlib.Path.home", return_value=self.fake_home), \
                mock.patch("asb.doctor.check_keyring_service",
                           return_value=(True, "keyring ok", "")):
            with contextlib.redirect_stdout(out):
                code = self.module.doctor(root, as_json=True)
        return code, json.loads(out.getvalue())

    def test_json_key_set_and_check_ordering_when_guards_are_absent(self):
        code, report = self._run_doctor(self.fake_home)

        self.assertEqual(set(report),
                         {"schemaVersion", "healthy", "infrastructure", "providers"})
        self.assertFalse(report["healthy"])
        self.assertEqual(code, 1)
        self.assertEqual(set(report["providers"]), {"claude", "codex", "agy"})
        self.assertEqual(set(report["infrastructure"]),
                         {"healthy", "checks", "workspaces"})
        self.assertEqual(set(report["providers"]["claude"]),
                         {"state", "healthy", "remediation"})

        check_names = [c["name"] for c in report["infrastructure"]["checks"]]
        self.assertEqual(check_names, [
            "podman_installed", "podman_version", "python_version",
            "git_installed", "image", "credentials_volume", "toolcache_volume",
            "keyring_service", "project_dropin_absent", "network_gate",
            "netns_producers_third_party", "guard_claude", "guard_codex",
            "guard_agy", "cli_guard", "docker_broker",
        ])
        self.assertEqual(report["infrastructure"]["workspaces"], [])

    def test_json_healthy_when_guards_match_the_checkout(self):
        fake_root = Path(self.tmp.name) / "checkout"
        guard_bin = fake_root / "cli" / "asb-guard"
        guard_bin.parent.mkdir(parents=True)
        guard_bin.write_text("#!/bin/sh\n")
        cli_bin = fake_root / "cli" / "asb-agent"
        cli_bin.write_text("#!/usr/bin/env python3\n")
        bin_dir = self.fake_home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        for agent in ("claude", "codex", "agy"):
            (bin_dir / f"asb-{agent}").symlink_to(guard_bin)
        (bin_dir / "asb-agent").symlink_to(cli_bin)

        code, report = self._run_doctor(fake_root)

        self.assertTrue(report["healthy"])
        self.assertEqual(code, 0)


class TestDoctorExitPrecedenceViaMain(unittest.TestCase):
    """So `main()` mapeia excecao nao tratada para 2 e `KeyboardInterrupt`
    para 130 — `doctor()` nunca devolve esses codigos sozinho. `shutil.which`
    e a PRIMEIRA chamada de `diagnose()`, entao levanta antes de qualquer
    checagem tocar `root`/`Path.home()`."""

    def setUp(self):
        self.module = _load_cli_module()

    def _run_main(self, argv: list[str]):
        with mock.patch.object(self.module.sys, "argv", argv), \
                mock.patch.object(self.module.sys, "stderr", io.StringIO()), \
                mock.patch.object(self.module.sys, "stdout", io.StringIO()):
            return self.module.main()

    def test_uncaught_exception_bubbles_to_the_infrastructure_code(self):
        with mock.patch("shutil.which", side_effect=RuntimeError("boom")):
            code = self._run_main(["asb-agent", "doctor"])
        self.assertEqual(code, 2)

    def test_keyboard_interrupt_exits_130(self):
        with mock.patch("shutil.which", side_effect=KeyboardInterrupt):
            code = self._run_main(["asb-agent", "doctor"])
        self.assertEqual(code, 130)


if __name__ == "__main__":
    unittest.main()
