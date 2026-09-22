"""tests/unit/test_install_server.py — Tarefa 7 (`install-server`, `ui`,
`doctor`), espec 13.1 e Emenda G.

TUDO aqui e falso: nenhum teste chama systemd de verdade, roda `uv`/`pnpm`
de verdade ou abre um navegador. `install.install_server` recebe `run`
(substitui `subprocess.run`) e `check_health` injetaveis; `ui.ui` recebe
`check_health`, `which` e `popen` injetaveis; as checagens do doctor usam
`ASB_SYSTEMD_UNIT_DIR`/`keyring.CONFIG` isolados e `subprocess.run`/
`install.default_health_check` mockados.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import install, keyring  # noqa: E402
from asb.diagnostics import checks as diag_checks  # noqa: E402
from asb.diagnostics.checks import CheckResult  # noqa: E402
from asb.interfaces import ui as ui_mod  # noqa: E402


def _ok(stdout: str = "ok\n") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def _fail(stdout: str = "", stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, stdout=stdout, stderr=stderr)


class FakeRun:
    """Substitui `subprocess.run` para `install_server`: nunca invoca uv,
    node, pnpm ou systemctl de verdade. `missing_tools` simula um
    executavel ausente do PATH (`FileNotFoundError`, como o real
    `subprocess.run` levanta); `failures` simula um passo que sai != 0,
    indexado pelo argv exato."""

    def __init__(self, missing_tools: frozenset[str] = frozenset(),
                 failures: dict | None = None) -> None:
        self.missing_tools = missing_tools
        self.failures = failures or {}
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, argv, cwd=None, capture_output=True, text=True):
        self.calls.append((list(argv), cwd))
        if argv[0] in self.missing_tools:
            raise FileNotFoundError(argv[0])
        result = self.failures.get(tuple(argv))
        return result if result is not None else _ok()


class TestRenderServerUnit(unittest.TestCase):
    """Espec 8.1 + Emenda D: ExecStart, Restart, RestartSec, WantedBy —
    escapados por `supervisor.escape_systemd_arg`, nunca por uma segunda
    rotina de escaping mais fraca."""

    def test_fixed_fields(self):
        content = install.render_server_unit(Path("/opt/asb/.venv/bin/asb-server"))
        self.assertIn("ExecStart=/opt/asb/.venv/bin/asb-server serve\n", content)
        self.assertIn("Restart=on-failure\n", content)
        self.assertIn("RestartSec=2\n", content)
        self.assertIn("WantedBy=default.target\n", content)
        self.assertIn("[Install]\n", content)

    def test_escapes_a_checkout_path_with_a_space(self):
        venv_bin = Path("/tmp/my project/.venv/bin/asb-server")
        content = install.render_server_unit(venv_bin)
        self.assertIn(
            'ExecStart="/tmp/my project/.venv/bin/asb-server" serve\n', content)
        # A unidade continua bem formada: uma so linha de ExecStart, sem
        # aspas desbalanceadas.
        exec_lines = [ln for ln in content.splitlines() if ln.startswith("ExecStart=")]
        self.assertEqual(len(exec_lines), 1)
        self.assertEqual(exec_lines[0].count('"'), 2)

    def test_escapes_a_checkout_path_with_a_quote(self):
        venv_bin = Path('/tmp/weird"quote/.venv/bin/asb-server')
        content = install.render_server_unit(venv_bin)
        self.assertIn('ExecStart="/tmp/weird\\"quote/.venv/bin/asb-server" serve\n',
                       content)


class InstallServerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        self.root.mkdir()
        self.units_dir = Path(self.tmp.name) / "units"
        self.env_patch = mock.patch.dict(
            "os.environ", {"ASB_SYSTEMD_UNIT_DIR": str(self.units_dir)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)


class TestInstallServerHappyPath(InstallServerTestBase):
    def test_writes_unit_and_reports_success(self):
        fake = FakeRun()
        code = install.install_server(
            self.root, run=fake, check_health=lambda url: True)

        self.assertEqual(code, 0)
        unit_file = self.units_dir / install.SERVER_UNIT_NAME
        self.assertTrue(unit_file.is_file())
        expected_bin = self.root / ".venv" / "bin" / "asb-server"
        self.assertIn(f"ExecStart={expected_bin} serve\n", unit_file.read_text())

        argvs = [argv for argv, _cwd in fake.calls]
        self.assertIn(["uv", "--version"], argvs)
        self.assertIn(["node", "--version"], argvs)
        self.assertIn(["pnpm", "--version"], argvs)
        self.assertIn(["uv", "sync", "--frozen"], argvs)
        self.assertIn(["pnpm", "install", "--frozen-lockfile"], argvs)
        self.assertIn(["pnpm", "build"], argvs)
        self.assertIn(["systemctl", "--user", "daemon-reload"], argvs)
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", install.SERVER_UNIT_NAME], argvs)

        # cwd correto para cada passo do workspace.
        by_argv = {tuple(argv): cwd for argv, cwd in fake.calls}
        self.assertEqual(by_argv[("uv", "sync", "--frozen")], self.root)
        self.assertEqual(by_argv[("pnpm", "install", "--frozen-lockfile")],
                         self.root / "web")
        self.assertEqual(by_argv[("pnpm", "build")], self.root / "web")

    def test_idempotent_rerun_leaves_the_same_unit(self):
        fake = FakeRun()
        install.install_server(self.root, run=fake, check_health=lambda url: True)
        unit_file = self.units_dir / install.SERVER_UNIT_NAME
        first_content = unit_file.read_text()
        first_listing = sorted(p.name for p in self.units_dir.iterdir())

        fake2 = FakeRun()
        code = install.install_server(self.root, run=fake2, check_health=lambda url: True)

        self.assertEqual(code, 0)
        second_content = unit_file.read_text()
        second_listing = sorted(p.name for p in self.units_dir.iterdir())
        self.assertEqual(first_content, second_content)
        # Nenhum arquivo temporario (.tmp) ou duplicado sobrou: so a unidade.
        self.assertEqual(first_listing, [install.SERVER_UNIT_NAME])
        self.assertEqual(second_listing, [install.SERVER_UNIT_NAME])

    def test_health_timeout_still_installs_and_warns(self):
        """A sonda de saude nunca bloqueia a instalacao: enable --now ja
        rodou; a unidade so avisa e nomeia journalctl."""
        fake = FakeRun()
        code = install.install_server(
            self.root, run=fake, check_health=lambda url: False, health_timeout=0)
        self.assertEqual(code, 0)
        self.assertTrue((self.units_dir / install.SERVER_UNIT_NAME).is_file())


class TestInstallServerPrerequisiteFailures(InstallServerTestBase):
    """Cada passo interrompe o comando e nomeia a correcao exata (Emenda D)."""

    def test_uv_missing(self):
        fake = FakeRun(missing_tools=frozenset({"uv"}))
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("uv", str(ctx.exception))
        self.assertIn("instale o uv", str(ctx.exception))

    def test_node_missing(self):
        fake = FakeRun(missing_tools=frozenset({"node"}))
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("instale o Node.js", str(ctx.exception))

    def test_pnpm_missing(self):
        fake = FakeRun(missing_tools=frozenset({"pnpm"}))
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("instale o pnpm", str(ctx.exception))

    def test_uv_sync_fails(self):
        fake = FakeRun(failures={("uv", "sync", "--frozen"): _fail(stderr="lockfile stale")})
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        msg = str(ctx.exception)
        self.assertIn("uv sync --frozen", msg)
        self.assertIn("lockfile stale", msg)

    def test_pnpm_install_fails(self):
        fake = FakeRun(failures={
            ("pnpm", "install", "--frozen-lockfile"): _fail(stderr="lockfile mismatch")})
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("pnpm install --frozen-lockfile", str(ctx.exception))

    def test_pnpm_build_fails(self):
        fake = FakeRun(failures={("pnpm", "build"): _fail(stderr="tsc error")})
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("pnpm build", str(ctx.exception))

    def test_daemon_reload_fails(self):
        fake = FakeRun(failures={
            ("systemctl", "--user", "daemon-reload"): _fail(stderr="unit corrupt")})
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn("systemctl --user daemon-reload", str(ctx.exception))

    def test_enable_now_fails(self):
        fake = FakeRun(failures={
            ("systemctl", "--user", "enable", "--now", install.SERVER_UNIT_NAME):
                _fail(stderr="Failed to enable")})
        with self.assertRaises(RuntimeError) as ctx:
            install.install_server(self.root, run=fake)
        self.assertIn(f"systemctl --user enable --now {install.SERVER_UNIT_NAME}",
                      str(ctx.exception))


class TestUiBrowserSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config"
        self.config.mkdir()
        self.token_path = self.config / install.SERVER_TOKEN_NAME
        self.token_path.write_text("abc123")
        self.keyring_patch = mock.patch.object(keyring, "CONFIG", self.config)
        self.keyring_patch.start()
        self.addCleanup(self.keyring_patch.stop)

    def test_prints_url_instead_of_opening_when_print_url(self):
        out = []
        code = ui_mod.ui(
            print_url=True, check_health=lambda url: True,
            which=lambda name: (_ for _ in ()).throw(AssertionError("nao deveria chamar which")),
            popen=lambda argv: (_ for _ in ()).throw(AssertionError("nao deveria abrir nada")),
            out=type("W", (), {"write": lambda self, s: out.append(s)})(),
        )
        self.assertEqual(code, 0)
        printed = "".join(out)
        self.assertIn("http://127.0.0.1:7420/#token=abc123", printed)

    def test_print_url_never_probes_health_even_when_the_daemon_is_down(self):
        """A Tarefa 7 pede que `--print-url` funcione sem daemon de pe: nem
        uma chamada de rede pode acontecer nesse caminho."""
        out = []

        def _must_not_be_called(_url):
            raise AssertionError("--print-url nao deveria checar saude")

        code = ui_mod.ui(
            print_url=True, check_health=_must_not_be_called,
            out=type("W", (), {"write": lambda self, s: out.append(s)})(),
        )
        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:7420/#token=abc123", "".join(out))

    def test_picks_the_first_browser_of_the_three_in_priority_order(self):
        # chromium E brave existem; a prioridade manda escolher chromium
        # (primeiro da tupla), nunca brave.
        def which(name):
            return f"/usr/bin/{name}" if name in ("chromium", "brave") else None

        calls = []
        code = ui_mod.ui(
            check_health=lambda url: True, which=which,
            popen=lambda argv: calls.append(argv),
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "/usr/bin/chromium")
        self.assertEqual(calls[0][1], "--app=http://127.0.0.1:7420/#token=abc123")

    def test_falls_back_to_xdg_open_when_no_browser_found(self):
        def which(name):
            return "/usr/bin/xdg-open" if name == "xdg-open" else None

        calls = []
        code = ui_mod.ui(
            check_health=lambda url: True, which=which,
            popen=lambda argv: calls.append(argv),
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["/usr/bin/xdg-open",
                                  "http://127.0.0.1:7420/#token=abc123"]])

    def test_prints_the_url_when_nothing_can_open_it(self):
        out = []
        code = ui_mod.ui(
            check_health=lambda url: True, which=lambda name: None,
            popen=lambda argv: (_ for _ in ()).throw(AssertionError("nao deveria chamar popen")),
            out=type("W", (), {"write": lambda self, s: out.append(s)})(),
        )
        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:7420/#token=abc123", "".join(out))

    def test_reports_inactive_unit_and_opens_nothing(self):
        err = []
        code = ui_mod.ui(
            check_health=lambda url: False,
            which=lambda name: (_ for _ in ()).throw(AssertionError("nao deveria chamar which")),
            popen=lambda argv: (_ for _ in ()).throw(AssertionError("nao deveria abrir nada")),
            err=type("W", (), {"write": lambda self, s: err.append(s)})(),
        )
        self.assertEqual(code, 1)
        message = "".join(err)
        self.assertIn(f"systemctl --user start {install.SERVER_UNIT_NAME}", message)

    def test_never_puts_the_token_anywhere_but_the_fragment(self):
        """A URL impressa carrega o token SO depois de `#`; nunca antes,
        nunca numa query string."""
        out = []
        ui_mod.ui(
            print_url=True, check_health=lambda url: True,
            out=type("W", (), {"write": lambda self, s: out.append(s)})(),
        )
        printed = "".join(out).strip()
        before_hash, _, after_hash = printed.partition("#")
        self.assertNotIn("abc123", before_hash)
        self.assertIn("token=abc123", after_hash)
        self.assertNotIn("?", printed)


class DoctorWebChecksTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        self.root.mkdir()
        self.units_dir = Path(self.tmp.name) / "units"
        self.units_dir.mkdir()
        self.config = Path(self.tmp.name) / "config"
        self.config.mkdir()
        self.env_patch = mock.patch.dict(
            "os.environ", {"ASB_SYSTEMD_UNIT_DIR": str(self.units_dir)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.keyring_patch = mock.patch.object(keyring, "CONFIG", self.config)
        self.keyring_patch.start()
        self.addCleanup(self.keyring_patch.stop)

    def _write_unit(self, exec_bin: Path) -> Path:
        unit_path = self.units_dir / install.SERVER_UNIT_NAME
        unit_path.write_text(install.render_server_unit(exec_bin))
        return unit_path

    def _write_binary(self) -> Path:
        binary = self.root / ".venv" / "bin" / "asb-server"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        return binary

    def _write_dist(self) -> None:
        dist = self.root / "web" / "dist" / "index.html"
        dist.parent.mkdir(parents=True)
        dist.write_text("<html></html>")

    def _write_token(self, mode: int = 0o600) -> Path:
        token = self.config / install.SERVER_TOKEN_NAME
        token.write_text("secret")
        token.chmod(mode)
        return token


class TestDoctorWebChecksNeverInstalled(DoctorWebChecksTestBase):
    def test_single_informational_line_when_unit_absent(self):
        results = diag_checks.collect_web_checks(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "web_interface")
        self.assertTrue(results[0].healthy)
        self.assertEqual(results[0].remediation, "asb-agent install-server")


class TestDoctorWebChecksInstalled(DoctorWebChecksTestBase):
    """As seis checagens da Emenda F, uma por vez, com sistema de arquivos e
    `systemctl`/`GET /api/health` falsos."""

    def test_web_binary(self):
        self.assertFalse(diag_checks.check_web_binary(self.root).healthy)
        self._write_binary()
        cr = diag_checks.check_web_binary(self.root)
        self.assertTrue(cr.healthy)
        self.assertEqual(cr.remediation, "")

    def test_web_dist(self):
        self.assertFalse(diag_checks.check_web_dist(self.root).healthy)
        self._write_dist()
        self.assertTrue(diag_checks.check_web_dist(self.root).healthy)

    def test_web_unit_healthy_when_execstart_exists(self):
        binary = self._write_binary()
        unit_path = self._write_unit(binary)
        cr = diag_checks.check_web_unit(unit_path)
        self.assertTrue(cr.healthy)

    def test_web_unit_detects_stale_execstart_after_a_moved_checkout(self):
        moved_away = self.root / ".venv" / "bin" / "asb-server"
        unit_path = self._write_unit(moved_away)  # nunca escrito no disco
        cr = diag_checks.check_web_unit(unit_path)
        self.assertFalse(cr.healthy)
        self.assertIn("checkout movido", cr.label)
        self.assertEqual(cr.remediation, "asb-agent install-server")

    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_web_unit_active(self, run):
        run.side_effect = [
            mock.Mock(stdout="enabled\n"), mock.Mock(stdout="active\n")]
        cr = diag_checks.check_web_unit_active()
        self.assertTrue(cr.healthy)

    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_web_unit_inactive(self, run):
        run.side_effect = [
            mock.Mock(stdout="enabled\n"), mock.Mock(stdout="inactive\n")]
        cr = diag_checks.check_web_unit_active()
        self.assertFalse(cr.healthy)
        self.assertIn(f"systemctl --user enable --now {install.SERVER_UNIT_NAME}",
                      cr.remediation)

    def test_web_token_mode_ok(self):
        self._write_token(0o600)
        cr = diag_checks.check_web_token_mode()
        self.assertTrue(cr.healthy)

    def test_web_token_mode_too_open(self):
        self._write_token(0o644)
        cr = diag_checks.check_web_token_mode()
        self.assertFalse(cr.healthy)
        self.assertIn("chmod 600", cr.remediation)

    def test_web_token_missing(self):
        cr = diag_checks.check_web_token_mode()
        self.assertFalse(cr.healthy)

    @mock.patch("asb.install.default_health_check", return_value=True)
    def test_web_health_ok(self, _check):
        self.assertTrue(diag_checks.check_web_health().healthy)

    @mock.patch("asb.install.default_health_check", return_value=False)
    def test_web_health_down(self, _check):
        cr = diag_checks.check_web_health()
        self.assertFalse(cr.healthy)
        self.assertIn("journalctl", cr.remediation)

    @mock.patch("asb.install.default_health_check", return_value=True)
    @mock.patch("asb.diagnostics.checks.subprocess.run")
    def test_collect_web_checks_all_six_green_after_install(self, run, _health):
        run.side_effect = [
            mock.Mock(stdout="enabled\n"), mock.Mock(stdout="active\n")]
        binary = self._write_binary()
        self._write_dist()
        self._write_unit(binary)
        self._write_token(0o600)

        results = diag_checks.collect_web_checks(self.root)

        self.assertEqual(
            [r.name for r in results],
            ["web_binary", "web_dist", "web_unit", "web_unit_active",
             "web_token_mode", "web_health"])
        self.assertTrue(all(r.healthy for r in results), results)


if __name__ == "__main__":
    unittest.main()
