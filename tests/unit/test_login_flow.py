"""Testes do fluxo de login seletivo, persistencia e fixacao de versoes (A3).

Nenhum teste aqui inicia login real nem alcanca um fornecedor: subprocesso,
lock por fornecedor e criacao/remocao de cliente sao todos simulados. O
container de login so existe como uma lista de argumentos capturada.

Contexto empirico (Tarefa A1, docs/validation/2026-09-07-*.md):

* Claude Code 2.1.263 abre a credencial com `O_RDONLY | O_NOFOLLOW`. Num
  symlink o Linux devolve ELOOP, que o Claude classifica como
  `refused-symlink` e trata como credencial AUSENTE. O `image/entrypoint.sh`
  ainda criava esse symlink e, pior, precriava o alvo como arquivo de 0 bytes
  (`: > "$stored"`), que jamais poderia ser lido como JSON. O volume de
  producao tem literalmente `claude.json` com 0 bytes ao lado de um
  `codex-auth.json` saudavel de 3876 bytes.
* `rename`/`os.replace` sobre um SYMLINK substitui o proprio symlink e corta o
  vinculo com o volume; sobre um arquivo BIND-MONTADO falha com EBUSY. Só o
  DIRETORIO montado sobrevive ao padrao de escrita real dos fornecedores.
* `claude /login` responde "isn't available in this environment" e sai com
  codigo 0 SEM logar. O comando real e `claude auth login`.
* `agy` nao tem status local e `agy -p ping` bloqueia 60s quando deslogado.

ATENCAO: `lifecycle.ensure_credential_dirs` resolve o mountpoint REAL do
volume via `podman volume inspect` e cria diretorios nele. Qualquer teste que
chegue a `credential_mount_args` PRECISA mocka-lo, sob pena de escrever no
volume de credenciais de producao do operador.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import auth, keyring, lifecycle  # noqa: E402
from asb.auth import AuthResult  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "image" / "entrypoint.sh"
CONTAINERFILE = ROOT / "image" / "Containerfile"

FAKE_ROOT = Path("/fake/root")


def _ok(returncode: int = 0):
    return mock.MagicMock(returncode=returncode, stdout="", stderr="")


@contextmanager
def login_harness(*, exec_returncode: int = 0, tty: bool = True,
                  image_exists: bool = True):
    """Isola `auth.login` do mundo: nenhum podman, nenhum subprocesso real.

    Devolve um dicionario com o que foi capturado, para que cada teste afirme
    sobre argumentos em vez de sobre efeitos colaterais.
    """
    captured: dict[str, list] = {
        "run": [], "exec": [], "removed": [], "locked": []}

    def fake_run(*args, **kwargs):
        captured["run"].append(list(args))
        if args and args[0] == "rm":
            captured["removed"].append(args[-1])
        return _ok()

    def fake_subprocess_run(cmd, *a, **kw):
        captured["exec"].append(list(cmd))
        return _ok(exec_returncode)

    @contextmanager
    def fake_lock(provider: str):
        captured["locked"].append(provider)
        yield Path(f"/fake/locks/login-{provider}.lock")

    with mock.patch.object(auth.podman, "run", side_effect=fake_run), \
            mock.patch.object(auth.podman, "exists",
                              side_effect=lambda kind, name: image_exists), \
            mock.patch.object(auth.podman, "require_binary",
                              return_value="podman"), \
            mock.patch.object(auth.subprocess, "run",
                              side_effect=fake_subprocess_run), \
            mock.patch.object(auth.lifecycle, "ensure_keyring_service"), \
            mock.patch.object(auth.lifecycle, "ensure_keyring_runtime_volume",
                              return_value="asb-keyring-runtime"), \
            mock.patch.object(auth.lifecycle, "ensure_credentials_volume",
                              return_value="asb-credentials"), \
            mock.patch.object(auth.lifecycle, "credential_mount_args",
                              return_value=["--mount", "type=volume,fake"]), \
            mock.patch.object(auth, "operator_lock", fake_lock), \
            mock.patch.object(auth.sys.stdin, "isatty", return_value=tty), \
            redirect_stderr(io.StringIO()):
        yield captured


class TestLoginCommandTable(unittest.TestCase):
    """O contrato exato dos comandos de login, verbatim do brief da A3."""

    def test_login_command_per_provider(self):
        self.assertEqual(auth.login_command("claude"),
                         ("claude", "auth", "login"))
        self.assertEqual(auth.login_command("codex"),
                         ("codex", "login", "--device-auth"))
        self.assertEqual(auth.login_command("agy"), ("agy",))

    def test_login_command_rejects_all_and_unknown(self):
        for bad in ("all", "gemini", ""):
            with self.subTest(provider=bad):
                with self.assertRaises(ValueError):
                    auth.login_command(bad)

    def test_no_login_command_is_the_dead_slash_login(self):
        """`claude /login` sai com 0 SEM logar (A1): um falso verde que manda
        o operador embora achando que a credencial foi gravada."""
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("/login", auth.login_command(provider))

    def test_claude_login_never_selects_api_billing(self):
        """`--console` seleciona faturamento por API em vez da assinatura."""
        self.assertNotIn("--console", auth.login_command("claude"))

    def test_no_login_command_is_a_version_query(self):
        """`--version` responde 0 com o agente deslogado."""
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("--version", auth.login_command(provider))

    def test_there_is_one_command_for_each_installed_provider(self):
        self.assertEqual(set(auth.LOGIN_COMMANDS), {"claude", "codex", "agy"})


class TestLoginSelection(unittest.TestCase):
    def test_login_verifies_a_fresh_client_and_fails_when_unauthenticated(self):
        """Caso do brief: o login interativo termina bem, mas o cliente NOVO
        diz deslogado — o fluxo tem de reprovar."""
        with login_harness(), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "claude", "unauthenticated", "2026-09-07T00:00:00Z",
                "native_status", "login")
            self.assertNotEqual(auth.login(FAKE_ROOT, "claude"), 0)
            verify.assert_called_once_with("claude")

    def test_login_returns_zero_only_when_the_fresh_client_is_authenticated(self):
        with login_harness(), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "2026-09-07T00:00:00Z",
                "native_status", "")
            self.assertEqual(auth.login(FAKE_ROOT, "codex"), 0)

    def test_login_selective_touches_only_the_requested_provider(self):
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "x", "native_status", "")
            auth.login(FAKE_ROOT, "codex")

        joined = " ".join(" ".join(c) for c in captured["exec"])
        self.assertIn("codex login --device-auth", joined)
        self.assertNotIn("claude auth login", joined)
        self.assertEqual(captured["locked"], ["codex"])

    def test_login_default_is_all_and_runs_each_provider_once(self):
        seen = []

        def fake_verify(provider):
            seen.append(provider)
            return AuthResult(provider, "authenticated", "x",
                              "native_status", "")

        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=fake_verify):
            auth.login(FAKE_ROOT)

        self.assertEqual(seen, ["claude", "codex", "agy"])
        self.assertEqual(captured["locked"], ["claude", "codex", "agy"])

    def test_login_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            auth.login(FAKE_ROOT, "gemini")

    def test_login_all_is_not_zero_while_agy_is_pending(self):
        """A4 ainda nao esta integrado: sem `verify_client`, o resultado do
        agy e explicitamente pendente e nao autoriza anunciar login completo
        de `all`."""
        with login_harness():
            rc = auth.login(FAKE_ROOT, "all")
        self.assertNotEqual(rc, 0)

    def test_login_preserves_a_per_provider_result_on_partial_login(self):
        """Um fornecedor que falha nao apaga o resultado dos outros, e o
        codigo agregado nao vira 0."""
        def fake_verify(provider):
            state = "unauthenticated" if provider == "claude" else "authenticated"
            return AuthResult(provider, state, "x", "native_status", "")

        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=fake_verify):
            rc = auth.login(FAKE_ROOT, "claude")
            self.assertNotEqual(rc, 0)
            # O fornecedor seguinte continua sendo tentado quando pedido.
            self.assertEqual(auth.login(FAKE_ROOT, "codex"), 0)
        self.assertEqual(captured["locked"], ["claude", "codex"])


class TestLoginTtyAndCancellation(unittest.TestCase):
    def test_login_without_a_tty_fails_with_guidance_instead_of_hanging(self):
        stderr = []
        with login_harness(tty=False) as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify, \
                mock.patch("builtins.print",
                           side_effect=lambda *a, **kw: stderr.append(
                               " ".join(str(x) for x in a))):
            rc = auth.login(FAKE_ROOT, "claude")

        self.assertNotEqual(rc, 0)
        self.assertEqual(captured["run"], [],
                         "sem TTY nao se cria container algum")
        self.assertEqual(captured["exec"], [])
        verify.assert_not_called()
        self.assertTrue(any("terminal" in m.lower() for m in stderr),
                        f"faltou orientacao sobre o terminal: {stderr}")

    def test_cancellation_returns_130_and_removes_only_its_own_client(self):
        """Cancelar preserva dados: nada de volume, nada de credencial
        removida — apenas o container efemero desta execucao."""
        def cancel(cmd, *a, **kw):
            raise KeyboardInterrupt

        with login_harness() as captured, \
                mock.patch.object(auth.subprocess, "run", side_effect=cancel), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            rc = auth.login(FAKE_ROOT, "claude")

        self.assertEqual(rc, 130)
        verify.assert_not_called()
        self.assertTrue(captured["removed"],
                        "o cliente desta execucao tem de ser removido")
        for removed in captured["removed"]:
            self.assertTrue(removed.startswith("asb-login-claude-")
                            or removed.startswith("asb-verify-claude-"))
        commands = [c[0] for c in captured["run"] if c]
        self.assertNotIn("volume", commands)

    def test_sigint_exit_code_from_the_provider_is_treated_as_cancellation(self):
        with login_harness(exec_returncode=130), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            rc = auth.login(FAKE_ROOT, "claude")
        self.assertEqual(rc, 130)
        verify.assert_not_called()


class TestCancellationDuringAll(unittest.TestCase):
    def test_a_cancelled_all_still_reports_what_was_already_verified(self):
        """Cancelar no codex nao pode engolir o resultado ja obtido do claude:
        o operador precisa saber o que ficou pronto."""
        reported = []

        def fake_exec(cmd, *a, **kw):
            if "codex login --device-auth" in " ".join(str(c) for c in cmd):
                raise KeyboardInterrupt
            return _ok()

        with login_harness(), \
                mock.patch.object(auth.subprocess, "run", side_effect=fake_exec), \
                mock.patch("asb.auth._report_login",
                           side_effect=reported.append), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "claude", "authenticated", "x", "native_status", "")
            rc = auth.login(FAKE_ROOT, "all")

        self.assertEqual(rc, 130)
        self.assertEqual([r.provider for r in reported], ["claude"])


class TestLoginClientIdentity(unittest.TestCase):
    def test_client_names_are_unique_per_run(self):
        first = auth._client_name("login", "claude")
        second = auth._client_name("login", "claude")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("asb-login-claude-"))

    def test_cleanup_never_removes_the_shared_asb_login_container(self):
        """`asb-login` era um nome fixo: duas execucoes concorrentes se
        matavam. Nenhuma remocao pode citar esse nome nem o do keyring."""
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "x", "native_status", "")
            auth.login(FAKE_ROOT, "codex")

        self.assertNotIn("asb-login", captured["removed"])
        self.assertNotIn(lifecycle.KEYRING_CONTAINER, captured["removed"])
        self.assertTrue(captured["removed"])

    def test_login_client_is_removed_before_the_fresh_client_is_verified(self):
        """Encerrar o cliente de login e verificar OUTRO cliente antes de
        declarar persistencia valida"."""
        order = []

        def fake_run(*args, **kwargs):
            if args and args[0] == "rm":
                order.append(f"rm {args[-1]}")
            return _ok()

        def fake_verify(provider):
            order.append("verify")
            return AuthResult(provider, "authenticated", "x",
                              "native_status", "")

        with login_harness(), \
                mock.patch.object(auth.podman, "run", side_effect=fake_run), \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=fake_verify):
            auth.login(FAKE_ROOT, "codex")

        self.assertIn("verify", order)
        removals = [i for i, e in enumerate(order) if e.startswith("rm ")]
        self.assertTrue(removals)
        self.assertLess(min(removals), order.index("verify"))

    def test_login_client_mounts_the_approved_credential_directories(self):
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "x", "native_status", "")
            auth.login(FAKE_ROOT, "codex")

        creations = [c for c in captured["run"] if c and c[0] == "run"]
        self.assertTrue(creations)
        self.assertIn("type=volume,fake", creations[0])
        self.assertIn(
            "type=tmpfs,destination=/run/asb-credentials/keyrings,"
            "ro,notmpcopyup,tmpfs-mode=000", creations[0])


class TestLoginKeyringContract(unittest.TestCase):
    """Contrato herdado de `TestLoginKeyringIntegration`, que vivia em
    `test_auth.py` quando o login morava em `lifecycle.py`."""

    def _agent_creation(self, captured):
        creations = [c for c in captured["run"] if c and c[0] == "run"]
        self.assertTrue(creations, "nenhum container foi criado")
        return creations[0]

    def _login_codex(self):
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "x", "native_status", "")
            auth.login(FAKE_ROOT, "codex")
        return captured

    def test_the_keyring_service_is_up_before_any_client_is_created(self):
        order = []
        with login_harness() as captured, \
                mock.patch.object(auth.lifecycle, "ensure_keyring_service",
                                  side_effect=lambda: order.append("keyring")), \
                mock.patch.object(
                    auth.podman, "run",
                    side_effect=lambda *a, **kw: (
                        order.append("run") if a and a[0] == "run" else None,
                        _ok())[1]), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "authenticated", "x", "native_status", "")
            auth.login(FAKE_ROOT, "codex")

        self.assertIn("keyring", order)
        self.assertIn("run", order)
        self.assertLess(order.index("keyring"), order.index("run"))

    def test_the_client_shares_the_keyring_bus_read_only(self):
        args = self._agent_creation(self._login_codex())
        self.assertIn("asb-keyring-runtime:/run/asb-keyring:ro,z", args)
        self.assertIn(
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", args)

    def test_the_client_never_receives_the_keyring_passphrase(self):
        """O cliente fala com o Secret Service pelo socket. A passphrase e do
        singleton; entrega-la aqui ampliaria o raio de exposicao sem uso."""
        args = self._agent_creation(self._login_codex())
        self.assertFalse(any("ASB_KEYRING_PASS" in str(a) for a in args))

    def test_the_client_is_removed_even_when_verification_fails(self):
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "codex", "unauthenticated", "x", "native_status", "login")
            self.assertNotEqual(auth.login(FAKE_ROOT, "codex"), 0)

        self.assertTrue(captured["removed"])
        self.assertNotIn(lifecycle.KEYRING_CONTAINER, captured["removed"])

    def test_the_client_is_removed_even_when_verification_raises(self):
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=auth.podman.PodmanError("boom")):
            with self.assertRaises(auth.podman.PodmanError):
                auth.login(FAKE_ROOT, "codex")

        self.assertTrue(captured["removed"])
        self.assertNotIn(lifecycle.KEYRING_CONTAINER, captured["removed"])

    def test_no_status_command_used_by_the_verification_is_a_version_query(self):
        """Herdado de `TestVerificacaoDeLogin`: `--version` responde 0 com o
        agente deslogado, e um falso verde e pior que nenhuma checagem."""
        for provider, command in auth.STATUS_COMMANDS.items():
            with self.subTest(provider=provider):
                self.assertNotIn("--version", command)


class TestOperatorLock(unittest.TestCase):
    def test_second_holder_gets_a_busy_error_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(keyring, "CONFIG", Path(tmp)):
                with auth.operator_lock("claude"):
                    with self.assertRaises(auth.LoginBusy):
                        with auth.operator_lock("claude"):
                            pass

    def test_lock_is_per_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(keyring, "CONFIG", Path(tmp)):
                with auth.operator_lock("claude"):
                    with auth.operator_lock("codex"):
                        pass

    def test_lock_is_released_on_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(keyring, "CONFIG", Path(tmp)):
                with auth.operator_lock("claude"):
                    pass
                with auth.operator_lock("claude"):
                    pass

    def test_lock_directory_is_not_world_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(keyring, "CONFIG", Path(tmp)):
                with auth.operator_lock("claude") as path:
                    self.assertEqual(path.parent.stat().st_mode & 0o077, 0)

    def test_busy_session_is_reported_without_starting_a_client(self):
        @contextmanager
        def busy(provider):
            raise auth.LoginBusy(provider)
            yield  # pragma: no cover

        with login_harness() as captured, \
                mock.patch.object(auth, "operator_lock", busy), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            rc = auth.login(FAKE_ROOT, "claude")

        self.assertNotEqual(rc, 0)
        self.assertEqual(captured["exec"], [])
        verify.assert_not_called()


class TestVerifyFreshClient(unittest.TestCase):
    def test_verify_uses_its_own_ephemeral_client_and_removes_it(self):
        created, removed = [], []

        def fake_run(*args, **kwargs):
            if args and args[0] == "run":
                created.append(args[args.index("--name") + 1])
            if args and args[0] == "rm":
                removed.append(args[-1])
            return _ok()

        with mock.patch.object(auth.podman, "run", side_effect=fake_run), \
                mock.patch.object(auth.lifecycle, "ensure_keyring_runtime_volume",
                                  return_value="asb-keyring-runtime"), \
                mock.patch.object(auth.lifecycle, "credential_mount_args",
                                  return_value=["--mount", "type=volume,fake"]), \
                mock.patch("asb.auth.check_status") as check:
            check.return_value = AuthResult(
                "claude", "authenticated", "x", "native_status", "")
            result = auth.verify_fresh_client("claude")

        self.assertEqual(result.state, "authenticated")
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].startswith("asb-verify-claude-"))
        self.assertEqual(removed, created)
        check.assert_called_once_with("claude", created[0])

    def test_verify_removes_the_client_even_when_the_check_raises(self):
        removed = []

        def fake_run(*args, **kwargs):
            if args and args[0] == "rm":
                removed.append(args[-1])
            return _ok()

        with mock.patch.object(auth.podman, "run", side_effect=fake_run), \
                mock.patch.object(auth.lifecycle, "ensure_keyring_runtime_volume",
                                  return_value="asb-keyring-runtime"), \
                mock.patch.object(auth.lifecycle, "credential_mount_args",
                                  return_value=[]), \
                mock.patch("asb.auth.check_status",
                           side_effect=auth.podman.PodmanError("boom")):
            with self.assertRaises(auth.podman.PodmanError):
                auth.verify_fresh_client("claude")

        self.assertTrue(removed)

    def test_verify_removes_the_client_even_when_creation_fails(self):
        """O `try` comeca ANTES do `podman run`: um Ctrl-C ou uma falha entre
        a criacao e o corpo deixaria o cliente de pe para sempre."""
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(list(args))
            if args and args[0] == "run":
                raise auth.podman.PodmanError("criacao falhou")
            return _ok()

        with mock.patch.object(auth.podman, "run", side_effect=fake_run), \
                mock.patch.object(auth.lifecycle, "ensure_keyring_runtime_volume",
                                  return_value="asb-keyring-runtime"), \
                mock.patch.object(auth.lifecycle, "credential_mount_args",
                                  return_value=[]):
            with self.assertRaises(auth.podman.PodmanError):
                auth.verify_fresh_client("claude")

        self.assertTrue(any(c and c[0] == "rm" for c in calls),
                        "a limpeza nao rodou apos falha na criacao")

    def test_verify_of_agy_is_pending_and_never_touches_podman(self):
        """`agy -p ping` bloqueia 60s quando deslogado (A1). Enquanto A4 nao
        entrega `verify_client`, o resultado e pendente, jamais 'logado'."""
        with mock.patch.object(auth.podman, "run") as run:
            result = auth.verify_fresh_client("agy")
        run.assert_not_called()
        self.assertEqual(result.state, "pending")
        self.assertNotEqual(result.state, "authenticated")

    def test_verify_rejects_all(self):
        with self.assertRaises(ValueError):
            auth.verify_fresh_client("all")


class TestLoginNeverLeaksCredentials(unittest.TestCase):
    def test_evidence_never_carries_captured_provider_output(self):
        """`auth.py` monta evidencia com texto enlatado mais um codigo de
        retorno. O login nao pode regredir isso interpolando stdout/stderr do
        fornecedor, que e onde tokens e codigos OAuth aparecem."""
        secret = "sk-ant-oat01-SEGREDO"

        def fake_subprocess_run(cmd, *a, **kw):
            return mock.MagicMock(returncode=1, stdout=secret, stderr=secret)

        with login_harness() as captured, \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=fake_subprocess_run), \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "claude", "unauthenticated", "x", "native_status", "login")
            auth.login(FAKE_ROOT, "claude")

        rendered = " ".join(
            " ".join(str(p) for p in c) for c in captured["run"] + captured["exec"])
        self.assertNotIn(secret, rendered)

    def test_interactive_login_never_captures_provider_output(self):
        """Capturar a saida do login a traria para dentro do processo, de onde
        ela pode vazar para log. O exec interativo herda o TTY e nao captura."""
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client") as verify:
            verify.return_value = AuthResult(
                "claude", "unauthenticated", "x", "native_status", "login")
            auth.login(FAKE_ROOT, "claude")

        self.assertTrue(captured["exec"])
        self.assertIn("-it", captured["exec"][0])


class TestCredentialDirectoryMounts(unittest.TestCase):
    """A1 provou: `rename` sobre symlink corta o vinculo com o volume, e
    sobre arquivo bind-montado falha com EBUSY. Só o DIRETORIO montado
    sobrevive."""

    def test_credential_mount_args_mount_directories_by_subpath(self):
        with mock.patch.object(lifecycle, "ensure_credentials_volume",
                               return_value="asb-credentials"), \
                mock.patch.object(lifecycle, "ensure_credential_dirs"):
            args = lifecycle.credential_mount_args(Path("/home/tester"))

        joined = " ".join(args)
        self.assertIn("volume-subpath=claude", joined)
        self.assertIn("volume-subpath=codex", joined)
        self.assertIn("dst=/home/tester/.claude", joined)
        self.assertIn("dst=/home/tester/.codex", joined)
        self.assertIn("src=asb-credentials", joined)
        self.assertEqual(args.count("--mount"), 2)

    def test_credential_mounts_are_never_single_files(self):
        with mock.patch.object(lifecycle, "ensure_credentials_volume",
                               return_value="asb-credentials"), \
                mock.patch.object(lifecycle, "ensure_credential_dirs"):
            joined = " ".join(lifecycle.credential_mount_args(Path("/home/t")))
        self.assertNotIn(".credentials.json", joined)
        self.assertNotIn("auth.json", joined)

    def test_credential_mount_args_creates_the_provider_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            with mock.patch.object(lifecycle.podman, "exists",
                                   return_value=True), \
                    mock.patch.object(lifecycle.podman, "out",
                                      return_value=str(mountpoint)):
                lifecycle.credential_mount_args(Path("/home/tester"))

            for sub in ("claude", "codex"):
                path = mountpoint / sub
                self.assertTrue(path.is_dir(), f"{sub} nao foi criado")
                self.assertEqual(path.stat().st_mode & 0o077, 0,
                                 f"{sub} nao pode ser legivel por outros")

    def test_credential_mount_args_delegates_the_filesystem_work(self):
        """`ensure_credential_dirs` toca um caminho REAL (o mountpoint que o
        podman reporta). Todo teste que chama `credential_mount_args` tem de
        mocka-lo; esta guarda existe para que a delegacao nao suma em
        silencio e leve os outros testes a escrever num volume de verdade."""
        with mock.patch.object(lifecycle, "ensure_credentials_volume",
                               return_value="asb-credentials"), \
                mock.patch.object(lifecycle, "ensure_credential_dirs") as dirs:
            lifecycle.credential_mount_args(Path("/home/t"))
        dirs.assert_called_once_with("asb-credentials")

    def test_credential_setup_never_creates_credential_files(self):
        """A causa confirmada: `: > "$stored"` deixava um arquivo de 0 bytes
        que nunca poderia ser lido como JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            with mock.patch.object(lifecycle.podman, "exists",
                                   return_value=True), \
                    mock.patch.object(lifecycle.podman, "out",
                                      return_value=str(mountpoint)):
                lifecycle.credential_mount_args(Path("/home/tester"))

            files = [p for p in mountpoint.rglob("*") if p.is_file()]
            self.assertEqual(files, [])

    def test_credential_setup_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            (mountpoint / "codex").mkdir(parents=True)
            existing = mountpoint / "codex" / "auth.json"
            existing.write_text('{"token": "preservado"}')
            with mock.patch.object(lifecycle.podman, "exists",
                                   return_value=True), \
                    mock.patch.object(lifecycle.podman, "out",
                                      return_value=str(mountpoint)):
                lifecycle.credential_mount_args(Path("/home/tester"))
            self.assertEqual(existing.read_text(), '{"token": "preservado"}')

    def test_up_mounts_the_credential_directories_into_the_agent(self):
        source = (ROOT / "cli" / "asb" / "lifecycle.py").read_text()
        self.assertIn("credential_mount_args", source)


class TestEntrypointCredentialLayout(unittest.TestCase):
    """A causa confirmada em A1 vive nestas linhas do entrypoint."""

    def setUp(self):
        self.text = ENTRYPOINT.read_text(encoding="utf-8")
        # O entrypoint mantem os trechos removidos CITADOS em comentario, como
        # registro da causa. O contrato e sobre o que ele EXECUTA.
        self.code = "\n".join(
            line for line in self.text.splitlines()
            if not line.lstrip().startswith("#"))

    def test_entrypoint_no_longer_creates_empty_credential_files(self):
        self.assertNotIn(': > "$stored"', self.code,
                         "o entrypoint ainda precria a credencial vazia")
        self.assertNotIn("link_credential", self.code,
                         "link_credential ainda e executado")

    def test_entrypoint_no_longer_symlinks_the_credential_paths(self):
        for path in (".claude/.credentials.json", ".codex/auth.json"):
            self.assertNotIn(path, self.code,
                             f"{path} ainda e manipulado pelo entrypoint")

    def test_entrypoint_never_destroys_the_credential_directories(self):
        for dangerous in ('rm -rf "$ASB_HOME/.claude"',
                          'rm -rf "$ASB_HOME/.codex"'):
            self.assertNotIn(dangerous, self.code,
                             f"o entrypoint executa {dangerous!r}")

    def test_the_causal_record_of_the_defect_stays_in_the_file(self):
        """Guarda do proprio teste: os assertos acima varrem so o codigo, e
        passariam num arquivo que tivesse perdido a explicacao junto."""
        self.assertIn("O_NOFOLLOW", self.text)
        self.assertIn("0 BYTES", self.text)

    def test_config_staging_replacement_is_not_destructive_in_place(self):
        """Com `~/.claude` virando diretorio COMPARTILHADO, o `rm -rf "$dst"`
        seguido de `cp -a` abria uma janela em que outro workspace lia um
        diretorio parcialmente copiado. A troca passa a ser por rename."""
        self.assertIn("asb-staging", self.code)
        self.assertNotIn('rm -rf "$dst"\n    cp -a', self.code)


class TestImageVersionPinning(unittest.TestCase):
    """Fixar versoes da imagem pelo mecanismo suportado por cada instalador.

    Se indisponivel, interromper o gate de build, sem usar latest como se
    estivesse fixado.
    """

    def setUp(self):
        self.text = CONTAINERFILE.read_text(encoding="utf-8")

    def test_claude_and_codex_are_pinned_to_exact_npm_versions(self):
        self.assertIn("@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}", self.text)
        self.assertIn("@openai/codex@${CODEX_VERSION}", self.text)
        self.assertNotIn("npm install -g @anthropic-ai/claude-code @openai/codex",
                         self.text)

    def test_pinned_versions_are_declared_as_build_args(self):
        for arg in ("ARG CLAUDE_CODE_VERSION=", "ARG CODEX_VERSION=",
                    "ARG AGY_VERSION="):
            self.assertIn(arg, self.text)

    def test_agy_is_installed_from_a_versioned_artifact_with_checksum(self):
        """O install.sh do agy nao aceita selecao de versao (so `--dir` e
        `--help`) e sempre instala a "latest available version". O manifesto,
        porem, expoe URL versionada + sha512: e esse o artefato fixado."""
        self.assertNotIn("antigravity.google/cli/install.sh", self.text)
        self.assertIn("ARG AGY_SHA512=", self.text)
        self.assertIn("sha512sum -c", self.text)

    def test_the_agy_artifact_url_carries_the_pinned_version(self):
        version = self._arg("AGY_VERSION")
        url = self._arg("AGY_URL")
        self.assertIn(f"/{version}-", url,
                      f"a URL {url!r} nao carrega a versao {version!r}")

    def test_versions_are_validated_against_the_binaries_at_build_time(self):
        """Label declarado no Containerfile nao prova nada: o build compara o
        que o BINARIO responde e falha se divergir."""
        for probe in ("claude --version", "codex --version", "agy --version"):
            self.assertIn(probe, self.text,
                          f"o build nao interroga '{probe}'")

    def test_every_pinned_version_has_a_label(self):
        for label in ("asb.claude.version=", "asb.codex.version=",
                      "asb.agy.version="):
            self.assertIn(label, self.text)

    def test_no_provider_is_installed_unpinned(self):
        self.assertNotIn("npm install -g @anthropic-ai/claude-code\n", self.text)
        self.assertNotIn("@latest", self.text)

    def _arg(self, name: str) -> str:
        for line in self.text.splitlines():
            if line.startswith(f"ARG {name}="):
                return line.split("=", 1)[1].strip()
        raise AssertionError(f"ARG {name} ausente no Containerfile")


class TestLifecycleLoginReexport(unittest.TestCase):
    def test_lifecycle_login_delegates_to_auth_login(self):
        with mock.patch("asb.auth.login", return_value=0) as delegated:
            self.assertEqual(lifecycle.login(FAKE_ROOT), 0)
        delegated.assert_called_once_with(FAKE_ROOT, "all")

    def test_lifecycle_no_longer_carries_the_dead_login_checks(self):
        """`claude -p ping` e `agy -p ping` mandavam PROMPT ao modelo para
        checar sessao, e o do agy bloqueia 60s quando deslogado."""
        self.assertFalse(hasattr(lifecycle, "LOGIN_CHECKS"))


if __name__ == "__main__":
    unittest.main()
