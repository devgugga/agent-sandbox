"""tests/integration/test_adoption.py — adocao e rollback de workspace e keyring (I6), ponta a ponta.

Isolamento (C3), provado e nao presumido:
- units em $XDG_RUNTIME_DIR/systemd/user (ASB_SYSTEMD_UNIT_DIR): a unica raiz
  fora do HOME que o manager do operador le. A producao recusa raiz fora do
  UnitPath do manager e unit resolvida para outro FragmentPath;
- estado, runtime versionado e mounts sob <state_root>/home: o HOME e
  desviado so dentro do processo (os.path.expanduser); o storage do Podman,
  que o proprio podman resolve, nao muda;
- config e drop-in do podman-restart sob ASB_CONFIG_ROOT, que o manager nao le;
- keyring isolado pelo nome do container (ASB_KEYRING_CONTAINER): a unit
  derivada e <prefixo>-keyring.service, nunca asb-keyring.service;
- guarda de comandos: todo systemctl/podman emitido pela producao so nomeia
  units e containers registrados na fixture; mutacao global do manager
  (ex.: reset-failed sem unit) e recusada;
- o HOME real e comparado antes/depois de cada cenario, e cada cenario
  termina com assert_no_orphans(all_registered=True).

Unica escrita no HOME aceita (ruling do operador, 2026-09-11): o symlink
default.target.wants/asb-test-*.target criado pelo `asb-agent resume` real
(lifecycle.py congelado habilita o target sem --runtime). O rollback remove as
duas habilitacoes e o teardown prova a ausencia (cenario 29).

Cenarios:
 1. dry-run produz inventario e zero mutacoes; dry-run disputa o lock;
 2. apply + rollback preservam ID, porta, sentinela, dados e worktree;
 3. politicas e estados running/stopped restaurados exatamente;
 4. target/unidades/manifesto preexistentes (0o640, habilitado, ativo) restaurados;
 5. ID divergente no diario recusa o rollback sem mutacao;
 6. falha entre policy update e start restaura o estado anterior;
 7. crash real por fase, retomada idempotente e recusa de fase incoerente;
 8. diario ausente, corrompido ou incompativel falha fechado;
 9. lock no diretorio de estado recusa apply, dry-run e rollback;
10. keyring dry-run/apply/rollback separados; rollback do workspace nao o desliga;
11. drop-in alheio preservado; do projeto removido e restaurado; troca detectada;
12. diagnostico separa mounts legados, forwarder e supervisao;
13. produtores do netns rootless so inventariados;
14. adocao/rollback nunca chamam podman rm/create/run;
15. teardown deixa zero recursos da fixture;
16. papeis invalidos, com traversal ou duplicados recusam sem mutacao;
17. falha de prontidao dispara rollback automatico;
18. estados mistos respeitam o contrato proxy->agent;
19. diario estruturalmente invalido falha fechado;
20. container recriado por fora entre duas mutacoes interrompe a seguinte;
21. paridade transacional do keyring (parado, lock, unit preexistente, crash);
22. falha injetada no rollback preserva o diario para retomada;
23. CLI: texto por padrao, JSON com --json;
24. runtime instalado sem mocks nem failpoints;
25. validacoes de status, politica, diagnostico e runtime;
26. keyring sem Secret Service dispara rollback automatico;
27. double fault de workspace grava rollback_error e retoma;
28. double fault de keyring grava rollback_error e retoma;
29. workspace parado adotado e religado pelo `asb-agent resume` real;
30. roles nao inventariados ficam intocados no rollback.
"""
from __future__ import annotations

import contextlib
import fcntl
import getpass
import hashlib
import json
import os
import runpy
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
sys.path.insert(0, str(ROOT))

from asb import install, lifecycle, podman as podman_mod, readiness, supervisor as sup  # noqa: E402
from asb.workspace import layout_for  # noqa: E402
from tests.integration.sandbox_fixture import IsolationError, SandboxFixture  # noqa: E402

REAL_HOME = Path(os.path.expanduser("~"))
PODMAN = str(Path(shutil.which("podman") or "/usr/bin/podman").resolve())
IMAGE = "agent-sandbox:latest"
ALPINE = "docker.io/library/alpine:latest"
JOURNALS = ("journal.json", "keyring-journal.json")

# Proxy sintetico do piloto T1: responde CONNECT com o status de /pilot/status.
PROXY = '''import socketserver
from pathlib import Path
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        request = self.request.recv(4096)
        with Path('/pilot/requests').open('ab') as log:
            log.write(request.split(b'\\r\\n')[0] + b'\\n')
        status = Path('/pilot/status').read_text().strip()
        self.request.sendall(('HTTP/1.1 ' + status + ' Synthetic\\r\\nContent-Length: 0\\r\\n\\r\\n').encode())
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
Server(('0.0.0.0', 3128), Handler).serve_forever()
'''

SLEEPER = "trap 'exit 0' TERM INT; while :; do sleep 0.5 & wait $!; done"


_REAL_RUN = subprocess.run


def run(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Comando do PROPRIO teste (montagem/verificacao): nunca passa pela guarda."""
    return _REAL_RUN(list(args), capture_output=True, text=True, **kwargs)


# --- Guarda de comandos ------------------------------------------------------

_SYSTEMCTL_VERBS = {"is-enabled", "is-active", "show", "daemon-reload", "enable", "disable",
                    "start", "stop", "reset-failed"}
_PODMAN_READ = {"inspect", "ps", "port", "logs", "version", "info"}
_PODMAN_TARGETED = {"update", "start", "stop", "restart", "kill"}


def guard_command(argv: list[str], units, containers, real_run) -> None:
    """Recusa systemctl/podman que nomeie recurso fora da fixture (IsolationError)."""
    binary = Path(argv[0]).name
    if binary == "systemctl":
        if argv[1:2] != ["--user"] or len(argv) < 3 or argv[2] not in _SYSTEMCTL_VERBS:
            raise IsolationError(f"systemctl fora do contrato de adocao: {argv}")
        operands = [a for a in argv[3:] if not a.startswith("-")]
        if not operands:
            if argv[2] == "daemon-reload" or argv[3:] == ["--property=UnitPath", "--value"]:
                return
            raise IsolationError(f"systemctl {argv[2]} sem unit: mutacao/consulta global recusada: {argv}")
        for unit in operands:
            if unit not in units:
                raise IsolationError(f"systemctl {argv[2]} {unit}: unit fora da fixture")
        return
    if binary != "podman":
        return
    args = argv[1:]
    op, rest = (args[0], args[1:]) if args else ("", [])

    def owned(ref: str) -> None:
        if ref in containers:
            return
        res = real_run([PODMAN, "inspect", "--format", "{{.Name}}", ref], capture_output=True, text=True)
        if res.returncode != 0 or res.stdout.strip().lstrip("/") not in containers:
            raise IsolationError(f"podman {op} {ref}: container fora da fixture")

    if op in ("container", "volume", "network", "image"):
        if rest[:1] and rest[0] in ("exists", "inspect", "ls"):
            return
        raise IsolationError(f"podman {op} fora do contrato de adocao: {argv}")
    if op in _PODMAN_READ:
        return
    if op == "exec":
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-u", "--user", "-e", "--env", "-w", "--workdir") else 1
        if i >= len(rest):
            raise IsolationError(f"podman exec sem container: {argv}")
        owned(rest[i])
        return
    if op in _PODMAN_TARGETED:
        targets = [a for a in rest if not a.startswith("-") and not a.isdigit()]
        if not targets:
            raise IsolationError(f"podman {op} sem alvo: {argv}")
        for t in targets:
            owned(t)
        return
    if op in ("run", "create"):
        name = rest[rest.index("--name") + 1] if "--name" in rest else None
        if name not in containers:
            raise IsolationError(f"podman {op} de container fora da fixture: {argv}")
        return
    raise IsolationError(f"podman {op} fora do contrato de adocao: {argv}")


def _expanduser_to(home: Path, real):
    def expand(path):
        text = os.fspath(path)
        if text == "~" or text.startswith("~/"):
            return str(home) + text[1:]
        return real(path)
    return expand


def isolation_env(sb: SandboxFixture) -> dict[str, str]:
    return {
        "ASB_CONFIG_ROOT": str(sb.config_dir),
        "ASB_SYSTEMD_UNIT_DIR": str(sb._unit_dir),
        "ASB_KEYRING_CONTAINER": sb.keyring_container,
        "ASB_KEYRING_RUNTIME_VOLUME": sb.keyring_runtime_volume,
        "ASB_KEYRING_DATA_VOLUME": sb.keyring_data_volume,
        "ASB_KEYRING_PASS_FILE": str(sb.passphrase_file),
        "ASB_CREDENTIALS_VOLUME": sb.credentials_volume,
        "ASB_TOOLCACHE_VOLUME": sb.toolcache_volume,
    }


def home_of(sb: SandboxFixture) -> Path:
    return sb.state_root / "home"


@contextlib.contextmanager
def isolated(home: Path, env: dict[str, str], units, containers, trace: list | None = None):
    """Ambiente + HOME desviado + guarda de comandos para chamadas de producao."""
    real_run = subprocess.run
    real_expand = os.path.expanduser

    def guarded(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)):
            parts = [str(a) for a in argv]
            guard_command(parts, units, containers, real_run)
            if trace is not None:
                trace.append(parts)
        return real_run(argv, *args, **kwargs)

    with mock.patch.dict(os.environ, env), \
            mock.patch("subprocess.run", side_effect=guarded), \
            mock.patch.object(os.path, "expanduser", side_effect=_expanduser_to(home, real_expand)):
        os.environ.pop("ASB_STATE_ROOT", None)
        if Path.home() != home:
            raise IsolationError(f"seam de HOME nao aplicado: Path.home()={Path.home()}")
        yield


# --- Runner do CLI em processo-filho ------------------------------------------

def i6_cli(settings: Path, args: list[str]) -> int:
    """Roda o asb-agent real sob o mesmo isolamento, num processo novo."""
    cfg = json.loads(settings.read_text())
    for name, value in cfg["env"].items():
        if os.environ.get(name) != value:
            raise IsolationError(f"ambiente do CLI divergente em {name}")
    if "ASB_STATE_ROOT" in os.environ:
        raise IsolationError("ASB_STATE_ROOT nao pode vazar para o CLI isolado")
    with contextlib.ExitStack() as stack:
        stack.enter_context(isolated(Path(cfg["home"]), cfg["env"], set(cfg["units"]), set(cfg["containers"])))
        if cfg.get("crash_at"):
            real_write = sup._atomic_write_text

            def crash_write(path, content, *a, **kw):
                real_write(path, content, *a, **kw)
                if Path(path).name in JOURNALS and json.loads(content).get("phase") == cfg["crash_at"]:
                    os._exit(42)

            stack.enter_context(mock.patch.object(sup, "_atomic_write_text", side_effect=crash_write))
        if cfg.get("host_target"):
            real_host = readiness.probe_host
            stack.enter_context(mock.patch.object(
                readiness, "probe_host", side_effect=lambda **kw: real_host(cfg["host_target"], **kw)))
        netns = stack.enter_context(mock.patch.object(lifecycle.podman, "ensure_rootless_netns"))
        if args == ["setup-keyring"]:
            lifecycle.ensure_keyring_service()
            netns.assert_not_called()
            return 0
        sys.argv = [str(ROOT / "cli" / "asb-agent"), *args]
        rc = runpy.run_path(str(ROOT / "cli" / "asb-agent"))["main"]()
        if args[:1] == ["resume"]:
            netns.assert_called()
        else:
            netns.assert_not_called()
        return rc


class TestAdoption(unittest.TestCase):
    """Adocao e rollback de workspace e keyring sob isolamento verificado."""

    # --- infraestrutura por cenario -----------------------------------------

    def setUp(self) -> None:
        self._home_before = self._home_listing()
        self.addCleanup(self._assert_home_untouched)

    @staticmethod
    def _home_listing() -> set[str]:
        roots = (REAL_HOME / ".config" / "systemd" / "user", REAL_HOME / ".local" / "state" / "agent-sandbox",
                 REAL_HOME / ".local" / "lib" / "agent-sandbox" / "runtime", REAL_HOME / "asb-agent")
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                seen.add(str(child))
                if child.is_dir() and not child.is_symlink():
                    seen.update(str(g) for g in child.iterdir())
        return seen

    def _assert_home_untouched(self) -> None:
        mounts = str(REAL_HOME / "asb-agent") + "/"
        created = sorted(p for p in self._home_listing() - self._home_before
                         if "test-adopt" in p or "/runtime/" in p or p.startswith(mounts))
        self.assertEqual(created, [], "o cenario deixou entradas novas no HOME do operador")

    @contextlib.contextmanager
    def sandbox(self, label: str):
        sb = SandboxFixture(label, auto_setup=False)
        with sb:
            home_of(sb).mkdir()
            yield sb
        sb.assert_no_orphans(all_registered=True)

    def iso(self, sb: SandboxFixture, trace: list | None = None):
        return isolated(home_of(sb), isolation_env(sb), sb._registered_units, sb._registered_containers, trace)

    def cli(self, sb: SandboxFixture, *args: str, crash_at: str | None = None,
            host_target: str | None = None) -> subprocess.CompletedProcess[str]:
        env = isolation_env(sb)
        settings = sb.state_root / f"i6-cli-{os.urandom(4).hex()}.json"
        settings.write_text(json.dumps({
            "env": env, "home": str(home_of(sb)), "units": sorted(sb._registered_units),
            "containers": sorted(sb._registered_containers), "crash_at": crash_at, "host_target": host_target,
        }))
        child_env = {k: v for k, v in os.environ.items() if k != "ASB_STATE_ROOT"}
        child_env.update(env)
        return run(sys.executable, "-B", str(Path(__file__).resolve()), "--i6-cli", str(settings), *args,
                   env=child_env)

    def assertCli(self, res: subprocess.CompletedProcess[str], rc: int = 0) -> None:
        self.assertEqual(res.returncode, rc, f"rc={res.returncode}\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")

    @staticmethod
    def state_dir(sb: SandboxFixture, component: str | None = None) -> Path:
        return home_of(sb) / ".local" / "state" / "agent-sandbox" / (component or sb.workspace)

    def journal(self, sb: SandboxFixture, component: str | None = None) -> dict:
        name = "keyring-journal.json" if component == "keyring" else "journal.json"
        return json.loads((self.state_dir(sb, component) / name).read_text())

    @staticmethod
    def policy(name: str) -> str:
        return run(PODMAN, "inspect", name, "--format", "{{.HostConfig.RestartPolicy.Name}}", check=True).stdout.strip()

    @staticmethod
    def running(name: str) -> bool:
        return run(PODMAN, "inspect", name, "--format", "{{.State.Running}}", check=True).stdout.strip() == "true"

    @staticmethod
    def cid(name: str) -> str:
        return run(PODMAN, "inspect", name, "--format", "{{.Id}}", check=True).stdout.strip()

    @staticmethod
    def unit_state(unit: str) -> tuple[str, str]:
        return (run("systemctl", "--user", "is-enabled", unit).stdout.strip(),
                run("systemctl", "--user", "is-active", unit).stdout.strip())

    @staticmethod
    def fragment(unit: str) -> str:
        return run("systemctl", "--user", "show", "--property=FragmentPath", "--value", unit).stdout.strip()

    def assert_units_gone(self, sb: SandboxFixture, *units: str) -> None:
        for unit in units:
            self.assertFalse((sb._unit_dir / unit).exists(), unit)
            self.assertEqual(self.unit_state(unit), ("not-found", "inactive"), unit)

    # --- montagem de recursos -------------------------------------------------

    def _init_repo(self, worktree: Path) -> None:
        for args in (("config", "user.name", "Test User"), ("config", "user.email", "test@example.com")):
            run("git", "-C", str(worktree), *args, check=True)
        (worktree / "README.md").write_text("# Test Workspace Adoption\n")
        run("git", "-C", str(worktree), "add", "README.md", check=True)
        run("git", "-C", str(worktree), "commit", "-m", "initial commit", check=True)

    def workspace(self, sb: SandboxFixture, *, running: bool = True, proxy_running: bool | None = None,
                  policy: str = "unless-stopped", ready: bool = False) -> tuple[str, str]:
        """Workspace legado sintetico: agent (alpine) e proxy (responder CONNECT).

        `ready=True` entrega o que a sonda de prontidao exige de verdade, para
        os cenarios que adotam pelo CLI (onde o ExecStartPost roda a sonda
        real): rede interna comum (o `nc -X connect` do agente resolve o proxy
        pelo nome), entrypoint real da imagem com sshd e porta 22, chave
        publica da fixture autorizada, e keyring do sandbox no ar.
        """
        self._init_repo(sb.worktree_dir)
        net: list[str] = []
        extra = ["--label", f"asb.workspace={sb.workspace}", "--label", "asb.role=agent", "--restart", policy]
        if ready:
            sb.register_network(sb.net_internal)
            run(PODMAN, "network", "create", "--internal", sb.net_internal, check=True)
            net = ["--network", sb.net_internal]
            sb._port = 22
            sb._image = IMAGE  # o sleeper alpine nao tem sshd; a sonda exige o entrypoint real
            sb._entrypoint_cmd = []
            sb._sentinel_path = "/tmp/sentinel.txt"  # uid 1000 nao escreve na raiz
            extra += [*net, "--userns", "keep-id:uid=1000,gid=1000",
                      "-e", f"ORCA_SSH_PUBLIC_KEY={sb.ssh_key.with_suffix('.pub').read_text().strip()}"]
        sb._extra_create_args = extra
        sb.setup_container()
        proxy = sb.register_container(f"{sb._prefix}-proxy")
        run(PODMAN, "create", "--name", proxy, "--pull=never", "--label", f"asb.workspace={sb.workspace}",
            "--label", "asb.role=proxy", "--restart", policy, *net, "--entrypoint", "python3", IMAGE,
            "-c", PROXY.replace("/pilot/requests", "/tmp/requests").replace(
                "Path('/pilot/status').read_text().strip()", "'200'"), check=True)
        if running if proxy_running is None else proxy_running:
            run(PODMAN, "start", proxy, check=True)
        if running:
            run(PODMAN, "start", sb.container, check=True)
        if ready:
            self.keyring(sb)  # a sonda do agente exige Secret Service respondendo
            if running:
                self._await_exec(sb.container)
        return sb.container, proxy

    @staticmethod
    def _await_exec(container: str, timeout: float = 30.0) -> None:
        """Espera o entrypoint real aceitar exec: `podman exec` num container ainda subindo devolve 255."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = run(PODMAN, "exec", container, "true")
            if last.returncode == 0:
                return
            time.sleep(0.5)
        state = run(PODMAN, "inspect", container, "--format",
                    "{{.State.Status}} exit={{.State.ExitCode}} err={{.State.Error}}").stdout.strip()
        logs = run(PODMAN, "logs", container)
        raise IsolationError(
            f"container {container} nao aceitou exec em {timeout:.0f}s apos o start; estado: {state}; "
            f"exec rc={last.returncode if last else '?'} stderr={(last.stderr or '').strip()[:300] if last else ''}; "
            f"logs: {(logs.stdout + logs.stderr).strip()[-500:]}"
        )

    def keyring(self, sb: SandboxFixture, *, running: bool = True, healthy: bool = True,
                policy: str = "unless-stopped") -> str:
        """Keyring sintetico com contrato de mounts real e responder D-Bus (ou sem ele)."""
        name = sb.register_container(sb.keyring_container)
        entry = KEYRING_DBUS if healthy else SLEEPER
        env = ["-e", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus"] if healthy else []
        run(PODMAN, "create", "--name", name, "--pull=never", "--label", "asb.role=keyring",
            "--label", "asb.keyring.schema=2", "--restart", policy, *env,
            "-v", f"{sb.credentials_volume}:/run/asb-credentials:ro",
            "-v", f"{sb.keyring_data_volume}:/run/asb-keyring-data:rw",
            "-v", f"{sb.keyring_runtime_volume}:/run/asb-keyring:rw",
            "-v", f"{sb.passphrase_file}:/run/asb-keyring-pass:ro",
            IMAGE, "sh", "-c", entry, check=True)
        if running:
            run(PODMAN, "start", name, check=True)
        return name

    def staged_runtime(self, sb: SandboxFixture, *, fail_role: str | None = None, message: str = "",
                     tag: str = "ok") -> tuple[Path, dict]:
        """Runtime montado pelo teste; a prova de integridade e o manifesto que ele devolve."""
        dest = install.install_runtime(ROOT, f"test-{tag}", target_base=sb.state_root / "runtimes")
        check = dest / "runtime_check.py"
        fail = repr(fail_role) if fail_role else "None"
        check.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "role = sys.argv[sys.argv.index('--role') + 1] if '--role' in sys.argv else ''\n"
            f"fail_role = {fail}\n"
            "if fail_role is not None and fail_role in (role, '*'):\n"
            f"    print({message!r}, file=sys.stderr)\n"
            "    sys.exit(1)\n"
            "sys.exit(0)\n")
        check.chmod(0o755)
        manifest = json.loads((dest / "manifest.json").read_text())
        manifest["files"]["runtime_check.py"] = {"sha256": hashlib.sha256(check.read_bytes()).hexdigest(), "mode": 0o755}
        (dest / "manifest.json").write_text(json.dumps(manifest))
        return dest / "launcher.sh", manifest

    # --- cenarios ---------------------------------------------------------------

    def test_01_dry_run_produces_inventory_and_zero_mutations(self) -> None:
        with self.sandbox("adopt01") as sb:
            agent, proxy = self.workspace(sb)
            res = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--json")
            self.assertCli(res)
            data = json.loads(res.stdout)
            self.assertEqual(data["status"], "dry_run")
            self.assertEqual(sorted(data["inventory"]["containers"]), ["agent", "proxy"])
            text = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace)
            self.assertCli(text)
            self.assertIn("dry-run concluido", text.stdout)
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("unless-stopped", "unless-stopped"))
            self.assertFalse((sb._unit_dir / f"asb-{sb.workspace}.target").exists())
            self.assertFalse(self.state_dir(sb).exists(), "dry-run criou o diretorio de estado")

            # I3: com o diretorio de estado existente, o dry-run disputa o mesmo lock.
            state = self.state_dir(sb)
            state.mkdir(parents=True)
            fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace)
            finally:
                os.close(fd)
            self.assertNotEqual(locked.returncode, 0)
            self.assertIn("lock ocupado", locked.stderr)
            self.assertEqual(sorted(p.name for p in state.iterdir()), [])

    def test_02_apply_and_rollback_preserve_identity_port_sentinel_data(self) -> None:
        with self.sandbox("adopt02") as sb:
            agent, proxy = self.workspace(sb, ready=True)
            identity = sb.inspect_identity()
            sb.write_sentinel("sentinel-preserve-test-42")
            target = f"asb-{sb.workspace}.target"

            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            self.assertEqual(sb.inspect_identity(), identity)
            self.assertTrue(sb.sentinel_exists())
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("no", "no"))
            self.assertEqual(self.unit_state(target), ("enabled-runtime", "active"))
            for unit in (target, f"asb-{sb.workspace}-agent.service", f"asb-{sb.workspace}-proxy.service"):
                self.assertEqual(self.fragment(unit), str(sb._unit_dir / unit))
            agent_unit = (sb._unit_dir / f"asb-{sb.workspace}-agent.service").read_text()
            self.assertIn(f"{sb.keyring_container}.service", agent_unit)
            self.assertNotIn("asb-keyring.service", agent_unit)
            self.assertFalse((REAL_HOME / ".config/systemd/user/default.target.wants" / target).exists())

            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertEqual(sb.inspect_identity(), identity)
            self.assertTrue(sb.sentinel_exists())
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("unless-stopped", "unless-stopped"))
            self.assertTrue(self.running(agent) and self.running(proxy))
            self.assert_units_gone(sb, target, f"asb-{sb.workspace}-agent.service", f"asb-{sb.workspace}-proxy.service")
            self.assertTrue((sb.worktree_dir / "README.md").is_file())

    def test_03_policies_and_running_stopped_states_restored_exactly(self) -> None:
        with self.sandbox("adopt03") as sb:
            agent, proxy = self.workspace(sb, running=False)
            res = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply", "--json")
            self.assertCli(res)
            self.assertEqual(json.loads(res.stdout)["phase"], "supervision_configured")
            self.assertFalse(self.running(agent) or self.running(proxy), "workspace parado foi ligado")
            self.assertEqual(self.policy(agent), "no")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertEqual(self.policy(agent), "unless-stopped")
            self.assertFalse(self.running(agent))

            # Container ligado durante a supervisao volta a parado no rollback.
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            run(PODMAN, "start", proxy, check=True)
            run(PODMAN, "start", agent, check=True)
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertFalse(self.running(agent) or self.running(proxy))

    def test_04_target_and_units_restored_on_rollback(self) -> None:
        with self.sandbox("adopt04") as sb:
            self.workspace(sb, ready=True)
            target = f"asb-{sb.workspace}.target"
            agent_unit = f"asb-{sb.workspace}-agent.service"
            target_file, agent_file = sb._unit_dir / target, sb._unit_dir / agent_unit
            manifest_file = self.state_dir(sb) / "runtime.json"
            manifest_file.parent.mkdir(parents=True)
            baseline = {
                target_file: "# sentinela target\n[Unit]\nDescription=Sentinel Target\n[Install]\nWantedBy=default.target\n",
                agent_file: "# sentinela agent\n[Unit]\nDescription=Sentinel Agent\n",
                manifest_file: json.dumps({"schemaVersion": 1, "custom_field": "sentinel"}, indent=2),
            }
            for path, text in baseline.items():
                path.write_text(text)
                path.chmod(0o640)
            run("systemctl", "--user", "daemon-reload", check=True)
            run("systemctl", "--user", "enable", "--runtime", target, check=True)
            run("systemctl", "--user", "start", target, check=True)

            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            self.assertNotEqual(target_file.read_text(), baseline[target_file])
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            for path, text in baseline.items():
                self.assertEqual((path.read_text(), path.stat().st_mode & 0o777), (text, 0o640), path)
            self.assertEqual(self.unit_state(target), ("enabled-runtime", "active"))
            self.assertEqual(self.unit_state(agent_unit), ("static", "inactive"))

            # Sem nada preexistente, o rollback remove tudo o que a adocao criou.
            run("systemctl", "--user", "disable", "--runtime", "--now", target, check=True)
            for path in baseline:
                path.unlink()
            (self.state_dir(sb) / "journal.json").unlink()
            run("systemctl", "--user", "daemon-reload", check=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertFalse(manifest_file.exists())
            self.assert_units_gone(sb, target, agent_unit, f"asb-{sb.workspace}-proxy.service")

    def test_05_divergent_id_before_apply_rollback_refuses_without_mutation(self) -> None:
        with self.sandbox("adopt05") as sb:
            agent, _ = self.workspace(sb, ready=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            path = self.state_dir(sb) / "journal.json"
            data = json.loads(path.read_text())
            real_id = data["containers"]["agent"]["id"]
            data["containers"]["agent"]["id"] = "f" * 64
            path.write_text(json.dumps(data))
            res = self.cli(sb, "rollback-runtime", "--workspace", sb.workspace)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("divergente", res.stderr)
            self.assertEqual(self.policy(agent), "no", "rollback recusado mutou a politica")
            self.assertTrue((sb._unit_dir / f"asb-{sb.workspace}.target").is_file())
            data["containers"]["agent"]["id"] = real_id
            path.write_text(json.dumps(data))
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))

    def test_06_failure_between_policy_update_and_start_restores_prior_state(self) -> None:
        with self.sandbox("adopt06") as sb:
            agent, proxy = self.workspace(sb)
            launcher, manifest = self.staged_runtime(sb)
            with self.iso(sb), mock.patch.object(sup, "_start_unit", side_effect=RuntimeError("falha injetada no start")) as start:
                with self.assertRaises(RuntimeError):
                    sup.adopt_workspace(sb.workspace, apply=True, helper_path=launcher, runtime_manifest=manifest)
            start.assert_called()
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("unless-stopped", "unless-stopped"))
            self.assertEqual(self.journal(sb)["phase"], "rolled_back")
            self.assert_units_gone(sb, f"asb-{sb.workspace}.target", f"asb-{sb.workspace}-agent.service")

    def test_07_interruption_per_phase_and_resumption_via_journal_are_idempotent(self) -> None:
        with self.sandbox("adopt07") as sb:
            agent, _ = self.workspace(sb, ready=True)
            for phase in ("units_prepared", "policies_updated", "supervision_started", "readiness_verified"):
                with self.subTest(phase=phase):
                    crash = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply", crash_at=phase)
                    self.assertCli(crash, 42)
                    self.assertEqual(self.journal(sb)["phase"], phase)
                    resumed = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply", "--json")
                    self.assertCli(resumed)
                    self.assertEqual(json.loads(resumed.stdout)["phase"], "readiness_verified")
                    after = self.journal(sb)
                    self.assertFalse(after["prior_units"]["target_existed"])
                    self.assertEqual(after["containers"]["agent"]["prior_restart_policy"], "unless-stopped")
                    self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
                    self.assertEqual(self.policy(agent), "unless-stopped")
                    self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))

            # C1: fase gravada cujo artefato foi desfeito recusa a retomada sem mutar.
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply",
                                    crash_at="policies_updated"), 42)
            run(PODMAN, "update", "--restart=unless-stopped", agent, check=True)
            refused = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("fase 'policies_updated'", refused.stderr)
            self.assertEqual(self.journal(sb)["phase"], "policies_updated")
            self.assertEqual(self.unit_state(f"asb-{sb.workspace}.target")[1], "inactive")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))

    def test_08_missing_corrupt_or_incompatible_journal_fails_closed(self) -> None:
        with self.sandbox("adopt08") as sb:
            self.workspace(sb)
            path = self.state_dir(sb) / "journal.json"
            path.parent.mkdir(parents=True)
            for content, needle in (("{ corrompido", "corrompido"), (json.dumps({"schemaVersion": 99}), "schemaVersion")):
                path.write_text(content)
                res = self.cli(sb, "rollback-runtime", "--workspace", sb.workspace)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(needle, res.stderr)
            path.unlink()
            res = self.cli(sb, "rollback-runtime", "--workspace", sb.workspace)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("ausente", res.stderr)

    def test_09_concurrent_locks_refuse_contention(self) -> None:
        with self.sandbox("adopt09") as sb:
            agent, _ = self.workspace(sb, ready=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            fd = os.open(self.state_dir(sb), os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for args in (("adopt-runtime", "--workspace", sb.workspace, "--apply"),
                             ("adopt-runtime", "--workspace", sb.workspace),
                             ("rollback-runtime", "--workspace", sb.workspace)):
                    res = self.cli(sb, *args)
                    self.assertNotEqual(res.returncode, 0, args)
                    self.assertIn("lock ocupado", res.stderr)
            finally:
                os.close(fd)
            self.assertEqual(self.policy(agent), "no")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))

    def test_10_keyring_dry_run_apply_rollback_and_workspace_does_not_stop_it(self) -> None:
        with self.sandbox("adopt10") as sb:
            self.workspace(sb, ready=True)  # ja sobe o keyring do sandbox, que a sonda exige
            k_unit = f"{sb.keyring_container}.service"
            with self.iso(sb):
                dry = sup.adopt_keyring(apply=False)
                self.assertEqual(dry["status"], "dry_run")
                self.assertFalse(self.state_dir(sb, "keyring").exists(), "dry-run criou estado do keyring")
                self.assertEqual(sup.adopt_keyring(apply=True)["phase"], "readiness_verified")
                self.assertEqual(sup.adopt_workspace(sb.workspace, apply=True)["status"], "applied")
            self.assertEqual(self.fragment(k_unit), str(sb._unit_dir / k_unit))
            with self.iso(sb):
                sup.rollback_workspace(sb.workspace)
            self.assertEqual(self.unit_state(k_unit)[1], "active", "rollback do workspace parou o keyring")
            with self.iso(sb):
                self.assertEqual(sup.rollback_keyring()["status"], "rolled_back")
            self.assert_units_gone(sb, k_unit)

    def test_11_third_party_dropin_preserved_and_project_dropin_removed_and_restored(self) -> None:
        with self.sandbox("adopt11") as sb:
            self.keyring(sb)
            dropin = sb.config_dir / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
            dropin.parent.mkdir(parents=True)
            foreign = "# drop-in de terceiro\n[Service]\nEnvironment=CUSTOM=1\n"
            project = install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n"

            dropin.write_text(foreign)
            with self.iso(sb):
                sup.adopt_keyring(apply=True)
                self.assertEqual(dropin.read_text(), foreign)
                sup.rollback_keyring()
            self.assertEqual(dropin.read_text(), foreign)

            dropin.write_text(project)
            dropin.chmod(0o644)
            with self.iso(sb):
                sup.adopt_keyring(apply=True)
                self.assertFalse(dropin.exists())
                sup.rollback_keyring()
            self.assertEqual((dropin.read_text(), dropin.stat().st_mode & 0o777), (project, 0o644))

            # I4: troca entre a ultima validacao e a remocao, provocada dentro da adocao.
            swapped: list[int] = []
            real_rename = os.rename

            def swap_then_rename(src, *args, **kwargs):
                if not swapped and os.fspath(src) == dropin.name:
                    tmp = dropin.parent / ".swap"
                    tmp.write_text(foreign)
                    os.replace(tmp, dropin)
                    swapped.append(dropin.stat().st_ino)
                return real_rename(src, *args, **kwargs)

            with self.iso(sb), mock.patch("os.rename", side_effect=swap_then_rename):
                with self.assertRaises(RuntimeError) as cm:
                    sup.adopt_keyring(apply=True)
            self.assertIn("substitu", str(cm.exception))
            self.assertEqual((dropin.read_text(), dropin.stat().st_ino), (foreign, swapped[0]))
            self.assertEqual(self.journal(sb, "keyring")["phase"], "rolled_back")
            self.assert_units_gone(sb, f"{sb.keyring_container}.service")

    def test_12_diagnostic_separates_legacy_mounts_forwarder_and_supervision(self) -> None:
        with self.sandbox("adopt12") as sb:
            self.workspace(sb)
            diag = json.loads(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--json").stdout)["inventory"]["diagnostics"]
            self.assertEqual(sorted(diag), ["forwarder_needs_recreation", "legacy_credentials_layout", "rootless_netns_producers"])
            self.assertFalse(diag["legacy_credentials_layout"])
            self.assertFalse(diag["forwarder_needs_recreation"])

            mountpoint = Path(run(PODMAN, "volume", "inspect", sb.credentials_volume, "--format", "{{.Mountpoint}}", check=True).stdout.strip())
            (mountpoint / ".credentials.json").write_text("{}")
            fwd = sb.register_container(f"asb-{sb.workspace}-forwarder")
            run(PODMAN, "create", "--name", fwd, "--pull=never", ALPINE, "true", check=True)
            diag2 = json.loads(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--json").stdout)["inventory"]["diagnostics"]
            self.assertTrue(diag2["legacy_credentials_layout"])
            self.assertTrue(diag2["forwarder_needs_recreation"])

    def test_13_rootless_netns_producers_only_inventoried(self) -> None:
        """Um produtor injetado de CADA classe tem de aparecer nomeado.

        A versao anterior deste cenario nao injetava produtor algum e apenas
        afirmava que o resultado era uma `list` — asserçao que passava com o
        inventario vazio, com o inventario correto e com qualquer coisa no
        meio. Aqui entram as tres classes que o gate nomeou: drop-in alheio no
        mesmo `.d`, unidade legada de outro workspace e container sem label
        `asb.workspace=`. E o contrato do cenario continua sendo o mesmo: SO
        inventariar, nunca mutar.
        """
        with self.sandbox("adopt13") as sb:
            self.workspace(sb)

            # 1. drop-in alheio, ao lado do nosso, no `.d` isolado da fixture
            dropins = sb.config_dir / "systemd" / "user" / "podman-restart.service.d"
            dropins.mkdir(parents=True, exist_ok=True)
            (dropins / "agent-sandbox.conf").write_text(
                install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
            foreign_dropin = dropins / "zz-outro-projeto.conf"
            foreign_dropin.write_text("[Service]\nEnvironment=ALHEIO=1\n")
            foreign_dropin.chmod(0o600)

            # 2. unidade legada de outro workspace, na raiz do drop-in — que
            #    num host real e `~/.config/systemd/user`, e aqui e a raiz
            #    isolada da fixture
            legacy_unit = dropins.parent / "asb-test-legado-ws.target"
            legacy_unit.write_text("[Unit]\nDescription=legado\n")

            def producers_now() -> list[str]:
                trace: list[list[str]] = []
                with self.iso(sb, trace):
                    dry = sup.adopt_workspace(sb.workspace, apply=False)
                # O contrato do cenario: SO inventariar, nunca mutar.
                self.assertFalse([c for c in trace if c[0].endswith("podman")
                                  and c[1] in ("unshare", "update", "start", "stop")])
                return dry["inventory"]["diagnostics"]["rootless_netns_producers"]

            def unlabelled(producers: list[str]) -> int:
                hits = [q for q in producers if q.startswith("containers_sem_label:")]
                return int(hits[0].split(":", 1)[1]) if hits else 0

            # A consulta de containers e do host inteiro, como tem de ser num
            # diagnostico de coexistencia — logo a contagem absoluta depende do
            # host. O que o cenario prova e o DELTA: injetar um container sem
            # label faz a contagem subir exatamente um.
            baseline = producers_now()
            before = unlabelled(baseline)

            # 3. container SEM label `asb.workspace=`: a classe que a contagem
            #    derivada daquele label ignorava por construcao
            plain = sb.register_container(f"asb-{sb.workspace}-sem-label")
            run(PODMAN, "create", "--name", plain, "--pull=never", ALPINE, "true", check=True)

            producers = producers_now()
            self.assertIn("dropin:agent-sandbox.conf(projeto)", producers)
            self.assertIn("dropin:zz-outro-projeto.conf(alheio)", producers)
            self.assertIn("unit:asb-test-legado-ws.target(legada ou de outro workspace)", producers)
            self.assertEqual(unlabelled(producers), before + 1, producers)
            self.assertTrue([q for q in producers if q.startswith("workspaces_rotulados:")], producers)
            # A unidade do proprio workspace desta transacao nao e produtor de fora.
            self.assertFalse([q for q in producers if f"asb-{sb.workspace}.target" in q], producers)

            # O drop-in alheio segue intacto em conteudo e em modo.
            self.assertEqual(foreign_dropin.read_text(), "[Service]\nEnvironment=ALHEIO=1\n")
            self.assertEqual(foreign_dropin.stat().st_mode & 0o777, 0o600)

    def test_14_adoption_and_rollback_never_call_podman_rm_create_run(self) -> None:
        with self.sandbox("adopt14") as sb:
            self.workspace(sb, ready=True)  # ja sobe o keyring do sandbox, que a sonda exige
            trace: list[list[str]] = []
            with self.iso(sb, trace):
                sup.adopt_workspace(sb.workspace, apply=True)
                sup.rollback_workspace(sb.workspace)
                sup.adopt_keyring(apply=True)
                sup.rollback_keyring()
            ops = [c[1] for c in trace if Path(c[0]).name == "podman"]
            self.assertFalse(set(ops) & {"rm", "create", "run"}, ops)
            self.assertIn("update", ops)

    def test_15_teardown_leaves_zero_registered_resources(self) -> None:
        with self.sandbox("adopt15") as sb:
            self.workspace(sb, ready=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            prefix, units = sb._prefix, sorted(sb._registered_units)
        for kind in ("ps -a", "volume ls", "network ls"):
            res = run(PODMAN, *kind.split(), "--filter", f"name=^{prefix}[.-]", "--quiet")
            self.assertEqual((res.returncode, res.stdout.strip()), (0, ""), kind)
        for root in (sb._unit_dir, REAL_HOME / ".config" / "systemd" / "user"):
            for unit in units:
                self.assertFalse((root / unit).exists() or (root / "default.target.wants" / unit).is_symlink(), unit)
        res = run("systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", *units)
        self.assertEqual((res.returncode, res.stdout.strip()), (0, ""))
        self.assertFalse(sb.state_root.exists())

    def test_16_invalid_traversal_and_duplicate_roles_refused_without_mutation(self) -> None:
        with self.sandbox("adopt16a") as sb:
            sb._extra_create_args = ["--label", f"asb.workspace={sb.workspace}", "--label", "asb.role=../../escaped",
                                     "--restart", "unless-stopped"]
            sb.setup_container()
            res = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("papel nao-canonico ou invalido", res.stderr)
            self.assertEqual(self.policy(sb.container), "unless-stopped")
            # Delimitado, nunca `asb-{ws}*`: o prefixo cru casaria com as units
            # de um workspace vizinho cujo nome comece igual (R1).
            self.assertEqual(
                [q for q in sb._unit_dir.iterdir() if q.name in sb._registered_units], [])
        with self.sandbox("adopt16b") as sb:
            sb._extra_create_args = ["--label", f"asb.workspace={sb.workspace}", "--label", "asb.role=agent",
                                     "--restart", "unless-stopped"]
            sb.setup_container()
            twin = sb.register_container(f"{sb._prefix}-agent2")
            run(PODMAN, "create", "--name", twin, "--pull=never", *sb._extra_create_args, ALPINE, "sh", "-c", SLEEPER, check=True)
            res = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("papel duplicado", res.stderr)
            # Delimitado, nunca `asb-{ws}*`: o prefixo cru casaria com as units
            # de um workspace vizinho cujo nome comece igual (R1).
            self.assertEqual(
                [q for q in sb._unit_dir.iterdir() if q.name in sb._registered_units], [])

    def test_17_readiness_probe_failure_triggers_automatic_rollback(self) -> None:
        with self.sandbox("adopt17") as sb:
            agent, proxy = self.workspace(sb)
            for role in ("*", "agent"):
                with self.subTest(role=role):
                    launcher, manifest = self.staged_runtime(sb, fail_role=role, message=f"falha de prontidao em {role}",
                                                           tag=f"fail-{'all' if role == '*' else role}")
                    with self.iso(sb), self.assertRaises(RuntimeError) as cm:
                        sup.adopt_workspace(sb.workspace, apply=True, helper_path=launcher,
                                            runtime_manifest=manifest)
                    self.assertIn("sonda de prontidao", str(cm.exception))
                    if role == "agent":
                        self.assertIn("agent", str(cm.exception))
                    self.assertEqual((self.policy(agent), self.policy(proxy)), ("unless-stopped", "unless-stopped"))
                    self.assertTrue(self.running(agent) and self.running(proxy))
                    self.assertEqual(self.journal(sb)["phase"], "rolled_back")
                    self.assert_units_gone(sb, f"asb-{sb.workspace}.target")
            launcher, manifest = self.staged_runtime(sb, tag="retry")
            with self.iso(sb):
                self.assertEqual(sup.adopt_workspace(sb.workspace, apply=True, helper_path=launcher,
                                                     runtime_manifest=manifest)["phase"], "readiness_verified")
                sup.rollback_workspace(sb.workspace)

    def test_18_mixed_container_states_preserved_on_apply_and_rollback(self) -> None:
        with self.sandbox("adopt18a") as sb:
            agent, proxy = self.workspace(sb, running=True, proxy_running=False)
            res = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("proxy parado", res.stderr)
            self.assertEqual(self.policy(agent), "unless-stopped")
            self.assertFalse((sb._unit_dir / f"asb-{sb.workspace}.target").exists())
        with self.sandbox("adopt18b") as sb:
            agent, proxy = self.workspace(sb, running=False, proxy_running=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            self.assertFalse(self.running(agent), "agent parado foi ligado")
            self.assertTrue(self.running(proxy))
            self.assertEqual(self.unit_state(f"asb-{sb.workspace}-proxy.service")[1], "active")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertFalse(self.running(agent))
            self.assertTrue(self.running(proxy))

    def test_19_structural_journal_validation_fails_closed(self) -> None:
        with self.sandbox("adopt19") as sb:
            self.workspace(sb)
            with self.iso(sb):
                inventory = sup.adopt_workspace(sb.workspace, apply=False)["inventory"]
            path = self.state_dir(sb) / "journal.json"
            path.parent.mkdir(parents=True)
            cases = (
                (lambda j: j.update(schemaVersion=99), "schemaVersion incompativel"),
                (lambda j: j.update(containers=["x"]), "containers"),
                (lambda j: j["containers"].update({"../../bad": j["containers"].pop("agent")}), "papel nao-canonico"),
                (lambda j: j.update(malicioso=1), "chaves nao reconhecidas"),
                (lambda j: j["prior_units"].update(target_file="/tmp/evil/" + Path(j["prior_units"]["target_file"]).name),
                 "nao derivado"),
            )
            for mutate, needle in cases:
                with self.subTest(needle=needle):
                    j = json.loads(json.dumps(inventory))
                    mutate(j)
                    path.write_text(json.dumps(j))
                    res = self.cli(sb, "rollback-runtime", "--workspace", sb.workspace)
                    self.assertNotEqual(res.returncode, 0)
                    self.assertIn(needle, res.stderr)

    def test_20_immediate_container_id_validation_prevents_mutation(self) -> None:
        with self.sandbox("adopt20") as sb:
            agent, proxy = self.workspace(sb)
            with self.assertRaises(ValueError):
                sup._verify_single_container_id("f" * 64, agent)

            real_write = sup._atomic_write_text
            recreated: list[str] = []

            def write_then_recreate(path, content, *a, **kw):
                real_write(path, content, *a, **kw)
                if Path(path).name == "runtime.json" and not recreated:
                    # Proxy recriado por fora com o mesmo nome logo apos a 1a mutacao.
                    run(PODMAN, "rm", "-f", proxy, check=True)
                    run(PODMAN, "create", "--name", proxy, "--pull=never", "--label", f"asb.workspace={sb.workspace}",
                        "--label", "asb.role=proxy", "--restart", "always", ALPINE, "sh", "-c", SLEEPER, check=True)
                    recreated.append(self.cid(proxy))

            with self.iso(sb), mock.patch.object(sup, "_atomic_write_text", side_effect=write_then_recreate):
                with self.assertRaises(ValueError) as cm:
                    sup.adopt_workspace(sb.workspace, apply=True)
            self.assertIn("ID divergente", str(cm.exception))
            self.assertEqual(self.policy(proxy), "always", "o container novo sofreu mutacao")
            self.assertEqual(self.policy(agent), "unless-stopped")
            self.assertFalse((sb._unit_dir / f"asb-{sb.workspace}.target").exists(), "mutacao seguinte ocorreu")
            journal = self.journal(sb)
            self.assertIn("ID divergente", journal["error"]["message"])
            self.assertIn("ID divergente", journal["rollback_error"]["message"])

    def test_21_keyring_comprehensive_transactional_parity(self) -> None:
        k_unit_of = lambda sb: f"{sb.keyring_container}.service"  # noqa: E731
        with self.sandbox("adopt21a") as sb:  # parado: supervision_configured, nao liga
            name = self.keyring(sb, running=False)
            with self.iso(sb):
                self.assertEqual(sup.adopt_keyring(apply=True)["phase"], "supervision_configured")
                self.assertFalse(self.running(name))
                sup.rollback_keyring()
            self.assertEqual((self.policy(name), self.running(name)), ("unless-stopped", False))
        with self.sandbox("adopt21b") as sb:  # lock no diretorio de estado
            self.keyring(sb)
            state = self.state_dir(sb, "keyring")
            state.mkdir(parents=True)
            fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.iso(sb):
                    for apply in (True, False):
                        with self.assertRaises(RuntimeError) as cm:
                            sup.adopt_keyring(apply=apply)
                        self.assertIn("lock ocupado", str(cm.exception))
            finally:
                os.close(fd)
        with self.sandbox("adopt21c") as sb:  # unit preexistente com modo 0o640
            self.keyring(sb)
            unit_file = sb._unit_dir / k_unit_of(sb)
            sentinel = "# sentinela keyring\n[Unit]\nDescription=Sentinel Keyring\n"
            unit_file.write_text(sentinel)
            unit_file.chmod(0o640)
            run("systemctl", "--user", "daemon-reload", check=True)
            with self.iso(sb):
                sup.adopt_keyring(apply=True)
                self.assertNotEqual(unit_file.read_text(), sentinel)
                sup.rollback_keyring()
            self.assertEqual((unit_file.read_text(), unit_file.stat().st_mode & 0o777), (sentinel, 0o640))
            unit_file.unlink()
        with self.sandbox("adopt21d") as sb:  # crash real por fase e retomada
            name = self.keyring(sb)
            for phase in ("units_prepared", "policies_updated", "supervision_started", "readiness_verified"):
                with self.subTest(phase=phase):
                    self.assertCli(self.cli(sb, "adopt-runtime", "--keyring", "--apply", crash_at=phase), 42)
                    self.assertEqual(self.journal(sb, "keyring")["phase"], phase)
                    resumed = self.cli(sb, "adopt-runtime", "--keyring", "--apply", "--json")
                    self.assertCli(resumed)
                    self.assertEqual(json.loads(resumed.stdout)["phase"], "readiness_verified")
                    self.assertCli(self.cli(sb, "rollback-runtime", "--keyring"))
                    self.assertEqual(self.policy(name), "unless-stopped")

    def test_22_rollback_failure_injected_fails_closed_and_preserves_journal(self) -> None:
        with self.sandbox("adopt22") as sb:
            agent, _ = self.workspace(sb, ready=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            real_run = podman_mod.run

            def failing_update(*args, **kwargs):
                if args[:1] == ("update",):
                    raise RuntimeError("falha injetada no update do rollback")
                return real_run(*args, **kwargs)

            with self.iso(sb), mock.patch.object(podman_mod, "run", side_effect=failing_update) as prun:
                with self.assertRaises(RuntimeError):
                    sup.rollback_workspace(sb.workspace)
            prun.assert_called()
            journal = self.journal(sb)
            self.assertNotEqual(journal["phase"], "rolled_back")
            self.assertEqual(journal["error"]["type"], "RuntimeError")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertEqual(self.journal(sb)["phase"], "rolled_back")
            self.assertEqual(self.policy(agent), "unless-stopped")

    def test_23_cli_json_and_human_readable_output_contract(self) -> None:
        with self.sandbox("adopt23") as sb:
            self.workspace(sb)
            text = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace)
            self.assertCli(text)
            self.assertIn("dry-run concluido para workspace", text.stdout)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(text.stdout)
            parsed = json.loads(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--json").stdout)
            self.assertEqual((parsed["status"], parsed["workspace"]), ("dry_run", sb.workspace))

    def test_24_installed_runtime_contains_zero_mocks_or_test_failpoints(self) -> None:
        with self.sandbox("adopt24") as sb:
            dest = install.install_runtime(ROOT, "test-rev", target_base=sb.state_root / "runtimes")
            for path in dest.rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    for pattern in (".mock", "mock_readiness", "mock_fail", "ASB_TEST_CRASH", "test_failpoint"):
                        self.assertNotIn(pattern, text, path)
            self.assertEqual(json.loads((dest / "manifest.json").read_text()), install.runtime_manifest(ROOT, "test-rev"))

    def test_25_advanced_unit_and_diagnostic_validations(self) -> None:
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "Failed to connect to bus\n")) as sr:
            with self.assertRaises(RuntimeError) as cm:
                sup._systemd_unit_status("asb-test-fake.service")
        sr.assert_called_once()
        self.assertIn("Failed to connect to bus", str(cm.exception))
        with mock.patch.object(podman_mod, "out", return_value=json.dumps({"Name": "on-failure", "MaximumRetryCount": 3})) as out:
            self.assertEqual(sup._inspect_container_restart_policy("cid"), ("on-failure", 3))
        out.assert_called_once()
        with mock.patch.object(podman_mod, "run", return_value=subprocess.CompletedProcess([], 125, "", "Error: connection refused")) as prun:
            diag = sup._collect_diagnostics("asb-test-diag")
        prun.assert_called()
        # rc 125 nao e "ausente": os tres diagnosticos tem de dizer que nao sabem.
        self.assertEqual(diag["legacy_credentials_layout"], "unknown: Error: connection refused")
        self.assertEqual(diag["forwarder_needs_recreation"], "unknown: Error: connection refused")
        self.assertIn("unknown: Error: connection refused", diag["rootless_netns_producers"])
        with self.sandbox("adopt25") as sb:
            base = sb.state_root / "runtimes"
            launcher, _, rev = sup._resolve_versioned_runtime(revision="test-v1", target_base=base)
            pristine = launcher.read_bytes()
            launcher.write_text("# corrompido\n")
            launcher2, _, _ = sup._resolve_versioned_runtime(revision="test-v1", target_base=base)
            self.assertEqual((rev, launcher2.read_bytes()), ("test-v1", pristine))

    def test_26_keyring_readiness_failure_triggers_automatic_rollback(self) -> None:
        with self.sandbox("adopt26") as sb:
            name = self.keyring(sb, healthy=False)
            with self.iso(sb), self.assertRaises(RuntimeError) as cm:
                sup.adopt_keyring(apply=True)
            self.assertIn("sonda de prontidao", str(cm.exception))
            self.assertEqual((self.policy(name), self.running(name)), ("unless-stopped", True))
            self.assertEqual(self.journal(sb, "keyring")["phase"], "rolled_back")
            self.assert_units_gone(sb, f"{sb.keyring_container}.service")

    def test_27_workspace_double_fault_records_rollback_error_and_resumes(self) -> None:
        with self.sandbox("adopt27") as sb:
            agent, _ = self.workspace(sb)
            launcher, manifest = self.staged_runtime(sb, fail_role="*", message="falha de prontidao injetada", tag="dbl")
            real_run = podman_mod.run

            def fail_restore(*args, **kwargs):
                if args[:1] == ("update",) and args[1] != "--restart=no":
                    raise RuntimeError("double fault injetado no rollback automatico")
                return real_run(*args, **kwargs)

            with self.iso(sb), mock.patch.object(podman_mod, "run", side_effect=fail_restore) as prun:
                with self.assertRaises(RuntimeError):
                    sup.adopt_workspace(sb.workspace, apply=True, helper_path=launcher,
                                        runtime_manifest=manifest)
            prun.assert_called()
            journal = self.journal(sb)
            self.assertIn("double fault injetado", journal["rollback_error"]["message"])
            self.assertNotEqual(journal["phase"], "rolled_back")
            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertEqual((self.journal(sb)["phase"], self.policy(agent)), ("rolled_back", "unless-stopped"))

    def test_28_keyring_double_fault_records_rollback_error_and_resumes(self) -> None:
        with self.sandbox("adopt28") as sb:
            name = self.keyring(sb, healthy=False)
            real_run = podman_mod.run

            def fail_restore(*args, **kwargs):
                if args[:1] == ("update",) and args[1] != "--restart=no":
                    raise RuntimeError("double fault injetado no rollback do keyring")
                return real_run(*args, **kwargs)

            with self.iso(sb), mock.patch.object(podman_mod, "run", side_effect=fail_restore) as prun:
                with self.assertRaises(RuntimeError):
                    sup.adopt_keyring(apply=True)
            prun.assert_called()
            self.assertIn("double fault injetado", self.journal(sb, "keyring")["rollback_error"]["message"])
            with self.iso(sb):
                self.assertEqual(sup.rollback_keyring()["status"], "rolled_back")
            self.assertEqual((self.journal(sb, "keyring")["phase"], self.policy(name)), ("rolled_back", "unless-stopped"))

    def test_29_stopped_workspace_adopted_and_resumed(self) -> None:
        """I5: workspace parado, adotado, religado pelo `asb-agent resume` real e revertido."""
        with self.sandbox("adopt29") as sb:
            agent, proxy = self._real_workspace(sb)
            target = f"asb-{sb.workspace}.target"
            ids = (self.cid(agent), self.cid(proxy))
            control = socketserver.ThreadingTCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler)
            threading.Thread(target=control.serve_forever, daemon=True).start()
            self.addCleanup(control.server_close)
            self.addCleanup(control.shutdown)
            host_target = f"127.0.0.1:{control.server_address[1]}"
            sb.register_container(sb.keyring_container)
            self.assertCli(self.cli(sb, "setup-keyring"))

            adopted = self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply", "--json")
            self.assertCli(adopted)
            self.assertEqual(json.loads(adopted.stdout)["phase"], "supervision_configured")
            self.assertFalse(self.running(agent) or self.running(proxy))
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("no", "no"))

            resumed = self.cli(sb, "resume", "--workspace", sb.workspace, host_target=host_target)
            self.assertCli(resumed)
            lines = [line for line in resumed.stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, resumed.stdout)
            port = int(json.loads(lines[0])["port"])
            self.assertEqual(port, sb.inspect_identity()[1])
            self.assertEqual((self.cid(agent), self.cid(proxy)), ids)
            self.assertTrue(self.running(agent) and self.running(proxy))
            self.assertEqual(self.unit_state(target)[1], "active")
            self.assertEqual(self.fragment(target), str(sb._unit_dir / target))
            ssh = readiness.probe_ssh(port=port, key=sb.ssh_key, timeout=10.0)
            self.assertEqual(ssh.state, "healthy", ssh)
            # Estado e target consumidos sao os temporarios, nunca um workspace canonico.
            self.assertTrue((self.state_dir(sb) / "runtime.json").is_file())
            self.assertFalse((REAL_HOME / ".local/state/agent-sandbox" / sb.workspace).exists())

            self.assertCli(self.cli(sb, "rollback-runtime", "--workspace", sb.workspace))
            self.assertFalse(self.running(agent) or self.running(proxy))
            self.assertEqual((self.policy(agent), self.policy(proxy)), ("unless-stopped", "unless-stopped"))
            self.assertFalse((REAL_HOME / ".config/systemd/user/default.target.wants" / target).is_symlink(),
                             "rollback nao removeu a habilitacao persistente criada pelo resume")
            self.assert_units_gone(sb, target)

    def _real_workspace(self, sb: SandboxFixture) -> tuple[str, str]:
        """Workspace legado parado com sshd real (receita do piloto T1) e rotulos de inventario."""
        home = home_of(sb)
        layout = layout_for(sb.worktree_dir, sb.workspace, home)
        layout.state.mkdir(parents=True)
        layout.project_root.mkdir(parents=True)
        (layout.state / "origin").write_text(str(sb.worktree_dir))
        proxy_data = sb.state_root / "proxy"
        proxy_data.mkdir()
        (proxy_data / "status").write_text("200")
        sb.register_network(sb.net_internal)
        run(PODMAN, "network", "create", "--internal", sb.net_internal, check=True)
        labels = lambda role: ["--label", f"asb.workspace={sb.workspace}", "--label", f"asb.role={role}"]  # noqa: E731
        proxy = sb.register_container(f"{sb._prefix}-proxy")
        run(PODMAN, "create", "--name", proxy, "--pull=never", "--network", sb.net_internal, *labels("proxy"),
            "--restart", "unless-stopped", "--entrypoint", "python3", "-v", f"{proxy_data}:/pilot:Z", IMAGE,
            "-c", PROXY, check=True)
        cred = Path(run(PODMAN, "volume", "inspect", sb.credentials_volume, "--format", "{{.Mountpoint}}", check=True).stdout.strip())
        mounts: list[str] = []
        for provider in ("claude", "codex"):
            (cred / provider).mkdir(mode=0o700)
            mounts += ["--mount", f"type=volume,src={sb.credentials_volume},dst=/home/{getpass.getuser()}/.{provider},"
                                  f"volume-subpath={provider}"]
        agent = sb.register_container(f"{sb._prefix}-agent")
        run(PODMAN, "create", "--name", agent, "--pull=never", "--network", sb.net_internal, *labels("agent"),
            "--restart", "unless-stopped", "--userns", "keep-id:uid=1000,gid=1000", "-p", "127.0.0.1::22",
            "-e", f"ORCA_SSH_PUBLIC_KEY={sb.ssh_key.with_suffix('.pub').read_text().strip()}",
            "-v", f"{layout.project_root}:/pilot-project:Z", *mounts, IMAGE, check=True)
        sb.container = agent
        sb._port = 22
        return agent, proxy

    def test_30_uninventoried_roles_untouched_on_rollback(self) -> None:
        with self.sandbox("adopt30") as sb:
            self.workspace(sb, ready=True)
            self.assertCli(self.cli(sb, "adopt-runtime", "--workspace", sb.workspace, "--apply"))
            sentinels = {
                sb._unit_dir / f"asb-{sb.workspace}-forwarder.service": "# sentinela forwarder\n[Unit]\nDescription=Fwd\n",
                sb._unit_dir / f"asb-{sb.workspace}-docker.service": "# sentinela docker\n[Unit]\nDescription=Doc\n",
            }
            for path, text in sentinels.items():
                path.write_text(text)
                path.chmod(0o640)
            trace: list[list[str]] = []
            with self.iso(sb, trace):
                sup.rollback_workspace(sb.workspace)
            for path, text in sentinels.items():
                self.assertEqual((path.read_text(), path.stat().st_mode & 0o777), (text, 0o640))
            touched = {a for c in trace if Path(c[0]).name == "systemctl" for a in c[3:]}
            self.assertFalse(touched & {p.name for p in sentinels}, "rollback consultou/mutou role nao inventariado")


# Responder D-Bus minimo em /run/asb-keyring/bus (SASL, Hello e GetNameOwner).
KEYRING_DBUS = (
    "python3 -c \"\n"
    "import socket, struct, os, time, signal, threading\n"
    "sp = '/run/asb-keyring/bus'\n"
    "if os.path.exists(sp):\n"
    "    os.unlink(sp)\n"
    "os.makedirs(os.path.dirname(sp), exist_ok=True)\n"
    "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
    "s.bind(sp)\n"
    "os.chmod(sp, 0o777)\n"
    "s.listen(10)\n"
    "def pad(data, n=8):\n"
    "    return data + (b'\\\\x00' * ((n - len(data) % n) % n))\n"
    "def make_string(val):\n"
    "    b = val.encode('utf-8')\n"
    "    return struct.pack('<I', len(b)) + b + b'\\\\x00'\n"
    "def make_sig(sig):\n"
    "    b = sig.encode('utf-8')\n"
    "    return bytes([len(b)]) + b + b'\\\\x00'\n"
    "def build_msg(msg_type, serial, reply_serial, dest, sender, sig, body):\n"
    "    fields = [(5, 'u', struct.pack('<I', reply_serial)), (6, 's', make_string(dest)),\n"
    "              (7, 's', make_string(sender)), (8, 'g', make_sig(sig))]\n"
    "    arr = b''\n"
    "    for fid, fsig, val in fields:\n"
    "        arr = pad(arr, 8) + bytes([fid]) + make_sig(fsig) + val\n"
    "    head = struct.pack('<BBBBI I I', ord('l'), msg_type, 1, 1, len(body), serial, len(arr))\n"
    "    return pad(head + arr, 8) + body\n"
    "def handle(c):\n"
    "    while True:\n"
    "        line = b''\n"
    "        while not line.endswith(b'\\\\r\\\\n'):\n"
    "            b = c.recv(1)\n"
    "            if not b: return\n"
    "            line += b\n"
    "        if line.startswith(b'\\\\x00AUTH') or line.startswith(b'AUTH'):\n"
    "            c.sendall(b'OK 0123456789abcdef0123456789abcdef\\\\r\\\\n')\n"
    "        elif line.startswith(b'NEGOTIATE_UNIX_FD'):\n"
    "            c.sendall(b'ERROR\\\\r\\\\n')\n"
    "        elif line.startswith(b'BEGIN'):\n"
    "            break\n"
    "    while True:\n"
    "        hdr = c.recv(16)\n"
    "        if len(hdr) < 16: break\n"
    "        _, mtype, _, _, body_l, serial, fields_l = struct.unpack('<BBBBI I I', hdr)\n"
    "        c.recv(fields_l + ((8 - fields_l % 8) % 8) + body_l)\n"
    "        if mtype == 1:\n"
    "            owner = ':1.0' if serial == 1 else ':1.42'\n"
    "            c.sendall(build_msg(2, serial, serial, ':1.0', 'org.freedesktop.DBus', 's', make_string(owner)))\n"
    "def loop():\n"
    "    while True:\n"
    "        try:\n"
    "            c, _ = s.accept()\n"
    "            handle(c)\n"
    "            c.close()\n"
    "        except Exception:\n"
    "            break\n"
    "threading.Thread(target=loop, daemon=True).start()\n"
    "signal.signal(signal.SIGTERM, lambda *a: os._exit(0))\n"
    "signal.signal(signal.SIGINT, lambda *a: os._exit(0))\n"
    "while True:\n"
    "    time.sleep(0.5)\n"
    "\"\n"
)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--i6-cli":
        sys.exit(i6_cli(Path(sys.argv[2]), sys.argv[3:]))
    unittest.main()
