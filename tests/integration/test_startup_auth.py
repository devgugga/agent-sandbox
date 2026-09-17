"""Real Podman/systemd/SSH pilot with isolated, synthetic network edges.

Home lookup, host control destination, desktop netns repair and the last
provider command are seams. Keyring failure is injected by stopping its real
container after repair. Readiness results and SSH are never mocked.
"""
from __future__ import annotations

import contextlib
import getpass
import json
import os
import runpy
import shlex
import socketserver
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
sys.path.insert(0, str(ROOT))
from asb import auth, keyring, lifecycle, readiness  # noqa: E402
from asb.workspace import layout_for  # noqa: E402
from tests.integration.sandbox_fixture import IsolationError, SandboxFixture  # noqa: E402


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


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, **kwargs)


def guard_podman(command, cfg):
    """Reject Podman resources and systemd units outside the registered pilot."""
    binary = Path(command[0]).name
    if binary not in ("podman", "systemctl"):
        return
    registered = set(cfg["resources"])

    def resource(name):
        if name not in registered or not name.startswith(cfg["prefix"]):
            raise IsolationError(f"Podman resource outside registered pilot: {name}")

    def mount_source(source):
        if source.startswith("/"):
            if not Path(source).resolve().is_relative_to(Path(cfg["root"]).resolve()):
                raise IsolationError(f"Podman mount outside pilot: {source}")
        else:
            resource(source)

    def reject():
        raise IsolationError(f"Unsupported resource command in pilot: {command}")

    if binary == "systemctl":
        if command[1:] == ["--user", "daemon-reload"]:
            return
        if len(command) < 4 or command[1] != "--user" or command[2] not in (
                "enable", "reset-failed", "start", "stop", "disable", "is-active"):
            reject()
        for unit in command[3:]:
            resource(unit)
        return

    args = command[1:]
    if not args:
        reject()
    operation, *args = args
    if operation == "image":
        if args not in (["exists", "agent-sandbox:latest"], ["exists", "agent-sandbox-proxy:latest"]):
            reject()
        return
    if operation in ("container", "volume", "network"):
        if not args:
            reject()
        operation, *args = args
    if operation == "exec":
        while args and args[0] in ("-u", "--user"):
            args = args[2:]
        if not args:
            reject()
        resource(args[0])
        return  # Remaining operands are commands inside this owned container.
    if operation in ("run", "create"):
        named = network = False
        while args and args[0].startswith("-"):
            option = args.pop(0)
            if option in ("-d", "--pull=never"):
                continue
            if option not in ("--name", "--network", "-v", "--volume", "--mount",
                              "--label", "--restart", "--user", "--userns",
                              "-e", "--env", "--entrypoint", "-p") or not args:
                reject()
            value = args.pop(0)
            if option == "--name":
                resource(value)
                named = True
            elif option == "--network":
                if value != "none":
                    resource(value)
                network = True
            elif option in ("-v", "--volume"):
                mount_source(value.split(":", 1)[0])
            elif option == "--mount":
                fields = dict(part.split("=", 1) for part in value.split(",") if "=" in part)
                source = fields.get("src", fields.get("source"))
                if source:
                    mount_source(source)
                elif fields.get("type") != "tmpfs":
                    reject()
        if not named or not network or not args or args[0] != "agent-sandbox:latest":
            reject()
        return
    if operation == "ps":
        # Never allow an unfiltered query or a regex matching other pilots.
        if (len(args) != 5 or args[0] != "--filter"
                or args[2:] != ["--filter", "status=running", "--quiet"]):
            reject()
        allowed_filters = {f"name=^{name}$" for name in registered}
        if args[1] not in allowed_filters:
            reject()
        return
    if operation == "port":
        if len(args) != 2 or args[1] != "22":
            reject()
        resource(args[0])
        return
    if operation not in ("exists", "inspect", "start", "stop", "restart", "rm", "kill"):
        reject()
    targets = []
    while args:
        arg = args.pop(0)
        if arg in ("--format", "-t", "--time"):
            if not args:
                reject()
            args.pop(0)
        elif arg in ("-f", "--ignore"):
            continue
        elif arg.startswith("-"):
            reject()
        else:
            resource(arg)
            targets.append(arg)
    if not targets:
        reject()


class TestPilotIsolation(unittest.TestCase):
    def test_guard_rejects_global_and_unregistered_resources(self):
        prefix = "asb-test-startupguard-12345678"
        cfg = {"prefix": prefix, "root": f"/tmp/{prefix}-state",
               "resources": [f"{prefix}-agent", f"{prefix}-keyring"]}
        for command in (
            ["podman", "rm", "-f", "asb-keyring"],
            ["podman", "volume", "inspect", "asb-credentials"],
            ["podman", "volume", "rm", "asb-toolcache"],
            ["podman", "inspect", "other-production-container"],
            ["podman", "stop", f"{prefix}-unregistered"],
            ["podman", "ps", "--filter", "name=^asb-keyring$", "--filter", "status=running", "--quiet"],
            ["podman", "ps"],
            ["systemctl", "--user", "stop", "asb-keyring.service"],
            ["podman", "run", "--name", f"{prefix}-keyring", "--network", "none",
             "-v", "asb-credentials:/run/asb-credentials:ro", "agent-sandbox:latest"],
            ["podman", "run", "--name", f"{prefix}-keyring", "--network", "none",
             "-v", "/etc:/mnt:ro", "agent-sandbox:latest"],
            ["podman", "pause", f"{prefix}-agent"],
            ["podman", "run", "--name", f"{prefix}-keyring", "--network", "none",
             "--mount", "type=volume,src=foreign-volume,dst=/run/asb-keyring", "agent-sandbox:latest"],
        ):
            with self.subTest(command=command), self.assertRaises(IsolationError):
                guard_podman(command, cfg)

    def test_guard_allows_registered_resources_and_real_transports(self):
        prefix = "asb-test-startupguard-12345678"
        cfg = {"prefix": prefix, "root": f"/tmp/{prefix}-state",
               "resources": [f"{prefix}-agent", f"{prefix}-keyring", f"{prefix}.target"]}
        for command in (
            ["podman", "image", "exists", "agent-sandbox:latest"],
            ["podman", "ps", "--filter", f"name=^{prefix}-agent$", "--filter", "status=running", "--quiet"],
            ["podman", "run", "--name", f"{prefix}-keyring", "--network", "none",
             "-v", f"{cfg['root']}/keyring.pass:/run/asb-keyring-pass:ro,Z", "agent-sandbox:latest"],
            ["systemctl", "--user", "start", f"{prefix}.target"],
            ["ssh", "-p", "2222", "v@127.0.0.1", "true"],
        ):
            with self.subTest(command=command):
                guard_podman(command, cfg)


def pilot_cli(state: Path, args: list[str]) -> int:
    """Process-local seams; host HOME and Podman storage stay unchanged."""
    cfg = json.loads(state.read_text())
    # These assertions run BEFORE any late patch can conceal import defaults.
    if any(os.environ.get(name) != value for name, value in cfg["env"].items()):
        raise IsolationError("Pilot environment must be set before Python imports")
    if (lifecycle.CONFIG != Path(cfg["env"]["ASB_CONFIG_ROOT"])
            or lifecycle.SSH_KEY != lifecycle.CONFIG / "id_ed25519"
            or lifecycle.CREDENTIALS_VOLUME != cfg["env"]["ASB_CREDENTIALS_VOLUME"]
            or keyring.CONFIG != lifecycle.CONFIG):
        raise IsolationError("ASB imported production defaults before pilot environment")
    real_expanduser = os.path.expanduser
    real_host = readiness.probe_host
    real_run = subprocess.run
    real_ensure = lifecycle.ensure_keyring_service

    def traced(command, *pos, **kw):
        if not isinstance(command, list):
            raise AssertionError("CLI subprocess must use an argument list")
        guard_podman(command, cfg)
        with Path(cfg["trace"]).open("a") as log:
            log.write(json.dumps(command) + "\n")
        return real_run(command, *pos, **kw)

    def ensure_then_fault(runtime_dir):
        real_ensure(runtime_dir)
        if Path(cfg["fault"]).read_text() == "keyring":
            # Real failure AFTER repair: readiness must detect the stopped service.
            run("podman", "stop", "-t", "1", cfg["env"]["ASB_KEYRING_CONTAINER"], check=True)

    def synthetic_verify(provider):
        if provider != "codex":
            raise AssertionError("Only the synthetic Codex edge is allowed")
        return "printf 'attempt\\n' >> /tmp/t1-verify-attempts; printf 'ASB_AUTH_VERIFY_OK\\n'"

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(os.path, "expanduser", side_effect=lambda p: cfg["home"] if p == "~" else real_expanduser(p)))
        mock_host = stack.enter_context(mock.patch.object(readiness, "probe_host", side_effect=lambda **kw: real_host(cfg["host_target"], **kw)))
        stack.enter_context(mock.patch.object(lifecycle, "ensure_keyring_service", side_effect=ensure_then_fault))
        stack.enter_context(mock.patch.object(auth, "_verify_command", side_effect=synthetic_verify))
        stack.enter_context(mock.patch.object(subprocess, "run", side_effect=traced))
        if args == ["setup-keyring"]:
            lifecycle.ensure_keyring_service(lifecycle.ensure_runtime(ROOT))
            return 0
        sys.argv = [str(ROOT / "cli/asb-agent"), *args]
        rc = runpy.run_path(str(ROOT / "cli/asb-agent"))["main"]()
        if "resume" in args:
            mock_host.assert_called()
        return rc


class Pilot(SandboxFixture):
    """Connect I1 resource ownership to lifecycle names and on-disk state."""

    def __init__(self, label):
        super().__init__(label, image="agent-sandbox:latest", port=22)
        self.container = f"{self._prefix}-agent"
        self.proxy = f"{self._prefix}-proxy"
        self.target = f"{self._prefix}.target"
        self.target_file = self._unit_dir / self.target
        self.home = self.state_root / "home"
        self.layout = layout_for(self.worktree_dir, self.workspace, self.home)
        self.proxy_data = self.state_root / "proxy"
        self.fault = self.state_root / "fault"
        self.trace = self.state_root / "commands.jsonl"
        self.settings = self.state_root / "pilot.json"
        self.control = None

    def setup_container(self):
        self.layout.state.mkdir(parents=True)
        self.layout.project_root.mkdir(parents=True)
        (self.layout.project_root / "preserve.txt").write_text("dados preservados\n")
        (self.layout.state / "origin").write_text(str(self.worktree_dir))
        (self.layout.state / "runtime.json").write_text(json.dumps({
            "schemaVersion": 1, "runtime_type": "systemd",
            "containers": {"agent": {"name": self.container, "unit": self.unit}},
        }))
        self.proxy_data.mkdir()
        (self.proxy_data / "status").write_text("200")
        self.fault.write_text("")
        self.register_network(self.net_internal)
        run("podman", "network", "create", "--internal", self.net_internal, check=True)
        self.register_container(self.proxy)
        run("podman", "run", "-d", "--name", self.proxy, "--pull=never",
            "--network", self.net_internal, "--entrypoint", "python3",
            "-v", f"{self.proxy_data}:/pilot:Z", self._image, "-c", PROXY, check=True)
        cred = self._credentials_mountpoint()
        mounts = []
        for provider in ("claude", "codex"):
            (cred / provider).mkdir(mode=0o700)
            mounts += ["--mount", f"type=volume,src={self.credentials_volume},dst=/home/{getpass.getuser()}/.{provider},volume-subpath={provider}"]
        self.register_container(self.container)
        run("podman", "create", "--name", self.container, "--pull=never",
            "--network", self.net_internal, "--userns", "keep-id:uid=1000,gid=1000",
            "-p", "127.0.0.1::22", "-e", f"ORCA_SSH_PUBLIC_KEY={self.ssh_key.with_suffix('.pub').read_text().strip()}",
            "-v", f"{self.layout.project_root}:/pilot-project:Z",
            *mounts, self._image, check=True)
        self.control = socketserver.ThreadingTCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler)
        threading.Thread(target=self.control.serve_forever, daemon=True).start()
        self.xdg_config = self.state_root / "xdg_config"
        asb_cfg = self.xdg_config / "agent-sandbox"
        asb_cfg.mkdir(parents=True)
        (asb_cfg / "id_ed25519").write_bytes(self.ssh_key.read_bytes())
        (asb_cfg / "id_ed25519").chmod(0o600)
        (asb_cfg / "id_ed25519.pub").write_bytes(self.ssh_key.with_suffix(".pub").read_bytes())
        self.cli_env = {
            "ASB_CREDENTIALS_VOLUME": self.credentials_volume,
            "ASB_TOOLCACHE_VOLUME": self.toolcache_volume,
            "ASB_KEYRING_CONTAINER": self.keyring_container,
            "ASB_KEYRING_RUNTIME_VOLUME": self.keyring_runtime_volume,
            "ASB_KEYRING_DATA_VOLUME": self.keyring_data_volume,
            "ASB_KEYRING_PASS_FILE": str(self.passphrase_file),
            "ASB_CONFIG_ROOT": str(self.config_dir),
            "ASB_NETWORK_UNIT": self.network_unit,
            "ASB_NETWORK_GATE_TARGET": f"127.0.0.1:{self.control.server_address[1]}",
            "XDG_CONFIG_HOME": str(self.xdg_config),
        }
        self.register_container(self.keyring_container)
        self.register_unit(self.unit)
        self.register_unit(self.target)
        self.settings.write_text(json.dumps({"env": self.cli_env, "home": str(self.home),
            "prefix": self._prefix, "root": str(self.state_root),
            "resources": sorted(self._registered_containers | self._registered_volumes | self._registered_networks | self._registered_units),
            "host_target": f"127.0.0.1:{self.control.server_address[1]}",
            "fault": str(self.fault), "trace": str(self.trace)}))
        result = self.cli("setup-keyring")
        if result.returncode:
            raise AssertionError(result.stderr)

    def install_unit(self):
        super().install_unit()
        self.register_unit(self.target)
        self.target_file.write_text(f"[Unit]\nDescription=T1 isolated pilot\nWants={self.unit}\nAfter={self.unit}\n[Install]\nWantedBy=default.target\n")
        run("systemctl", "--user", "daemon-reload", check=True)

    def cli(self, *args):
        return run(sys.executable, "-B", str(Path(__file__).resolve()), "--pilot-cli", str(self.settings), *args,
                   env={**os.environ, **self.cli_env})

    def start(self):
        super().start()
        if not self.wait_active():
            raise AssertionError("pilot did not start")
        result = readiness.wait_until(lambda to: readiness.probe_ssh(self.inspect_identity()[1], key=self.ssh_key, timeout=to), timeout=20)
        if result.state != "healthy":
            raise AssertionError(result)

    def ssh(self, command):
        return run("ssh", "-p", str(self.inspect_identity()[1]), "-i", str(self.ssh_key),
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            f"{getpass.getuser()}@127.0.0.1", command)

    def break_proxy(self, status=403):
        super().break_proxy()
        (self.proxy_data / "status").write_text(str(status))
        run("podman", "start", self.proxy, check=True)

    def teardown(self):
        if self._cleaned_up:
            return
        run("systemctl", "--user", "disable", "--now", self.target)
        self.target_file.unlink(missing_ok=True)
        if self.control:
            self.control.shutdown()
            self.control.server_close()
        super().teardown()


class TestStartupAuth(unittest.TestCase):
    @contextlib.contextmanager
    def pilot(self, label):
        sandbox = Pilot(f"startup{label}")
        try:
            with sandbox:
                sandbox.start()
                yield sandbox
        finally:
            # Deliberately AFTER __exit__, including failed-test paths.
            for command in (
                ["podman", "ps", "-a", "--filter", f"name=^{sandbox._prefix}[.-]", "--format", "{{.Names}}"],
                ["podman", "volume", "ls", "--filter", f"name=^{sandbox._prefix}[.-]", "--format", "{{.Name}}"],
                ["podman", "network", "ls", "--filter", f"name=^{sandbox._prefix}[.-]", "--format", "{{.Name}}"],
            ):
                self.assertEqual(run(*command, check=True).stdout.strip(), "", command)
            self.assertFalse(sandbox.state_root.exists())
            self.assertFalse(sandbox._unit_file.exists())
            self.assertFalse(sandbox.target_file.exists())

    def assert_preserved(self, sandbox, identity):
        self.assertEqual(sandbox.inspect_identity(), identity)
        self.assertEqual((sandbox.layout.project_root / "preserve.txt").read_text(), "dados preservados\n")
        self.assertTrue(sandbox.worktree_exists())
        self.assertTrue(sandbox.is_container_running())

    def test_systemd_resume_failures_never_emit_connection(self):
        for label, status, expected in (("403", 403, "connect_denied"), ("503", 503, "connect_failed"), ("keyring", 200, "keyring_stopped")):
            with self.subTest(label=label), self.pilot(label) as sandbox:
                identity = sandbox.inspect_identity()
                sandbox.break_proxy(status)
                if label == "keyring":
                    sandbox.fault.write_text("keyring")
                sandbox.trace.write_text("")
                result = sandbox.cli("resume", "--workspace", sandbox.workspace)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn(expected, result.stderr)
                self.assert_preserved(sandbox, identity)
                commands = [json.loads(line) for line in sandbox.trace.read_text().splitlines()]
                for command in (["systemctl", "--user", "enable", sandbox.target],
                                ["systemctl", "--user", "reset-failed", sandbox.target, sandbox.unit],
                                ["systemctl", "--user", "start", sandbox.target]):
                    self.assertIn(command, commands)
                self.assertEqual(run("systemctl", "--user", "is-active", sandbox.target).stdout.strip(), "active")
                self.assertTrue((sandbox.proxy_data / "requests").read_text().startswith("CONNECT github.com:443"))

    def test_absent_account_keeps_real_ssh_usable(self):
        with self.pilot("account") as sandbox:
            self.assertEqual(list(sandbox._credentials_mountpoint().joinpath("codex").iterdir()), [])
            resumed = sandbox.cli("resume", "--workspace", sandbox.workspace)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["port"], sandbox.inspect_identity()[1])
            result = sandbox.cli("auth", "status", "--workspace", sandbox.workspace, "--agent", "codex", "--json")
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["results"][0]["state"], "unauthenticated")
            ssh = sandbox.ssh("printf 'SSH_WITHOUT_ACCOUNT\\n'")
            self.assertEqual(ssh.returncode, 0, ssh.stderr)
            self.assertEqual(ssh.stdout, "SSH_WITHOUT_ACCOUNT\n")

    def test_verify_real_gates_ssh_and_exactly_one_synthetic_attempt(self):
        with self.pilot("verify") as sandbox:
            # The agent cannot reach a provider directly; the synthetic proxy
            # only writes HTTP responses and never opens an upstream socket.
            routes = sandbox.exec("cat", "/proc/net/route", check=True).stdout
            self.assertNotIn("00000000", [line.split()[1] for line in routes.splitlines()[1:]])
            sandbox.break_proxy(403)
            blocked = sandbox.cli("auth", "verify", "--workspace", sandbox.workspace, "--agent", "codex", "--json")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(json.loads(blocked.stdout)["callBudget"], {"codex": 0})
            self.assertNotEqual(sandbox.ssh("test -e /tmp/t1-verify-attempts").returncode, 0)
            sandbox.break_proxy(200)
            result = sandbox.cli("auth", "verify", "--workspace", sandbox.workspace, "--agent", "codex", "--json")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["callBudget"], {"codex": 1})
            self.assertEqual(report["results"][0]["state"], "authenticated")
            self.assertEqual(sandbox.ssh("cat /tmp/t1-verify-attempts").stdout, "attempt\n")

    def test_up_refuses_existing_workspace_and_preserves_resources(self):
        with self.pilot("upexist") as sandbox:
            identity = sandbox.inspect_identity()
            sandbox.trace.write_text("")
            result = sandbox.cli("up", "--workspace", sandbox.workspace, "--repo", str(sandbox.worktree_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace ja existe", result.stderr)
            self.assert_preserved(sandbox, identity)
            self.assertTrue(lifecycle.podman.exists("network", sandbox.net_internal))
            self.assertTrue(lifecycle.podman.exists("volume", sandbox.credentials_volume))
            commands = [json.loads(line) for line in sandbox.trace.read_text().splitlines()]
            for cmd in commands:
                self.assertNotIn("rm", cmd)
                self.assertNotIn("kill", cmd)

    def test_workspace_transaction_rollback_is_existing_defensive_contract(self):
        """Defensive unit contract for WorkspaceTransaction(is_existing=True).

        Production lifecycle.up() rejects existing workspaces before creating
        a transaction; this test verifies the transaction helper's internal safety
        contract directly when is_existing is True.
        """
        with self.pilot("txdef") as sandbox:
            identity = sandbox.inspect_identity()
            tx = lifecycle.WorkspaceTransaction(sandbox.workspace, is_existing=lifecycle.podman.exists("container", sandbox.container))
            self.assertTrue(tx.is_existing)
            tx.record_container(identity[0])
            tx.record_network(sandbox.net_internal)
            tx.record_volume(sandbox.credentials_volume)
            sandbox.break_proxy(503)
            result = sandbox.cli("resume", "--workspace", sandbox.workspace)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("connect_failed", result.stderr)
            tx.rollback()
            self.assert_preserved(sandbox, identity)
            self.assertTrue(lifecycle.podman.exists("network", sandbox.net_internal))
            self.assertTrue(lifecycle.podman.exists("volume", sandbox.credentials_volume))

    def test_busy_login_lock_uses_isolated_config(self):
        with self.pilot("lock") as sandbox, mock.patch.object(keyring, "CONFIG", sandbox.config_dir):
            with auth.operator_lock("claude"):
                with self.assertRaises(auth.LoginBusy):
                    with auth.operator_lock("claude"):
                        pass

    def test_recipe_resume_reads_cli_json_and_suppresses_failure(self):
        with self.pilot("recipe") as sandbox:
            # Copy production caller verbatim and replace only its CLI executable.
            recipe_root = sandbox.state_root / "recipe"
            (recipe_root / "recipes").mkdir(parents=True)
            (recipe_root / "cli").mkdir()
            for name in ("common.sh", "resume.sh"):
                (recipe_root / "recipes" / name).write_bytes((ROOT / "recipes" / name).read_bytes())
            stub = recipe_root / "cli/asb-agent"
            stub.write_text("#!/usr/bin/env bash\nexec " + shlex.join([sys.executable, "-B", str(Path(__file__).resolve()), "--pilot-cli", str(sandbox.settings)]) + ' "$@"\n')
            stub.chmod(0o755)
            payload = json.dumps({"recipeResult": {"userData": {"workspace": sandbox.workspace}}})
            result = run("bash", str(recipe_root / "recipes/resume.sh"), input=payload,
                         env={**os.environ, **sandbox.cli_env})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["userData"]["workspace"], sandbox.workspace)
            self.assertEqual(report["connection"]["projectRoot"], str(sandbox.layout.project_root))
            self.assertEqual(report["connection"]["type"], "ssh")
            self.assertEqual(report["connection"]["target"]["host"], "127.0.0.1")
            self.assertEqual(report["connection"]["target"]["port"], sandbox.inspect_identity()[1])
            self.assertTrue(report["connection"]["target"]["identitiesOnly"])
            self.assertEqual(report["connection"]["target"]["username"], getpass.getuser())
            self.assertNotIn("pairingCode", report)

            # Assert identityFile belongs to isolated pilot root and not production config
            target = report["connection"]["target"]
            expected_key = sandbox.xdg_config / "agent-sandbox/id_ed25519"
            self.assertEqual(target["identityFile"], str(expected_key))
            self.assertTrue(Path(target["identityFile"]).is_relative_to(sandbox.state_root))
            self.assertFalse(Path(target["identityFile"]).is_relative_to(Path.home() / ".config"))

            # Execute real OpenSSH command using ONLY the connection fields from the emitted JSON
            ssh_result = run(
                "ssh",
                "-p", str(target["port"]),
                "-i", target["identityFile"],
                "-o", f"IdentitiesOnly={'yes' if target['identitiesOnly'] else 'no'}",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                f"{target['username']}@{target['host']}",
                "printf 'SSH_FROM_RECIPE_JSON\\n'",
            )
            self.assertEqual(ssh_result.returncode, 0, ssh_result.stderr)
            self.assertEqual(ssh_result.stdout, "SSH_FROM_RECIPE_JSON\n")

            sandbox.break_proxy(403)
            failed = run("bash", str(recipe_root / "recipes/resume.sh"), input=payload,
                         env={**os.environ, **sandbox.cli_env})
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, "")
            self.assertIn("connect_denied", failed.stderr)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pilot-cli":
        sys.exit(pilot_cli(Path(sys.argv[2]), sys.argv[3:]))
    unittest.main()
