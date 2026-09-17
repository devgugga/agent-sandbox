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

ISOLAMENTO: `lifecycle.ensure_credential_dirs` resolve o mountpoint REAL do
volume via `podman volume inspect` e cria diretorios nele — foi assim que dois
testes desta suite escreveram no volume de credenciais de PRODUCAO. Isso deixou
de depender de boa vontade: `asb_test_isolation` (importado no topo de todo
modulo de teste) impede qualquer invocacao real de podman que NOMEIE um volume,
e `TestUnitSuiteIsolation` reprova o modulo que esquecer o import.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

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


FAKE_CREDENTIALS_VOLUME = "asb-test-credentials"


@contextmanager
def prepare_workspace_harness(ws: str):
    """Roda `lifecycle.prepare_workspace` DE VERDADE e devolve o `podman run`
    do agente.

    Os mounts de credencial e de sessao nao sao mockados: eles rodam contra um
    mountpoint de volume falso, num diretorio temporario. Assim o teste afirma
    sobre a linha de comando que o podman receberia, e nao sobre a existencia
    de um nome no arquivo-fonte.

    Nenhuma chamada chega ao podman: `podman.out` responde o diretorio
    temporario e `podman.run` apenas registra.
    """
    from asb.profile import Profile
    from asb.workspace import Layout

    captured: dict = {"run": [], "agent_args": []}

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        mountpoint = tmp / "volume-data"
        home = tmp / "home"
        for path in (mountpoint, home, tmp / "mount", tmp / "state",
                     tmp / "origin", tmp / "root"):
            path.mkdir(parents=True)
        key = tmp / "id_ed25519"
        key.write_text("dummy")
        (tmp / "id_ed25519.pub").write_text("ssh-ed25519 AAAA dummy")
        captured["home"] = home
        captured["mountpoint"] = mountpoint

        runtime_dir = tmp / "runtime" / "rev1"
        runtime_dir.mkdir(parents=True)

        def fake_run(*args, **kwargs):
            captured["run"].append(list(args))
            if args and args[0] in ("run", "create") and "--name" in args:
                if args[args.index("--name") + 1] == f"asb-{ws}-agent":
                    captured["agent_args"] = list(args)
            return _ok()

        layout = Layout(ws=ws, project="proj", mount=tmp / "mount",
                        project_root=tmp / "mount" / "proj",
                        state=tmp / "state")
        profile = Profile(services=[], host_ports=[], publish_ports=[],
                          host_api="none", container_mode="standard", allow=[])

        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(lifecycle.podman, "exists", return_value=True))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_runtime", return_value=runtime_dir))
            stack.enter_context(mock.patch.object(lifecycle.supervisor, "install_workspace", return_value=[]))
            stack.enter_context(mock.patch.object(lifecycle.podman, "run", side_effect=fake_run))
            stack.enter_context(mock.patch.object(lifecycle.podman, "out", return_value=str(mountpoint)))
            stack.enter_context(mock.patch.object(lifecycle, "load_profile", return_value=profile))
            stack.enter_context(mock.patch.object(lifecycle, "layout_for", return_value=layout))
            stack.enter_context(mock.patch.object(lifecycle, "prepare_clone"))
            stack.enter_context(mock.patch.object(lifecycle, "render", return_value="acl x"))
            stack.enter_context(mock.patch.object(lifecycle, "build_staging", return_value=0))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_ssh_key", return_value=key))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_keyring_service"))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_credentials_volume", return_value=FAKE_CREDENTIALS_VOLUME))
            stack.enter_context(mock.patch.object(lifecycle, "ensure_toolcache_volume", return_value="asb-test-toolcache"))
            stack.enter_context(mock.patch.object(lifecycle.os.path, "expanduser", return_value=str(home)))
            stack.enter_context(redirect_stderr(io.StringIO()))
            lifecycle.prepare_workspace(tmp / "root", ws, tmp / "origin")
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
        """`PodmanError` na verificacao nao escapa mais do laco (I5): vira
        resultado `provider_error` deste fornecedor. O cliente efemero
        continua sendo removido pelo `finally`, e o keyring compartilhado
        nunca entra na lista de remocao."""
        with login_harness() as captured, \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=auth.podman.PodmanError("boom")):
            self.assertEqual(auth.login(FAKE_ROOT, "codex"), 2)

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
                mock.patch.object(auth.lifecycle, "ensure_credentials_volume",
                                  return_value="asb-credentials"), \
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
                mock.patch.object(auth.lifecycle, "ensure_credentials_volume",
                                  return_value="asb-credentials"), \
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
                mock.patch.object(auth.lifecycle, "ensure_credentials_volume",
                                  return_value="asb-credentials"), \
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

    def test_a_volume_we_cannot_write_becomes_an_actionable_error(self):
        """M10: um volume cujo `_data` nao aceita escrita — o estado que o
        piloto real encontrou, com `_data` do uid 0 — levantava
        `PermissionError` cru e o operador recebia traceback em vez de
        diagnostico."""
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir(mode=0o500)
            try:
                with mock.patch.object(lifecycle.podman, "exists",
                                       return_value=True), \
                        mock.patch.object(lifecycle.podman, "out",
                                          return_value=str(mountpoint)):
                    with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                        lifecycle.credential_mount_args(Path("/home/tester"))
            finally:
                mountpoint.chmod(0o700)

        message = str(ctx.exception)
        self.assertIn(str(mountpoint), message, "o erro nao diz ONDE falhou")
        self.assertIn("podman unshare chown", message,
                      "o erro nao traz remediacao acionavel")

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
        """O ponto de integracao inteiro do diff: os mounts tem de chegar a
        LINHA DE COMANDO do agente.

        A versao anterior deste teste lia `lifecycle.py` e afirmava que a
        string "credential_mount_args" estava la — a funcao e DEFINIDA ali,
        entao ele passava mesmo que `prepare_workspace` nunca a chamasse. Aqui
        `prepare_workspace` roda de verdade e os argumentos sao lidos do
        `podman run` que ela emite.
        """
        with prepare_workspace_harness("ws-mount") as captured:
            agent = captured["agent_args"]

        joined = " ".join(agent)
        for rel in (".claude", ".codex"):
            self.assertIn(
                f"type=volume,src={FAKE_CREDENTIALS_VOLUME},"
                f"dst={captured['home'] / rel},"
                f"volume-subpath={rel.lstrip('.')},relabel=shared",
                joined)
        self.assertIn("--mount", agent)

    def test_the_credential_directories_reach_the_agent_created_by_up(self):
        """Guarda do proprio teste acima: uma harness que nao chegasse a
        emitir o `podman run` do agente deixaria as asercoes vazias."""
        with prepare_workspace_harness("ws-mount-guard") as captured:
            pass
        self.assertTrue(captured["agent_args"])
        self.assertEqual(captured["agent_args"][0], "create")
        self.assertIn("asb-ws-mount-guard-agent", captured["agent_args"])


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
        """A copia acontece ao lado e so entra no lugar pronta. O contrato
        completo — inclusive que o destino nunca e apagado no lugar — esta em
        `TestEntrypointNeverDestroysSharedDirectories`."""
        self.assertIn("asb-staging", self.code)


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


class TestAggregateExitCodeDeniesByDefault(unittest.TestCase):
    """C1: o agregado nega por padrao.

    A versao anterior testava os estados RUINS e devolvia 0 para todo o resto.
    `pending` — estado criado por esta mesma tarefa — nascia valendo
    "exit 0 = todos autenticados" no caminho de `auth status`, e ficava inerte
    so porque a A4 ainda nao alimenta esse caminho.
    """

    @staticmethod
    def _result(state: str, provider: str = "claude") -> AuthResult:
        return AuthResult(provider, state, "2026-09-08T00:00:00Z",
                          "evidencia enlatada", "")

    def test_an_invented_state_can_never_become_zero(self):
        """A regressao propriamente dita: um estado que ninguem previu."""
        for invented in ("quantum", "refreshing", "expired-soon", ""):
            with self.subTest(state=invented):
                code = auth._aggregate_exit_code([self._result(invented)])
                self.assertNotEqual(code, 0)
                self.assertEqual(code, 2)

    def test_an_invented_state_taints_an_otherwise_healthy_set(self):
        code = auth._aggregate_exit_code(
            [self._result("authenticated"), self._result("quantum", "codex")])
        self.assertNotEqual(code, 0)

    def test_pending_is_one_not_zero(self):
        self.assertEqual(auth._aggregate_exit_code([self._result("pending")]), 1)

    def test_pending_reaching_auth_status_is_not_reported_as_success(self):
        """O caminho exato do achado: quando a A4 alimentar `pending` no
        `auth status`, um fornecedor NAO VERIFICADO nao pode sair com 0."""
        pending = self._result("pending", "agy")
        with mock.patch("asb.auth.check_status", return_value=pending), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-x-agent"}), \
                redirect_stderr(io.StringIO()):
            code = auth.status("x", "agy", json_output=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(code, 1)

    def test_only_authenticated_produces_zero(self):
        self.assertEqual(
            auth._aggregate_exit_code(
                [self._result("authenticated"),
                 self._result("authenticated", "codex")]),
            0)

    def test_infrastructure_states_keep_precedence_over_account_states(self):
        for infra in ("unknown", "unreachable", "provider_error"):
            with self.subTest(state=infra):
                self.assertEqual(
                    auth._aggregate_exit_code(
                        [self._result("unauthenticated"),
                         self._result(infra, "codex")]),
                    2)

    def test_unauthenticated_alone_is_one(self):
        self.assertEqual(
            auth._aggregate_exit_code([self._result("unauthenticated")]), 1)

    def test_an_empty_result_list_is_not_success(self):
        """Nao ter perguntado a ninguem nao e prova de nada."""
        self.assertNotEqual(auth._aggregate_exit_code([]), 0)

    def test_login_and_status_share_the_same_aggregate(self):
        """Duas copias da regra foi como `pending` ficou certo num caminho e
        valendo 0 no outro."""
        source = (ROOT / "cli" / "asb" / "auth.py").read_text(encoding="utf-8")
        self.assertNotIn("_login_exit_code", source)


class TestUnitSuiteIsolation(unittest.TestCase):
    """C2: o isolamento da suite e IMPOSTO, nao pedido em docstring.

    O que aconteceu duas vezes: um teste mockou so
    `ensure_credentials_volume` e deixou a chamada seguinte chegar a um
    `podman volume inspect asb-credentials` REAL, criando diretorios dentro do
    volume de producao do operador.
    """

    def test_every_unit_test_module_imports_the_isolation_guard(self):
        missing = [
            path.name
            for path in sorted((ROOT / "tests" / "unit").glob("test_*.py"))
            if "asb_test_isolation" not in path.read_text(encoding="utf-8")]
        self.assertEqual(
            missing, [],
            "modulo de teste sem o guarda de isolamento: um teste ali pode "
            "alcancar um volume real do host")

    def test_the_guard_blocks_a_real_podman_volume_inspect(self):
        with self.assertRaises(asb_test_isolation.RealPodmanVolumeAccess):
            asb_test_isolation.subprocess.run(
                ["/usr/bin/podman", "volume", "inspect", "asb-credentials",
                 "--format", "{{.Mountpoint}}"])

    def test_the_guard_blocks_every_way_of_naming_a_volume(self):
        cases = [
            ["podman", "volume", "create", "asb-credentials"],
            ["podman", "volume", "rm", "-f", "asb-credentials"],
            ["podman", "volume", "exists", "asb-test-unit-credentials"],
            ["podman", "run", "-v", "asb-credentials:/run/asb-credentials:z",
             "img"],
            ["podman", "run", "--mount",
             "type=volume,src=asb-credentials,dst=/home/x/.claude,"
             "volume-subpath=claude", "img"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertTrue(asb_test_isolation.named_volumes(argv),
                                "o guarda nao enxergou o volume nesta linha")

    def test_the_guard_is_not_a_blanket_refusal(self):
        """Guarda do proprio guarda: um invólucro que recusasse tudo faria os
        testes acima passarem sem provar nada, e quebraria o resto da suite."""
        for argv in (["podman", "ps", "--filter", "name=x"],
                     ["podman", "--version"],
                     ["podman", "image", "exists", "agent-sandbox:latest"],
                     ["podman", "run", "-v", "/tmp/host:/run/x:ro", "img"],
                     ["git", "rev-parse", "HEAD"]):
            with self.subTest(argv=argv):
                self.assertEqual(asb_test_isolation.named_volumes(argv), [])
        self.assertEqual(
            asb_test_isolation.subprocess.run(
                ["/usr/bin/true"]).returncode, 0)

    def test_credential_mount_args_without_mocks_cannot_reach_a_real_volume(self):
        """A costura exata que contaminou o volume de producao, agora com o
        guarda no lugar: sem mock nenhum, a chamada MORRE antes do podman."""
        with self.assertRaises(asb_test_isolation.RealPodmanVolumeAccess):
            lifecycle.credential_mount_args(Path("/home/tester"))

    def test_ensure_session_volume_without_mocks_cannot_reach_a_real_volume(self):
        with self.assertRaises(asb_test_isolation.RealPodmanVolumeAccess):
            lifecycle.ensure_session_volume("ws-sem-mock")


class TestLegacyCredentialLayoutWarning(unittest.TestCase):
    """I3: o layout de raiz e detectado e ANUNCIADO. Nada e apagado."""

    @contextmanager
    def _volume(self, *names: str):
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            mountpoint.mkdir()
            for name in names:
                (mountpoint / name).write_text('{"legado": true}')
            err = io.StringIO()
            with mock.patch.object(lifecycle.podman, "exists",
                                   return_value=True), \
                    mock.patch.object(lifecycle.podman, "out",
                                      return_value=str(mountpoint)), \
                    redirect_stderr(err):
                lifecycle.credential_mount_args(Path("/home/tester"))
            yield mountpoint, err.getvalue()

    def test_the_root_layout_is_named_out_loud(self):
        with self._volume("codex-auth.json", "claude.json") as (_, err):
            self.assertIn("codex-auth.json", err)
            self.assertIn("claude.json", err)
            self.assertIn("aviso", err.lower())

    def test_the_warning_states_the_exposure_and_the_relogin(self):
        with self._volume("codex-auth.json") as (_, err):
            self.assertIn("/run/asb-credentials/", err)
            self.assertIn("login", err.lower())

    def test_the_warning_never_deletes_or_moves_anything(self):
        """A politica de migracao nao e desta funcao, e apagar credencial
        nunca e recuperacao valida."""
        with self._volume("codex-auth.json") as (mountpoint, _):
            legacy = mountpoint / "codex-auth.json"
            self.assertTrue(legacy.is_file())
            self.assertEqual(legacy.read_text(), '{"legado": true}')

    def test_a_clean_volume_produces_no_warning(self):
        with self._volume() as (_, err):
            self.assertNotIn("aviso", err.lower())

    def test_the_new_layout_alone_produces_no_warning(self):
        """Um `claude/auth.json` DENTRO do subdiretorio e o layout novo: nao
        pode ser confundido com a copia orfa da raiz."""
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "_data"
            (mountpoint / "codex").mkdir(parents=True)
            (mountpoint / "codex" / "auth.json").write_text("{}")
            err = io.StringIO()
            with mock.patch.object(lifecycle.podman, "exists",
                                   return_value=True), \
                    mock.patch.object(lifecycle.podman, "out",
                                      return_value=str(mountpoint)), \
                    redirect_stderr(err):
                lifecycle.credential_mount_args(Path("/home/tester"))
            self.assertEqual(err.getvalue(), "")


class TestLoginPreservesResultsAcrossFailures(unittest.TestCase):
    """I5: erro de infraestrutura de UM fornecedor nao apaga o resultado ja
    conquistado de outro."""

    def test_a_podman_failure_does_not_discard_a_verified_provider(self):
        verified = AuthResult("claude", "authenticated", "x",
                              "native_status", "")

        def verify(provider: str):
            if provider == "claude":
                return verified
            raise auth.podman.PodmanError("podman ps falhou")

        err = io.StringIO()
        with login_harness(), \
                mock.patch("asb.auth.verify_fresh_client", side_effect=verify), \
                redirect_stderr(err):
            code = auth.login(FAKE_ROOT, "all")

        report = err.getvalue()
        # O sucesso do claude sobreviveu ao erro do codex...
        self.assertIn("claude: authenticated", report)
        # ...e o erro do codex foi PRESERVADO, nao engolido.
        self.assertIn("codex: provider_error", report)
        # ...e o agy continuou sendo tentado depois do erro.
        self.assertIn("agy: ", report)
        self.assertEqual(code, 2)

    def test_the_podman_error_never_carries_provider_output(self):
        """A evidencia continua sendo texto enlatado: o erro do podman nao e
        saida capturada do fornecedor."""
        secret = "sk-ant-oat01-SEGREDO"
        err = io.StringIO()
        with login_harness(), \
                mock.patch("asb.auth.verify_fresh_client",
                           side_effect=auth.podman.PodmanError("falha")), \
                redirect_stderr(err):
            auth.login(FAKE_ROOT, "codex")
        self.assertNotIn(secret, err.getvalue())


class TestSessionStateIsolation(unittest.TestCase):
    """I6: a credencial e compartilhada; a transcricao nao.

    Medido no podman 6.1 antes de escrever o codigo: o mount do workspace
    entra POR CIMA do subdiretorio de `~/.claude`, dois workspaces leem a
    MESMA credencial e nenhum enxerga o `projects/` do outro.
    """

    def test_the_session_directories_are_mounted_from_the_workspace_volume(self):
        args = lifecycle.session_mount_args("asb-demo-session",
                                            Path("/home/tester"))
        joined = " ".join(args)
        for rel, sub in ((".claude/projects", "claude-projects"),
                         (".claude/todos", "claude-todos"),
                         (".codex/sessions", "codex-sessions")):
            self.assertIn(f"dst=/home/tester/{rel}", joined)
            self.assertIn(f"volume-subpath={sub}", joined)
        self.assertIn("src=asb-demo-session", joined)

    def test_the_credential_volume_is_never_the_session_volume(self):
        with prepare_workspace_harness("ws-a") as captured:
            agent = " ".join(captured["agent_args"])
        self.assertIn(f"src={FAKE_CREDENTIALS_VOLUME},"
                      f"dst={captured['home'] / '.claude'},"
                      f"volume-subpath=claude", agent)
        self.assertIn(f"src=asb-ws-a-session,"
                      f"dst={captured['home'] / '.claude/projects'},"
                      f"volume-subpath=claude-projects", agent)

    def test_two_workspaces_never_share_a_session_volume(self):
        with prepare_workspace_harness("ws-a") as first:
            pass
        with prepare_workspace_harness("ws-b") as second:
            pass
        a = " ".join(first["agent_args"])
        b = " ".join(second["agent_args"])
        self.assertIn("src=asb-ws-a-session", a)
        self.assertNotIn("asb-ws-b-session", a)
        self.assertIn("src=asb-ws-b-session", b)
        self.assertNotIn("asb-ws-a-session", b)
        # ...e mesmo assim os dois montam a MESMA credencial: o
        # compartilhamento exigido pela spec continua de pe.
        self.assertIn(f"src={FAKE_CREDENTIALS_VOLUME}", a)
        self.assertIn(f"src={FAKE_CREDENTIALS_VOLUME}", b)

    def test_the_session_source_subpaths_are_created_on_the_host(self):
        """`volume-subpath` NAO cria o caminho de origem (A1): um subpath
        ausente aborta o `podman run`."""
        with prepare_workspace_harness("ws-subpaths") as captured:
            # Dentro do bloco: o mountpoint e um diretorio temporario que
            # some quando a harness fecha.
            mountpoint = captured["mountpoint"]
            for sub in lifecycle.SESSION_STATE_DIRS:
                with self.subTest(sub=sub):
                    self.assertTrue((mountpoint / sub).is_dir())
                    self.assertEqual(
                        (mountpoint / sub).stat().st_mode & 0o077, 0)

    def test_the_session_volume_holds_no_credential_path(self):
        joined = " ".join(lifecycle.SESSION_STATE_DIRS.values())
        self.assertNotIn(".credentials.json", joined)
        self.assertNotIn("auth.json", joined)

    def test_purge_removes_the_session_volume_and_nothing_shared(self):
        removed = []

        def fake_run(*args, **kwargs):
            removed.append(list(args))
            return _ok()

        with mock.patch.object(lifecycle, "_origin_of",
                               return_value=Path("/origin")), \
                mock.patch.object(lifecycle, "layout_for"), \
                mock.patch.object(lifecycle, "down", return_value=0), \
                mock.patch.object(lifecycle, "remove_workspace"), \
                mock.patch.object(lifecycle.podman, "exists",
                                  return_value=True), \
                mock.patch.object(lifecycle.podman, "run",
                                  side_effect=fake_run), \
                redirect_stderr(io.StringIO()):
            lifecycle.purge("demo", confirmed=True)

        self.assertEqual(removed, [["volume", "rm", "-f", "asb-demo-session"]])


class TestEntrypointNeverDestroysSharedDirectories(unittest.TestCase):
    """I6, segunda metade: com `~/.claude` compartilhado, todo `up` apagava e
    recriava `plugins`/`skills` DENTRO do volume compartilhado, a vista de
    todo workspace em execucao."""

    def setUp(self):
        self.code = "\n".join(
            line for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#"))

    def test_the_destination_is_never_removed_in_place(self):
        self.assertNotIn('rm -rf "$dst"', self.code,
                         "o entrypoint ainda apaga o destino no lugar")

    def test_the_old_directory_leaves_by_rename_before_being_removed(self):
        self.assertIn('mv "$dst" "$previous"', self.code)
        self.assertIn('mv "$staged" "$dst"', self.code)
        self.assertLess(self.code.index('mv "$dst" "$previous"'),
                        self.code.index('rm -rf "$previous"'))

    def test_the_residual_window_is_declared_in_the_file(self):
        """O limite fica escrito: `mv` sobre diretorio nao e
        `renameat2(RENAME_EXCHANGE)`, entao a troca nao e atomica."""
        text = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("RENAME_EXCHANGE", text)


if __name__ == "__main__":
    unittest.main()
