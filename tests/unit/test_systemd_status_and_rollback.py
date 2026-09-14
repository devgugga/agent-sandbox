"""tests/unit/test_systemd_status_and_rollback.py — prisoner tests do contrato systemd da adocao (I6).

`FakeHost` simula o manager `systemd --user` e o podman no nivel de
`subprocess.run`: o supervisor emite os mesmos comandos que emitiria no host e
o teste observa o que aconteceu (estado das units e dos containers, e a lista
ordenada de mutacoes), nao a fiacao de chamadas internas. As outras suites de
I6 importam `FakeHost` daqui.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import install, readiness, supervisor  # noqa: E402

WS = "demo"
KEYRING = "asb-test-kr"
JOURNALS = ("journal.json", "keyring-journal.json")


def _listdir_raising_on(alvo: Path):
    """`os.listdir` que levanta EACCES so no caminho pedido, e delega o resto.

    Injetar o erro em vez de provoca-lo por `chmod(0o000)` mantem o ramo
    coberto em qualquer ambiente, root inclusive.
    """
    real = os.listdir

    def listdir(path, *a, **kw):
        if Path(path) == alvo:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *a, **kw)

    return listdir



class FakeHost:
    """Manager systemd --user + podman simulados, com registro de mutacoes."""

    MUTATING_SYSTEMCTL = {"daemon-reload", "enable", "disable", "start", "stop", "reset-failed"}
    MUTATING_PODMAN = {"update", "start", "stop", "restart", "rm", "create", "run", "kill"}

    def __init__(self, search_path: list[Path]) -> None:
        self.search_path = list(search_path)
        self.loaded: dict[str, Path | None] = {}
        self.config: dict[str, list[str]] = {}
        self.enabled: dict[str, set[str]] = {}
        self.active: dict[str, str] = {}
        self.containers: dict[str, dict] = {}
        self.events: list[tuple] = []
        self.mutations = 0
        self.swap_after: tuple[int, str] | None = None
        self.swapped_at: int | None = None
        self.responses: dict[tuple, tuple[int, str, str]] = {}
        self.runtime = mock.Mock()
        self.probe = mock.Mock()
        self.probe_result = readiness.ProbeResult("keyring", "healthy", "ok", 1, "")
        self.crash_at_phase: str | None = None
        self.inert_starts: set[str] = set()  # start que ativa so a unit, sem puxar Wants=
        self.readiness_rc = 0  # exit code do runtime_check.py (sonda de prontidao do workspace)
        self.readiness_calls: list[list[str]] = []
        self.wait_until_calls: list[float] = []
        self._next_id = 0

    # --- construcao do estado -------------------------------------------
    def add_container(self, name: str, *, role: str | None, ws: str | None = WS,
                      running: bool = True, policy: str = "unless-stopped") -> None:
        # `role=None` cria container SEM label algum: e a classe de produtor de
        # netns que a contagem por `asb.workspace=` nunca enxergava.
        labels = {} if role is None else {"asb.role": role}
        if ws is not None:
            labels["asb.workspace"] = ws
        self.containers[name] = {
            "id": self._new_id(name), "labels": labels, "running": running,
            "policy": policy, "retry": 0,
        }

    def swap(self, name: str) -> None:
        """Container recriado por fora com o mesmo nome: ID novo, estado de fabrica."""
        c = self.containers[name]
        c.update(id=self._new_id(name), running=False, policy="unless-stopped", retry=0)

    def respond(self, argv: tuple, rc: int, out: str = "", err: str = "") -> None:
        """Resposta injetada para um comando exato (sem o binario)."""
        self.responses[argv] = (rc, out, err)

    def _new_id(self, name: str) -> str:
        self._next_id += 1
        return f"{name}-id{self._next_id}".replace("-", "")[:40].ljust(40, "0")

    # --- instalacao -------------------------------------------------------
    @contextlib.contextmanager
    def installed(self, runtime_dir: Path):
        real_write = supervisor._atomic_write_text

        def write(path, content, *args, **kwargs):
            journal = Path(path).name in JOURNALS
            if not journal:
                self._before_mutation(("write", str(path)))
            real_write(path, content, *args, **kwargs)
            if not journal:
                self._after_mutation()
            elif self.crash_at_phase and json.loads(content).get("phase") == self.crash_at_phase:
                # Morte do processo logo apos o checkpoint: SystemExit nao e
                # capturado pelo `except Exception` da adocao, logo nao ha
                # rollback automatico — o estado fica como num crash real.
                raise SystemExit(42)

        def single_shot(check, timeout):
            # Observavel de proposito: um patch sem asserção e decoracao, nao
            # mock (R7). Este aqui e load-bearing — sem ele, o caminho de sonda
            # permanentemente falha ficaria girando ate o timeout real de 10s.
            self.wait_until_calls.append(timeout)
            return check(timeout)

        self.runtime.return_value = (runtime_dir / "launcher.sh", runtime_dir / "runtime_check.py", "rev")
        self.probe.return_value = self.probe_result
        patches = [
            mock.patch("subprocess.run", side_effect=self.run),
            mock.patch.object(supervisor, "_atomic_write_text", side_effect=write),
            mock.patch.object(supervisor, "_resolve_versioned_runtime", self.runtime),
            mock.patch.object(readiness, "probe_keyring", self.probe),
            mock.patch.object(readiness, "wait_until", side_effect=single_shot),
        ]
        # Sem `hasattr`: o patch e INCONDICIONAL de proposito (R7). Guardado por
        # `hasattr`, o dia em que a producao renomeasse ou inlinasse
        # `_remove_file` o patch simplesmente nao seria instalado, os `unlink`
        # parariam de entrar em `self.mutations` e a varredura de
        # `test_id_swap_protection.py` — que deriva as posicoes de injecao de
        # `host.mutations` — perderia em silencio TODA posicao de remocao de
        # arquivo, com a suite inteira verde. Incondicional, o mesmo dia produz
        # `AttributeError` no momento do patch: falha alta em vez de perda
        # silenciosa de cobertura.
        real_remove = supervisor._remove_file

        def remove(path):
            self._before_mutation(("unlink", str(path)))
            real_remove(path)
            self._after_mutation()

        patches.append(mock.patch.object(supervisor, "_remove_file", side_effect=remove))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            yield self

    # --- registro de mutacoes ------------------------------------------------
    def _before_mutation(self, event: tuple) -> None:
        self.events.append(event)

    def _after_mutation(self) -> None:
        self.mutations += 1
        if self.swap_after and self.mutations == self.swap_after[0] and self.swapped_at is None:
            self.swap(self.swap_after[1])
            self.swapped_at = len(self.events)

    def mutations_after_swap(self) -> list[tuple]:
        return [] if self.swapped_at is None else self.events[self.swapped_at:]

    def mutation_events(self) -> list[tuple]:
        return list(self.events)

    # --- subprocess.run ---------------------------------------------------
    def run(self, argv, *args, **kwargs):
        argv = [str(a) for a in argv]
        binary = Path(argv[0]).name
        if binary == "systemctl":
            assert argv[1] == "--user", argv
            rc, out, err = self._systemctl(argv[2:])
        elif binary == "podman":
            rc, out, err = self._podman(argv[1:])
        elif binary == "systemd-analyze":
            rc, out, err = 0, "", ""
        elif len(argv) > 1 and Path(argv[1]).name == "runtime_check.py":
            self.readiness_calls.append(argv[2:])
            if self.readiness_rc == "timeout":
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            rc, out, err = self.readiness_rc, "", "" if self.readiness_rc == 0 else "sonda falhou"
        else:
            raise AssertionError(f"comando inesperado no FakeHost: {argv}")
        if kwargs.get("check") and rc != 0:
            raise subprocess.CalledProcessError(rc, argv, out, err)
        return subprocess.CompletedProcess(argv, rc, out, err)

    def _find_file(self, unit: str) -> Path | None:
        for d in self.search_path:
            if (d / unit).is_file():
                return d / unit
        return None

    def _injected(self, key: tuple):
        return self.responses.get(key)

    def _systemctl(self, args: list[str]) -> tuple[int, str, str]:
        verb, rest = args[0], args[1:]
        units = [a for a in rest if not a.startswith("-")]
        flags = [a for a in rest if a.startswith("-")]
        key = ("systemctl", verb, *flags, *units)
        if verb in self.MUTATING_SYSTEMCTL:
            self._before_mutation(key)
            result = self._injected(key) or self._systemctl_mutate(verb, flags, units)
            if result[0] == 0:
                self._after_mutation()
            return result
        injected = self._injected(key)
        if injected:
            return injected
        if verb == "show":
            props = [a.split("=", 1)[1] for a in flags if a.startswith("--property=")]
            if props == ["UnitPath"]:
                return 0, " ".join(str(p) for p in self.search_path) + "\n", ""
            if props == ["FragmentPath"]:
                frag = self.loaded.get(units[0])
                return 0, f"{frag or ''}\n", ""
            if props == ["ExecStartPost"]:
                return 0, "", ""
            raise AssertionError(f"show nao emulado: {args}")
        unit = units[0]
        if verb == "is-enabled":
            scopes = self.enabled.get(unit)
            if scopes:
                return 0, ("enabled" if "persistent" in scopes else "enabled-runtime") + "\n", ""
            path = self._find_file(unit)
            if path is None:
                return 4, "not-found\n", ""
            return (1, "disabled\n", "") if "[Install]" in path.read_text() else (0, "static\n", "")
        if verb == "is-active":
            state = self.active.get(unit)
            if state == "active":
                return 0, "active\n", ""
            if state in ("failed", "activating"):
                return 3, f"{state}\n", ""
            return (3, "inactive\n", "") if unit in self.loaded else (4, "inactive\n", "")
        raise AssertionError(f"systemctl nao emulado: {args}")

    def _systemctl_mutate(self, verb: str, flags: list[str], units: list[str]) -> tuple[int, str, str]:
        if verb == "daemon-reload":
            loaded: dict[str, Path | None] = {}
            for d in reversed(self.search_path):
                if d.is_dir():
                    for f in d.iterdir():
                        if f.is_file():
                            loaded[f.name] = f
            for u in self.active:
                loaded.setdefault(u, None)
            self.loaded = loaded
            # Como o systemd real: a configuracao fica em cache ate o proximo reload.
            self.config = {u: (p.read_text().splitlines() if p else self.config.get(u, []))
                           for u, p in loaded.items()}
            return 0, "", ""
        if not units:
            raise AssertionError(f"systemctl {verb} sem unit: mutacao global do manager do operador")
        unit = units[0]
        scope = "runtime" if "--runtime" in flags else "persistent"
        if verb == "enable":
            path = self._find_file(unit)
            if path is None:
                return 1, "", f"Failed to enable unit: Unit {unit} does not exist"
            if "[Install]" not in path.read_text():
                return 0, "", "The unit files have no installation config"
            self.enabled.setdefault(unit, set()).add(scope)
            return 0, "", "Created symlink"
        if verb == "disable":
            if self._find_file(unit) is None and unit not in self.enabled:
                return 1, "", f"Failed to disable unit: Unit {unit} does not exist"
            self.enabled.get(unit, set()).discard(scope)
            if not self.enabled.get(unit):
                self.enabled.pop(unit, None)
            return 0, "", ""
        if verb == "start":
            if unit not in self.loaded or self.loaded[unit] is None:
                return 5, "", f"Failed to start {unit}: Unit {unit} not found."
            self._start(unit)
            return 0, "", ""
        if verb == "stop":
            if unit not in self.loaded and unit not in self.active:
                return 5, "", f"Failed to stop {unit}: Unit {unit} not loaded."
            self._stop(unit)
            return 0, "", ""
        if verb == "reset-failed":
            if unit not in self.loaded:
                return 1, "", f"Failed to reset failed state of unit {unit}: Unit {unit} not loaded."
            if self.active.get(unit) == "failed":
                del self.active[unit]
            return 0, "", ""
        raise AssertionError(verb)

    def _unit_lines(self, unit: str) -> list[str]:
        return self.config.get(unit, [])

    def _start(self, unit: str) -> None:
        self.active[unit] = "active"
        if unit in self.inert_starts:
            return
        for line in self._unit_lines(unit):
            if unit.endswith(".target") and line.startswith("Wants="):
                for dep in line.split("=", 1)[1].split():
                    if dep in self.loaded and self.loaded[dep] is not None:
                        self._start(dep)
            if line.startswith("ExecStart="):
                self.containers[line.split()[-1]]["running"] = True

    def _stop(self, unit: str) -> None:
        self.active.pop(unit, None)
        if unit.endswith(".target"):
            for other in list(self.active):
                if self.active.get(other) == "active" and f"PartOf={unit}" in self._unit_lines(other):
                    self._stop(other)
        for line in self._unit_lines(unit):
            if line.startswith("ExecStart="):
                self.containers[line.split()[-1]]["running"] = False

    def _container(self, ref: str) -> dict | None:
        if ref in self.containers:
            return self.containers[ref]
        for c in self.containers.values():
            if c["id"] == ref:
                return c
        return None

    def _podman(self, args: list[str]) -> tuple[int, str, str]:
        verb = args[0]
        key = ("podman", *args)
        if verb in self.MUTATING_PODMAN:
            self._before_mutation(key)
            result = self._injected(key) or self._podman_mutate(args)
            if result[0] == 0:
                self._after_mutation()
            return result
        injected = self._injected(key)
        if injected:
            return injected
        if verb in ("container", "volume", "network", "image") and args[1] == "exists":
            ok = verb == "container" and args[2] in self.containers
            return (0 if ok else 1), "", ""
        if verb == "ps":
            if args[:3] == ["ps", "-a", "--filter"] and args[3].startswith("label=asb.workspace="):
                ws = args[3].split("=", 2)[2]
                names = [n for n, c in self.containers.items() if c["labels"].get("asb.workspace") == ws]
                return 0, "\n".join(names) + "\n", ""
            if args[:3] == ["ps", "-a", "--format"] and "{{.Labels}}" in args[3]:
                # Inventario de produtores de netns: nomes e labels de TODOS os
                # containers, rodando ou parados.
                lines = [
                    "{}|{}".format(n, ",".join(f"{k}={v}" for k, v in c["labels"].items()))
                    for n, c in self.containers.items()
                ]
                return 0, ("\n".join(lines) + "\n") if lines else "", ""
            if args[:2] == ["ps", "--format"]:
                return 0, "", ""
            if args[1] == "--filter" and args[2].startswith("name=^"):
                c = self.containers.get(args[2][len("name=^"):-1])
                return 0, (c["id"] + "\n") if c and c["running"] else "", ""
        if verb in ("inspect", "container"):
            rest = args[1:] if verb == "inspect" else args[2:]
            ref, fmt = rest[0], rest[2]
            c = self._container(ref)
            if c is None:
                return 125, "", f"Error: no such container {ref}"
            if fmt == "{{.Id}}":
                return 0, c["id"] + "\n", ""
            if fmt == "{{.State.Running}}":
                return 0, ("true" if c["running"] else "false") + "\n", ""
            if fmt == "{{json .HostConfig.RestartPolicy}}":
                return 0, json.dumps({"Name": c["policy"], "MaximumRetryCount": c["retry"]}), ""
            if fmt == "{{json .}}":
                return 0, json.dumps({
                    "Id": c["id"],
                    "Config": {"Labels": c["labels"], "Image": "img"},
                    "State": {"Running": c["running"], "Status": "running" if c["running"] else "exited"},
                    "HostConfig": {"RestartPolicy": {"Name": c["policy"], "MaximumRetryCount": c["retry"]}},
                    "Mounts": [], "NetworkSettings": {"Ports": {}},
                }), ""
        raise AssertionError(f"podman nao emulado: {args}")

    def _podman_mutate(self, args: list[str]) -> tuple[int, str, str]:
        c = self._container(args[-1])
        if c is None:
            return 125, "", f"Error: no such container {args[-1]}"
        if args[0] == "update":
            policy = args[1].split("=", 1)[1]
            name, _, retry = policy.partition(":")
            c["policy"], c["retry"] = name, int(retry or 0)
        elif args[0] == "start":
            c["running"] = True
        elif args[0] == "stop":
            c["running"] = False
        else:
            raise AssertionError(f"mutacao podman proibida na adocao: {args}")
        return 0, "", ""


def env_for(tmp: Path, **extra: str) -> dict[str, str]:
    """Ambiente minimo: config/drop-in e keyring sinteticos, nada do operador."""
    env = {"ASB_CONFIG_ROOT": str(tmp / "config"), "ASB_KEYRING_CONTAINER": KEYRING}
    env.update(extra)
    return env


@contextlib.contextmanager
def clean_env(env: dict[str, str]):
    """Aplica `env` e remove seams herdados que mudariam as raizes."""
    with mock.patch.dict(os.environ, env):
        for name in ("ASB_STATE_ROOT", "ASB_SYSTEMD_UNIT_DIR"):
            if name not in env:
                os.environ.pop(name, None)
        yield


def workspace_host(tmp: Path, *, running: bool = True, shadow: Path | None = None):
    unit_dir = tmp / "units"
    unit_dir.mkdir(parents=True, exist_ok=True)
    search = [shadow, unit_dir] if shadow else [unit_dir]
    host = FakeHost(search)
    host.add_container(f"asb-{WS}-proxy", role="proxy", running=running)
    host.add_container(f"asb-{WS}-agent", role="agent", running=running)
    return host, unit_dir, tmp / "state" / WS


def keyring_host(tmp: Path, *, running: bool = True, with_dropin: bool = False):
    unit_dir = tmp / "units"
    unit_dir.mkdir(parents=True, exist_ok=True)
    if with_dropin:
        # Sem drop-in real, `prior_dropin["exists"]` e False e a adocao pula o
        # bloco inteiro de remocao — os dois `_verify_ids` soltos e o `verify=`
        # interno. Foi assim que a varredura de troca de ID deixou de cobrir
        # justamente o caminho do achado Spec 1 do gate.
        from asb.install import PROJECT_DROPIN_HEADER
        dropin = tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
    host = FakeHost([unit_dir])
    host.add_container(KEYRING, role="keyring", ws=None, running=running)
    return host, unit_dir, tmp / "state" / "keyring"


def adopt(host: FakeHost, tmp: Path, unit_dir: Path, state_dir: Path, **kw):
    with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
        return supervisor.adopt_workspace(WS, apply=True, target_dir=unit_dir, state_dir=state_dir, **kw)


def rollback(host: FakeHost, tmp: Path, unit_dir: Path, state_dir: Path):
    with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
        return supervisor.rollback_workspace(WS, target_dir=unit_dir, state_dir=state_dir)


def adopt_kr(host: FakeHost, tmp: Path, unit_dir: Path, state_dir: Path):
    with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
        return supervisor.adopt_keyring(apply=True, target_dir=unit_dir, state_dir=state_dir)


def rollback_kr(host: FakeHost, tmp: Path, unit_dir: Path, state_dir: Path):
    with clean_env(env_for(tmp)), host.installed(tmp / "rt"):
        return supervisor.rollback_keyring(target_dir=unit_dir, state_dir=state_dir)


class _TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class TestUnitStatusTable(unittest.TestCase):
    """S1: todo par (rc, stdout) aceito tem valor definido; qualquer outro falha fechado."""

    ENABLED = {
        (0, "enabled"): True, (0, "enabled-runtime"): True, (0, "static"): False,
        (1, "disabled"): False, (4, "not-found"): False,
    }
    ACTIVE = {(0, "active"): True, (3, "inactive"): False, (3, "failed"): False, (4, "inactive"): False}
    UNSUPPORTED_ENABLED = [
        (1, "linked"), (1, "linked-runtime"), (0, "alias"), (1, "masked"), (1, "masked-runtime"),
        (0, "indirect"), (0, "generated"), (0, "transient"), (1, "bad"), (0, "linked"),
        (0, "disabled"), (1, "enabled"), (3, "enabled"), (1, "not-found"), (4, ""),
    ]
    UNSUPPORTED_ACTIVE = [
        (0, "reloading"), (3, "activating"), (3, "deactivating"), (3, "maintenance"),
        (3, "refreshing"), (0, "inactive"), (3, "active"), (4, "failed"), (1, "inactive"), (3, ""),
    ]

    def _status(self, en: tuple[int, str], act: tuple[int, str], err: str = ""):
        responses = [
            subprocess.CompletedProcess([], en[0], en[1] + "\n", err),
            subprocess.CompletedProcess([], act[0], act[1] + "\n", ""),
        ]
        with mock.patch("subprocess.run", side_effect=responses) as run:
            try:
                return supervisor._systemd_unit_status("asb-demo.target")
            finally:
                self.assertGreaterEqual(run.call_count, 1)

    def test_every_supported_pair_maps_to_its_value(self) -> None:
        for en, en_value in self.ENABLED.items():
            for act, act_value in self.ACTIVE.items():
                with self.subTest(enabled=en, active=act):
                    self.assertEqual(self._status(en, act), (en_value, act_value))

    def test_every_unsupported_enabled_state_fails_closed(self) -> None:
        for en in self.UNSUPPORTED_ENABLED:
            with self.subTest(enabled=en), self.assertRaises(RuntimeError):
                self._status(en, (3, "inactive"))

    def test_every_unsupported_active_state_fails_closed(self) -> None:
        for act in self.UNSUPPORTED_ACTIVE:
            with self.subTest(active=act), self.assertRaises(RuntimeError):
                self._status((1, "disabled"), act)

    def test_stderr_on_a_known_pair_fails_closed(self) -> None:
        for err in ("Access denied", "Failed to connect to bus: Connection refused"):
            with self.subTest(err=err), self.assertRaises(RuntimeError) as cm:
                self._status((1, "disabled"), (3, "inactive"), err=err)
            self.assertIn(err, str(cm.exception))

    def test_stderr_on_is_active_fails_closed(self) -> None:
        responses = [
            subprocess.CompletedProcess([], 1, "disabled\n", ""),
            subprocess.CompletedProcess([], 3, "inactive\n", "Connection refused"),
        ]
        with mock.patch("subprocess.run", side_effect=responses) as run, self.assertRaises(RuntimeError):
            supervisor._systemd_unit_status("asb-demo.target")
        self.assertEqual(run.call_count, 2)


class TestManagerSeam(_TmpCase):
    """C3: a raiz das units precisa ser lida pelo manager; o keyring vem do container."""

    def test_unit_dir_env_seam_and_config_root_is_not_a_unit_root(self) -> None:
        with clean_env({"ASB_SYSTEMD_UNIT_DIR": str(self.tmp / "u"), "ASB_CONFIG_ROOT": str(self.tmp / "c")}):
            self.assertEqual(supervisor._resolve_paths(WS)[1], self.tmp / "u")
        with clean_env({"ASB_CONFIG_ROOT": str(self.tmp / "c")}):
            self.assertEqual(supervisor._resolve_paths(WS)[1], Path.home() / ".config" / "systemd" / "user")

    def test_unit_dir_outside_manager_search_path_refuses_before_any_write(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.search_path = [self.tmp / "elsewhere"]
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("search path", str(cm.exception))
        self.assertEqual(host.mutation_events(), [])
        self.assertEqual(list(unit_dir.iterdir()), [])

    def test_shadowed_fragment_refuses_before_enable_or_start(self) -> None:
        shadow = self.tmp / "shadow"
        shadow.mkdir()
        (shadow / f"asb-{WS}.target").write_text("[Unit]\nDescription=alheio\n")
        host, unit_dir, state_dir = workspace_host(self.tmp, shadow=shadow)
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("FragmentPath", str(cm.exception))
        verbs = [e[1] for e in host.mutation_events() if e[0] == "systemctl"]
        self.assertNotIn("enable", verbs)
        self.assertNotIn("start", verbs)
        self.assertFalse(any(e[0] == "podman" and e[1] == "update" for e in host.mutation_events()))

    def test_agent_unit_depends_on_the_keyring_named_by_the_container(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        adopt(host, self.tmp, unit_dir, state_dir)
        agent = (unit_dir / f"asb-{WS}-agent.service").read_text()
        self.assertIn(f"{KEYRING}.service", agent)
        self.assertNotIn("asb-keyring.service", agent)
        host.runtime.assert_called()

    def test_keyring_unit_is_named_after_its_container(self) -> None:
        host, unit_dir, state_dir = keyring_host(self.tmp)
        adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue((unit_dir / f"{KEYRING}.service").is_file())
        self.assertFalse((unit_dir / "asb-keyring.service").exists())
        for event in host.mutation_events():
            self.assertNotIn("asb-keyring.service", event)
        host.probe.assert_called()

    def test_dropin_is_resolved_under_config_root_not_under_unit_dir(self) -> None:
        from asb.install import PROJECT_DROPIN_HEADER
        body = PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n"
        live = self.tmp / "config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
        decoy = self.tmp / "units" / "podman-restart.service.d" / "agent-sandbox.conf"
        for p in (live, decoy):
            p.parent.mkdir(parents=True)
            p.write_text(body)
        host, unit_dir, state_dir = keyring_host(self.tmp)
        adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertFalse(live.exists())
        self.assertEqual(decoy.read_text(), body)


    def test_search_path_query_failure_refuses_before_any_write(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.respond(("systemctl", "show", "--property=UnitPath", "--value"), 1, "", "Failed to connect to bus")
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("search path", str(cm.exception))
        self.assertEqual(host.mutation_events(), [])
        self.assertFalse((state_dir / "journal.json").exists())
        self.assertEqual(list(unit_dir.iterdir()), [])

    def test_fragment_query_failure_stops_before_enable_or_start(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.respond(("systemctl", "show", "--property=FragmentPath", "--value", f"asb-{WS}.target"),
                     1, "", "Failed to get properties")
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("falha ao consultar FragmentPath", str(cm.exception))
        verbs = [e[1] for e in host.mutation_events() if e[0] == "systemctl"]
        self.assertIn("daemon-reload", verbs)
        self.assertNotIn("enable", verbs)
        self.assertNotIn("start", verbs)


class TestWorkspaceRollbackMutations(_TmpCase):
    """I2: toda mutacao systemd do rollback exige rc=0 e pos-condicao; nada e ignorado."""

    def _adopted(self):
        host, unit_dir, state_dir = workspace_host(self.tmp)
        res = adopt(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(res["phase"], "readiness_verified")
        return host, unit_dir, state_dir

    def _assert_journal_error(self, state_dir: Path, needle: str) -> None:
        journal = json.loads((state_dir / "journal.json").read_text())
        self.assertNotEqual(journal["phase"], "rolled_back")
        self.assertIn(needle, journal["error"]["message"])

    def test_rollback_restores_baseline_and_leaves_units_unloaded(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        rollback(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(list(unit_dir.iterdir()), [])
        self.assertEqual(host.enabled, {})
        self.assertEqual(host.active, {})
        for c in host.containers.values():
            self.assertEqual((c["policy"], c["running"]), ("unless-stopped", True))

    def test_disable_rc1_with_error_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        target = f"asb-{WS}.target"
        host.respond(("systemctl", "disable", target), 1, "", "Failed to disable unit: Access denied")
        with self.assertRaises(RuntimeError) as cm:
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertIn("Access denied", str(cm.exception))
        self.assertTrue((unit_dir / target).is_file(), "rollback seguiu adiante apos disable falho")
        self._assert_journal_error(state_dir, "Access denied")

    def test_disable_failure_after_successful_stop_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        unit = f"asb-{WS}-agent.service"
        host.enabled[unit] = {"persistent"}
        host.respond(("systemctl", "disable", unit), 1, "", "Failed to disable unit: Transaction is destructive")
        with self.assertRaises(RuntimeError):
            rollback(host, self.tmp, unit_dir, state_dir)
        # o stop do target ja parou a service (PartOf=); o disable dela falhou
        self.assertIn(("systemctl", "stop", f"asb-{WS}.target"), host.mutation_events())
        self.assertIn(("systemctl", "disable", unit), host.mutation_events())
        self.assertTrue((unit_dir / unit).is_file())

    def test_stop_failure_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        target = f"asb-{WS}.target"
        host.respond(("systemctl", "stop", target), 1, "", "Job failed")
        with self.assertRaises(RuntimeError):
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertTrue((unit_dir / target).is_file())

    def test_reset_failed_failure_is_not_ignored(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        unit = f"asb-{WS}-agent.service"
        host.active[unit] = "failed"
        host.respond(("systemctl", "reset-failed", unit), 1, "", "Access denied")
        with self.assertRaises(RuntimeError):
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertTrue((unit_dir / unit).is_file())

    def test_reset_failed_is_scoped_to_adopted_units(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        host.active[f"asb-{WS}-agent.service"] = "failed"
        rollback(host, self.tmp, unit_dir, state_dir)
        resets = [e for e in host.mutation_events() if e[:2] == ("systemctl", "reset-failed")]
        self.assertEqual(resets, [("systemctl", "reset-failed", f"asb-{WS}-agent.service")])

    def test_daemon_reload_failure_is_not_ignored(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        host.respond(("systemctl", "daemon-reload"), 1, "", "Access denied")
        with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertFalse(any(e[0] == "podman" for e in host.mutation_events()[-3:]))

    def test_auto_restarting_service_is_stopped_on_rollback(self) -> None:
        # Restart=always + ExecStartPost falho deixa a service `activating`
        # (auto-restart); o stop do target nao a alcanca, o rollback tem de para-la.
        host, unit_dir, state_dir = self._adopted()
        unit = f"asb-{WS}-agent.service"
        host.active[unit] = "activating"
        rollback(host, self.tmp, unit_dir, state_dir)
        self.assertIn(("systemctl", "stop", unit), host.mutation_events())
        self.assertEqual(host.active, {})

    def test_persistent_and_runtime_enablement_are_both_removed(self) -> None:
        # `asb-agent resume` habilita o target sem --runtime; o rollback tem de
        # remover as duas habilitacoes, senao o target volta no proximo login.
        host, unit_dir, state_dir = self._adopted()
        host.enabled[f"asb-{WS}.target"] = {"persistent", "runtime"}
        rollback(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(host.enabled, {})

    def test_enable_failure_while_restoring_baseline_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        target = f"asb-{WS}.target"
        (unit_dir / target).write_text("[Unit]\nDescription=pre\n[Install]\nWantedBy=default.target\n")
        host.loaded[target] = unit_dir / target
        host.enabled[target] = {"runtime"}
        adopt(host, self.tmp, unit_dir, state_dir)
        for key in (("systemctl", "enable", "--runtime", target), ("systemctl", "enable", target)):
            host.respond(key, 1, "", "Access denied")
        with self.assertRaises(RuntimeError) as cm:
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertIn("Access denied", str(cm.exception))
        self.assertIn(("write", str(unit_dir / target)), host.mutation_events())


    def test_stop_that_does_not_stop_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        adopt(host, self.tmp, unit_dir, state_dir)
        target = f"asb-{WS}.target"
        host.respond(("systemctl", "stop", target), 0, "", "")  # rc 0 sem efeito
        before = len(host.events)
        with self.assertRaises(RuntimeError) as cm:
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertIn("nao ficou inativa apos stop/reset-failed", str(cm.exception))
        self.assertEqual(host.events[before:].count(("systemctl", "stop", target)), 3)
        self.assertEqual(host.active.get(target), "active")

    def test_disable_that_does_not_disable_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        adopt(host, self.tmp, unit_dir, state_dir)
        target = f"asb-{WS}.target"
        host.respond(("systemctl", "disable", target), 0, "", "")  # rc 0 sem efeito
        with self.assertRaises(RuntimeError) as cm:
            rollback(host, self.tmp, unit_dir, state_dir)
        self.assertIn("continua habilitada apos disable", str(cm.exception))
        self.assertIn(target, host.enabled)


class TestAdoptionStart(_TmpCase):
    """O start da adocao prova supervisao: cada container que rodava ganha unit ativa."""

    def _start_hook(self, host: FakeHost, after) -> None:
        """Envolve FakeHost._start; o proprio _start recursivo passa pelo hook (atributo de instancia)."""
        real = host._start

        def start(unit: str) -> None:
            real(unit)
            after(unit)

        host._start = start

    def test_running_container_that_stops_after_start_is_refused(self) -> None:
        agent, agent_svc = f"asb-{WS}-agent", f"asb-{WS}-agent.service"
        cases = (("{ path=/launcher.sh ; code=exited ; status=1/FAILURE }", "ExecStartPost (status 1)"),
                 (None, "deveria estar em execucao apos adocao"))
        for i, (status, needle) in enumerate(cases):
            with self.subTest(status=status):
                tmp = self.tmp / f"case{i}"
                tmp.mkdir()
                host, unit_dir, state_dir = workspace_host(tmp)

                def died(unit: str, host=host) -> None:
                    if unit == agent_svc:  # ExecStartPost falhou: service em auto-restart, container parado
                        host.active[unit] = "activating"
                        host.containers[agent]["running"] = False

                self._start_hook(host, died)
                if status:
                    host.respond(("systemctl", "show", "--property=ExecStartPost", agent_svc), 0,
                                 f"ExecStartPost={status}\n", "")
                with self.assertRaises(RuntimeError) as cm:
                    adopt(host, tmp, unit_dir, state_dir)
                self.assertIn(needle, str(cm.exception))
                self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "rolled_back")
                self.assertTrue(host.containers[agent]["running"], "rollback deveria religar o agente")
                self.assertEqual(host.containers[agent]["policy"], "unless-stopped")

    def test_stopped_container_started_by_adoption_is_refused(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        agent = f"asb-{WS}-agent"
        host.containers[agent]["running"] = False  # estado misto valido: proxy rodando, agente parado

        def stray(unit: str) -> None:
            host.containers[agent]["running"] = True  # dependencia espuria religa o agente

        self._start_hook(host, stray)
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("deveria permanecer parado apos adocao", str(cm.exception))
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "rolled_back")
        self.assertFalse(host.containers[agent]["running"], "rollback deveria devolver o agente parado")

    def test_adoption_always_renders_and_runs_the_readiness_probe(self) -> None:
        """Ruling do operador: nao ha adocao de workspace sem prontidao provada."""
        host, unit_dir, state_dir = workspace_host(self.tmp)
        res = adopt(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(res["phase"], "readiness_verified")
        for role in ("proxy", "agent"):
            unit = (unit_dir / f"asb-{WS}-{role}.service").read_text()
            self.assertIn("ExecStartPost=", unit)
            self.assertIn(f"--role {role}", unit)
        self.assertEqual([c[:2] for c in host.readiness_calls], [["--role", "proxy"], ["--role", "agent"]])

    def test_keyring_identity_comes_from_baseline_when_env_is_absent(self) -> None:
        """R6: sem ASB_KEYRING_CONTAINER, "ausente" nao pode virar o keyring default.

        A suite inteira roda com a variavel definida; este e o unico teste que
        entra no ramo ausente, que e onde a adocao sobrescreveria o keyring
        real de um workspace criado com keyring proprio.
        """
        cases = (("kr-do-workspace", "asb-test-kr-proprio"), (None, "asb-keyring"))
        for i, (recorded, expected) in enumerate(cases):
            with self.subTest(recorded=recorded):
                tmp = self.tmp / f"env{i}"
                tmp.mkdir()
                host, unit_dir, state_dir = workspace_host(tmp)
                if recorded:
                    state_dir.mkdir(parents=True)
                    (state_dir / "runtime.json").write_text(json.dumps(
                        {"schemaVersion": 1, "workspace": WS, "keyring_container": expected}))
                env = {"ASB_CONFIG_ROOT": str(tmp / "config")}  # sem ASB_KEYRING_CONTAINER
                with mock.patch.dict(os.environ, env), host.installed(tmp / "rt"):
                    for name in ("ASB_STATE_ROOT", "ASB_SYSTEMD_UNIT_DIR", "ASB_KEYRING_CONTAINER"):
                        os.environ.pop(name, None)
                    supervisor.adopt_workspace(WS, apply=True, target_dir=unit_dir, state_dir=state_dir)
                manifest = json.loads((state_dir / "runtime.json").read_text())
                self.assertEqual(manifest["keyring_container"], expected)
                agent_unit = (unit_dir / f"asb-{WS}-agent.service").read_text()
                self.assertIn(f"{expected}.service", agent_unit)

    def test_stopped_proxy_is_not_wanted_by_the_agent_unit(self) -> None:
        """`wants_proxy=False`: o `Wants=` do agente omite o proxy, mas o `After=` mantem a ordem."""
        host, unit_dir, state_dir = workspace_host(self.tmp, running=False)
        adopt(host, self.tmp, unit_dir, state_dir)
        unit = (unit_dir / f"asb-{WS}-agent.service").read_text()
        wants = next(l for l in unit.splitlines() if l.startswith("Wants="))
        after = next(l for l in unit.splitlines() if l.startswith("After="))
        self.assertNotIn(f"asb-{WS}-proxy.service", wants)
        self.assertIn(f"asb-{WS}-proxy.service", after)

    def test_runtime_integrity_failure_aborts_before_any_mutation(self) -> None:
        """A fiacao adocao -> integridade do runtime, na direcao da falha.

        Os cenarios de integracao pelo CLI ja rodam `_resolve_versioned_runtime`
        de verdade; o que faltava era a integridade falhando NO MEIO da adocao.
        """
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.runtime.side_effect = RuntimeError("falha de integridade do runtime em /rt")
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("falha de integridade do runtime", str(cm.exception))
        host.runtime.assert_called_once()
        self.assertEqual(host.mutation_events(), [], "mutacao apesar da falha de integridade")
        self.assertFalse((state_dir / "journal.json").exists(), "diario gravado apesar da recusa")
        self.assertEqual(list(unit_dir.iterdir()), [])

    def test_corrupt_runtime_json_refuses_instead_of_defaulting_the_keyring(self) -> None:
        """R6 (rodada 4): presente e ilegivel nao e ausente.

        Cair no default aqui sobrescreveria o unico registro do keyring real do
        workspace e desviaria a sonda e o `After=`/`Wants=` da unit.
        """
        for i, corrupt in enumerate(("{nao-json", '"uma string"')):
            with self.subTest(corrupt=corrupt):
                tmp = self.tmp / f"corrupt{i}"
                tmp.mkdir()
                host, unit_dir, state_dir = workspace_host(tmp)
                state_dir.mkdir(parents=True)
                (state_dir / "runtime.json").write_text(corrupt)
                env = {"ASB_CONFIG_ROOT": str(tmp / "config")}  # sem ASB_KEYRING_CONTAINER
                with mock.patch.dict(os.environ, env), host.installed(tmp / "rt"):
                    for name in ("ASB_STATE_ROOT", "ASB_SYSTEMD_UNIT_DIR", "ASB_KEYRING_CONTAINER"):
                        os.environ.pop(name, None)
                    with self.assertRaises(RuntimeError) as cm:
                        supervisor.adopt_workspace(WS, apply=True, target_dir=unit_dir, state_dir=state_dir)
                self.assertIn("runtime.json", str(cm.exception))
                self.assertEqual(host.mutation_events(), [], "mutacao antes da recusa")
                self.assertEqual((state_dir / "runtime.json").read_text(), corrupt)
                self.assertEqual(list(unit_dir.iterdir()), [])

    def test_readiness_failure_blocks_readiness_verified(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.readiness_rc = 1
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("sonda de prontidao", str(cm.exception))
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "rolled_back")

    def test_enable_that_does_not_enable_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        target = f"asb-{WS}.target"
        host.respond(("systemctl", "enable", target), 0, "", "")  # rc 0 sem efeito
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("apos enable (esperado 'enabled')", str(cm.exception))
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "rolled_back")

    def test_already_active_target_is_started_again_to_pull_services(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        target = f"asb-{WS}.target"
        (unit_dir / target).write_text("[Unit]\nDescription=pre\n[Install]\nWantedBy=default.target\n")
        host._systemctl_mutate("daemon-reload", [], [])
        host.active[target] = "active"
        adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn(("systemctl", "start", target), host.mutation_events())
        for role in ("agent", "proxy"):
            self.assertEqual(host.active.get(f"asb-{WS}-{role}.service"), "active", role)

    def test_start_that_leaves_a_running_container_unsupervised_is_refused(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        host.inert_starts.add(f"asb-{WS}.target")
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("sem supervisao", str(cm.exception))
        self.assertEqual(json.loads((state_dir / "journal.json").read_text())["phase"], "rolled_back")
        self.assertEqual(list(unit_dir.iterdir()), [])


    def test_boot_started_container_under_its_unit_is_not_mistaken_for_a_bypass(self) -> None:
        """Ruling r13 revisado: rodar sob unit ativa e supervisao, nao bypass.

        O target lista todo o workspace em `Wants=` — `lifecycle.resume` depende
        disso para subir o workspace — e tem `WantedBy=default.target`, entao o
        systemd o ativa no boot seguinte e sobe tambem a unit de um container
        que a adocao deixou parado. Recusar a retomada ai acusaria o proprio
        manager de bypass externo. A distincao e a unit, nao o container.
        """
        host, unit_dir, state_dir = workspace_host(self.tmp)
        agent = f"asb-{WS}-agent"
        host.containers[agent]["running"] = False
        self.assertEqual(adopt(host, self.tmp, unit_dir, state_dir)["phase"], "readiness_verified")

        # Boot seguinte: o manager ativa o target, que puxa as Wants= inativas.
        host._start(f"asb-{WS}.target")
        self.assertTrue(host.containers[agent]["running"], "o dublê nao expandiu Wants=")
        self.assertEqual(host.active.get(f"{agent}.service"), "active")

        # A retomada tem de aceitar: o container roda SOB a propria unit.
        self.assertEqual(adopt(host, self.tmp, unit_dir, state_dir)["phase"], "readiness_verified")

    def test_unit_in_transition_refuses_with_the_accurate_diagnostic(self) -> None:
        """A janela do boot: `Type=exec` + `ExecStartPost` deixa a unit em `activating`.

        A sonda de prontidao roda no `ExecStartPost` (ate 95s no proxy, 60s no
        agente), entao por esse tempo o container ja roda enquanto a unit ainda
        ativa. O Task/Spec da rodada 7 previu que a checagem de supervisao
        acusaria o systemd de bypass nessa janela. Medido: **nao acusa** — o
        inventario chama `_systemd_unit_status`, que recusa estado transitorio
        antes, com o diagnostico certo ("nao ha baseline confiavel"). A recusa
        e correta e transitoria; o que nao pode acontecer e a mensagem culpar um
        bypass externo.
        """
        host, unit_dir, state_dir = workspace_host(self.tmp)
        agent = f"asb-{WS}-agent"
        host.containers[agent]["running"] = False
        adopt(host, self.tmp, unit_dir, state_dir)

        # Boot em curso: container de pe, unit ainda ativando.
        host.containers[agent]["running"] = True
        host.active[f"{agent}.service"] = "activating"
        before = len(host.events)
        with self.assertRaises(RuntimeError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("transitorio", str(cm.exception))
        self.assertNotIn("fora da supervisao", str(cm.exception))
        self.assertEqual(host.events[before:], [], "mutacao antes da recusa")

    def test_resuming_a_workspace_that_is_still_stopped_succeeds(self) -> None:
        """O ramo "continua parado": retomada legitima de adocao-parada.

        Se o `continue` por `not _is_container_running` sumisse ou invertesse,
        toda retomada de um workspace adotado parado — e corretamente ainda
        parado — passaria a ser recusada para sempre.
        """
        host, unit_dir, state_dir = workspace_host(self.tmp, running=False)
        host.crash_at_phase = "supervision_configured"
        with self.assertRaises(SystemExit):
            adopt(host, self.tmp, unit_dir, state_dir)
        host.crash_at_phase = None
        self.assertFalse(any(c["running"] for c in host.containers.values()))
        self.assertEqual(adopt(host, self.tmp, unit_dir, state_dir)["phase"],
                         "supervision_configured")

    def test_container_running_without_its_unit_is_refused_as_a_bypass(self) -> None:
        """O outro lado da mesma checagem: sem unit ativa, e bypass e recusa."""
        host, unit_dir, state_dir = workspace_host(self.tmp)
        agent = f"asb-{WS}-agent"
        host.containers[agent]["running"] = False
        adopt(host, self.tmp, unit_dir, state_dir)

        # `podman start` por fora: container de pe, unit parada.
        host.containers[agent]["running"] = True
        before = len(host.events)
        with self.assertRaises(ValueError) as cm:
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertIn("fora da supervisao", str(cm.exception))
        self.assertEqual(host.events[before:], [], "mutacao antes da recusa")


class TestKeyringRollbackMutations(_TmpCase):
    def _adopted(self):
        host, unit_dir, state_dir = keyring_host(self.tmp)
        res = adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(res["phase"], "readiness_verified")
        return host, unit_dir, state_dir

    def test_keyring_rollback_restores_baseline(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        rollback_kr(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(list(unit_dir.iterdir()), [])
        self.assertEqual((host.enabled, host.active), ({}, {}))
        self.assertEqual(host.containers[KEYRING]["policy"], "unless-stopped")

    def test_keyring_disable_rc1_with_error_is_not_accepted(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        unit = f"{KEYRING}.service"
        host.respond(("systemctl", "disable", "--runtime", unit), 1, "", "Access denied")
        host.respond(("systemctl", "disable", unit), 1, "", "Access denied")
        with self.assertRaises(RuntimeError):
            rollback_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue((unit_dir / unit).is_file())

    def test_keyring_reset_failed_failure_is_not_ignored(self) -> None:
        host, unit_dir, state_dir = self._adopted()
        unit = f"{KEYRING}.service"
        host.active[unit] = "failed"
        host.respond(("systemctl", "reset-failed", unit), 1, "", "Access denied")
        with self.assertRaises(RuntimeError):
            rollback_kr(host, self.tmp, unit_dir, state_dir)
        self.assertTrue((unit_dir / unit).is_file())


class TestRemoveWorkspaceUnits(_TmpCase):
    def test_wants_link_that_cannot_be_removed_is_an_error(self) -> None:
        """R6: um symlink de wants que sobra reabilita o target no proximo boot."""
        unit_dir = self.tmp / "units"
        wants = unit_dir / "default.target.wants"
        wants.mkdir(parents=True)
        link = wants / f"asb-{WS}.target"
        link.symlink_to(unit_dir / f"asb-{WS}.target")
        # EACCES INJETADO no unlink do link, em vez de `wants.chmod(0o500)`: o
        # bit de escrita nao se aplica a root, e sob root este teste falharia por
        # ambiente. Injetar cobre o ramo em qualquer euid.
        real_unlink = os.unlink

        def unlink_eacces(path, *a, **kw):
            if os.fspath(path) == os.fspath(link):
                raise PermissionError(13, "Permission denied", str(path))
            return real_unlink(path, *a, **kw)

        done = subprocess.CompletedProcess([], 0, "", "")
        with clean_env(env_for(self.tmp)), \
                mock.patch("os.unlink", side_effect=unlink_eacces) as desligado, \
                mock.patch("subprocess.run", return_value=done) as run:
            with self.assertRaises(PermissionError):
                supervisor.remove_workspace_units(WS, target_dir=unit_dir, state_dir=self.tmp / "state" / WS)
        # Injecao observada: o EACCES foi entregue no unlink DO LINK de wants.
        self.assertTrue([c for c in desligado.call_args_list if os.fspath(c.args[0]) == os.fspath(link)],
                        desligado.call_args_list)
        self.assertTrue(link.is_symlink())
        self.assertEqual([c.args[0][2] for c in run.call_args_list], ["stop", "disable"])


class TestAdoptionLock(_TmpCase):
    """I3: apply, dry-run e rollback disputam o mesmo flock no diretorio de estado."""

    @contextlib.contextmanager
    def _held(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def test_dry_run_refuses_while_state_dir_is_locked(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        with self._held(state_dir), clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            with self.assertRaises(RuntimeError) as cm:
                supervisor.adopt_workspace(WS, apply=False, target_dir=unit_dir, state_dir=state_dir)
        self.assertIn("lock", str(cm.exception))

    def test_dry_run_without_state_dir_creates_nothing(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            res = supervisor.adopt_workspace(WS, apply=False, target_dir=unit_dir, state_dir=state_dir)
        self.assertEqual(res["status"], "dry_run")
        self.assertFalse(state_dir.exists())
        self.assertEqual(host.mutation_events(), [])

    def test_apply_refuses_while_state_dir_is_locked(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        with self._held(state_dir), self.assertRaises(RuntimeError):
            adopt(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(host.mutation_events(), [])
        self.assertFalse((state_dir / "journal.json").exists())

    def test_keyring_dry_run_and_apply_refuse_while_locked(self) -> None:
        host, unit_dir, state_dir = keyring_host(self.tmp)
        with self._held(state_dir):
            with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"), self.assertRaises(RuntimeError):
                supervisor.adopt_keyring(apply=False, target_dir=unit_dir, state_dir=state_dir)
            with self.assertRaises(RuntimeError):
                adopt_kr(host, self.tmp, unit_dir, state_dir)
        self.assertEqual(host.mutation_events(), [])

    def test_lock_is_taken_before_inventory(self) -> None:
        host, unit_dir, state_dir = workspace_host(self.tmp)
        order: list[str] = []
        real_inspect = supervisor._inspect_workspace_containers
        real_flock = fcntl.flock

        def traced_flock(fd, op):
            order.append("lock")
            return real_flock(fd, op)

        def traced_inspect(ws):
            order.append("inventory")
            return real_inspect(ws)

        with mock.patch.object(supervisor, "_inspect_workspace_containers", side_effect=traced_inspect) as insp, \
                mock.patch.object(supervisor.fcntl, "flock", side_effect=traced_flock):
            adopt(host, self.tmp, unit_dir, state_dir)
        insp.assert_called()
        self.assertEqual(order[:2], ["lock", "inventory"])


class TestHelpers(unittest.TestCase):
    def test_format_restart_policy_arg(self) -> None:
        self.assertEqual(supervisor._format_restart_policy_arg("on-failure", 0), "--restart=on-failure")
        self.assertEqual(supervisor._format_restart_policy_arg("on-failure", 3), "--restart=on-failure:3")
        self.assertEqual(supervisor._format_restart_policy_arg("unless-stopped", 0), "--restart=unless-stopped")

    def test_verify_unit_files_failure_raises(self) -> None:
        res = subprocess.CompletedProcess([], 1, "", "asb-x.service:5: Unknown section 'Invalid'")
        with mock.patch("subprocess.run", return_value=res) as run, self.assertRaises(RuntimeError) as cm:
            supervisor._verify_unit_files([Path("/tmp/asb-x.service")])
        self.assertIn("Unknown section", str(cm.exception))
        run.assert_called_once()


class TestNetnsProducerInventory(_TmpCase):
    """Bloqueador 3 do gate: o inventario de produtores do namespace rootless.

    A versao anterior via uma coisa e meia: o drop-in DO PROJETO (por
    `is_file()`, que segue symlink) e uma contagem de workspaces derivada do
    label `asb.workspace=`. Ficavam de fora, por construcao, os drop-ins
    alheios, as unidades legadas e todo container sem aquele label — as tres
    classes que o controller nomeou.
    """

    def _config(self) -> Path:
        cfg = self.tmp / "config" / "systemd" / "user"
        (cfg / "podman-restart.service.d").mkdir(parents=True, exist_ok=True)
        return cfg

    def test_every_producer_class_is_inventoried_by_name(self) -> None:
        cfg = self._config()
        dropins = cfg / "podman-restart.service.d"
        (dropins / "agent-sandbox.conf").write_text(
            install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
        (dropins / "zz-terceiro.conf").write_text("[Service]\nEnvironment=X=1\n")
        alvo = self.tmp / "fora.conf"
        alvo.write_text("[Service]\n")
        (dropins / "link.conf").symlink_to(alvo)
        # Unidade legada de OUTRO workspace, e a deste, que nao entra.
        (cfg / "asb-legado.target").write_text("[Unit]\n")
        (cfg / "asb-outro-agent.service").write_text("[Unit]\n")
        (cfg / f"asb-{WS}.target").write_text("[Unit]\n")
        (cfg / f"asb-{WS}-agent.service").write_text("[Unit]\n")

        host, unit_dir, _ = workspace_host(self.tmp)
        host.add_container("vizinho-proxy", role="proxy", ws="outro-ws")
        host.add_container("container-alheio", role=None, ws=None)
        host.add_container("outro-alheio", role=None, ws=None, running=False)
        # `enable podman-restart.service` se registra como link de wants
        wants = cfg / "default.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        (wants / "podman-restart.service").symlink_to("/usr/lib/systemd/user/podman-restart.service")

        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._collect_diagnostics(WS)["rootless_netns_producers"]

        # 1. TODA entrada do `.d`, classificada — nossa, alheia e nao-regular.
        self.assertIn("dropin:agent-sandbox.conf(projeto)", producers)
        self.assertIn("dropin:zz-terceiro.conf(alheio)", producers)
        self.assertIn("dropin:link.conf(nao-regular)", producers)
        # 2. Unidades que sobem containers, legadas incluidas; a do workspace
        #    desta transacao nao e produtor "de fora" e fica de fora.
        self.assertIn("unit:podman-restart.service(habilitada em default.target.wants)", producers)
        self.assertIn("unit:asb-legado.target(legada ou de outro workspace)", producers)
        self.assertIn("unit:asb-outro-agent.service(legada ou de outro workspace)", producers)
        self.assertNotIn(f"unit:asb-{WS}.target(legada ou de outro workspace)", producers)
        self.assertNotIn(f"unit:asb-{WS}-agent.service(legada ou de outro workspace)", producers)
        # 3. Containers rotulados E nao rotulados; dois workspaces (demo e
        #    outro-ws) e dois containers sem label, um deles parado.
        self.assertIn("workspaces_rotulados:2", producers)
        self.assertIn("containers_sem_label:2", producers)
        # Nada do alvo do symlink foi lido nem seguido.
        self.assertEqual(alvo.read_text(), "[Service]\n")

    def test_foreign_dropin_alone_is_still_a_producer(self) -> None:
        """Sem drop-in nosso, um alheio no mesmo `.d` continua produzindo netns."""
        dropins = self._config() / "podman-restart.service.d"
        (dropins / "10-outro-projeto.conf").write_text("[Service]\nExecStartPre=/bin/true\n")
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("dropin:10-outro-projeto.conf(alheio)", producers)

    def test_symlinked_project_dropin_is_not_erased_from_the_inventory(self) -> None:
        """`is_file()` segue link e, num link pendurado, devolve False.

        Nos dois casos o nome do drop-in do projeto desaparecia do inventario,
        embora o systemd fosse ler o que estivesse ali.
        """
        dropins = self._config() / "podman-restart.service.d"
        (dropins / "agent-sandbox.conf").symlink_to(self.tmp / "nao-existe.conf")
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("dropin:agent-sandbox.conf(nao-regular)", producers)

    def test_container_query_failure_is_unknown_not_absence(self) -> None:
        """Fail-closed: nao saber e diferente de nao haver."""
        self._config()
        host, _, _ = workspace_host(self.tmp)
        host.respond(("podman", "ps", "-a", "--format", "{{.Names}}|{{.Labels}}"),
                     125, "", "Error: connection refused")
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("unknown: Error: connection refused", producers)
        self.assertFalse([q for q in producers if q.startswith("containers_sem_label")])

    def test_legacy_unit_without_the_wants_link_is_not_a_producer(self) -> None:
        """Sem link em `default.target.wants`, o podman-restart nao sobe no boot.

        O inventario le a habilitacao do disco em vez de perguntar ao manager:
        `is-enabled` alcancaria o manager do operador, que a guarda de
        isolamento proibe e que faria o resultado depender do host.
        """
        self._config()
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertFalse([q for q in producers if "podman-restart.service" in q], producers)

    def test_dangling_wants_link_still_counts_as_enabled(self) -> None:
        """Link pendurado continua sendo habilitacao registrada em disco.

        `exists()` seguiria o link e devolveria False; o systemd, no boot, ve o
        link e tenta puxar a unit. `is_symlink()` primeiro e o que impede o
        produtor de desaparecer do inventario.
        """
        cfg = self._config()
        wants = cfg / "default.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        (wants / "podman-restart.service").symlink_to(self.tmp / "nao-existe.service")
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("unit:podman-restart.service(habilitada em default.target.wants)", producers)



    def test_foreign_content_at_our_own_name_is_classified_alheio(self):
        """O lado `ours=False` do ternario `'projeto' if ours else 'alheio'`.

        Um arquivo alheio com o NOSSO nome exato e o unico input que alcanca
        esse lado: nome diferente sai por outro ramo, sem consultar autoria, e
        symlink morre no `S_ISREG` antes. Sem este teste, um mutante que
        cravasse `"projeto"` passava as seis outras checagens.
        """
        dropins = self._config() / "podman-restart.service.d"
        (dropins / "agent-sandbox.conf").write_text("[Service]\nEnvironment=DE_TERCEIRO=1\n")
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("dropin:agent-sandbox.conf(alheio)", producers)
        self.assertNotIn("dropin:agent-sandbox.conf(projeto)", producers)

    def test_unreadable_project_dropin_is_unknown_not_classified(self):
        """`read_project_dropin` levantando dentro do inventario.

        Ilegivel nao pode virar nem `(projeto)` nem `(alheio)`: o operador que
        le o diagnostico precisa saber que nao se sabe.
        """
        dropins = self._config() / "podman-restart.service.d"
        alvo = dropins / "agent-sandbox.conf"
        alvo.write_text(install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/bin/true\n")
        host, _, _ = workspace_host(self.tmp)
        # O erro e INJETADO, nao provocado por `chmod(0o000)`. Permissao nao se
        # aplica a root, entao um teste que dependesse dela ficaria verde sem
        # entrar no ramo sempre que a suite rodasse como root — nao-cobertura
        # invisivel, e justamente nestes ramos, que sao os unicos a provar a
        # distincao R6 entre "ausente" e "ilegivel".
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"), \
                mock.patch.object(supervisor.install, "read_project_dropin",
                                  side_effect=RuntimeError("drop-in ilegivel (EACCES)")) as leitura:
            producers = supervisor._netns_producers(WS)
        # Injecao OBSERVADA (test-shape.md, "Unasserted mocks"): sem isto, apagar
        # a chamada a `read_project_dropin` deixaria o teste verde.
        leitura.assert_called_once()
        # ESTREITADO: nomeia o caminho do drop-in, em vez de aceitar qualquer
        # `unknown: ... ilegivel`. Um `unknown:` vindo de outro ramo nao serve
        # como prova deste.
        self.assertTrue([q for q in producers if q.startswith(f"unknown: {alvo} ilegivel")],
                        producers)
        self.assertFalse([q for q in producers if q.startswith("dropin:agent-sandbox.conf(")],
                         producers)

    def test_absent_counts_are_omitted_not_reported_as_zero(self):
        """Os dois ramos de "nao ha nada a contar", discriminados por ausencia.

        Sem asserção de ausencia, um mutante que apagasse os dois `if` e
        emitisse sempre `containers_sem_label:0` e `workspaces_rotulados:0`
        sobreviveria — os testes que rodam com zero de cada um nunca olhavam.
        """
        self._config()
        host = FakeHost([self.tmp / "units"])  # NENHUM container: os dois lados vazios
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertFalse([q for q in producers if q.startswith("containers_sem_label")], producers)
        self.assertFalse([q for q in producers if q.startswith("workspaces_rotulados")], producers)

    def test_unlabelled_absent_while_labelled_present_omits_only_the_empty_one(self):
        """Um lado vazio e o outro nao: so o vazio e omitido."""
        self._config()
        host, _, _ = workspace_host(self.tmp)  # dois containers, ambos rotulados
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertIn("workspaces_rotulados:1", producers)
        self.assertFalse([q for q in producers if q.startswith("containers_sem_label")], producers)

    def test_missing_and_unreadable_dropin_dir_are_distinguished(self):
        """Diretorio ausente nao produz marcador; ilegivel produz `unknown:`."""
        # (a) ausente: nenhuma raiz de config criada
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"):
            producers = supervisor._netns_producers(WS)
        self.assertFalse([q for q in producers if "ilegivel" in q], producers)
        self.assertFalse([q for q in producers if q.startswith("dropin:")], producers)
        # Espaco negativo: ausencia nao pode produzir marcador algum de `unknown:`.
        self.assertFalse([q for q in producers if q.startswith("unknown:")], producers)

        # (b) ilegivel: o `listdir` do diretorio do drop-in levanta EACCES
        dropins = self._config() / "podman-restart.service.d"
        (dropins / "agent-sandbox.conf").write_text("[Service]\nExecStartPre=/bin/true\n")
        host2, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host2.installed(self.tmp / "rt"), \
                mock.patch("os.listdir", side_effect=_listdir_raising_on(dropins)) as listado:
            producers2 = supervisor._netns_producers(WS)
        # Injecao observada, e dirigida ao diretorio certo.
        self.assertTrue([c for c in listado.call_args_list if Path(c.args[0]) == dropins],
                        listado.call_args_list)
        # ESTREITADO: nomeia o diretorio, nao "qualquer unknown ilegivel".
        self.assertTrue([q for q in producers2 if q.startswith(f"unknown: {dropins} ilegivel")],
                        producers2)

    def test_unreadable_unit_root_is_unknown(self):
        """Raiz de units ilegivel entra como `unknown:`, nao como "sem units"."""
        cfg = self._config()
        (cfg / "asb-legado.target").write_text("[Unit]\n")
        host, _, _ = workspace_host(self.tmp)
        with clean_env(env_for(self.tmp)), host.installed(self.tmp / "rt"), \
                mock.patch("os.listdir", side_effect=_listdir_raising_on(cfg)) as listado:
            producers = supervisor._netns_producers(WS)
        self.assertTrue([c for c in listado.call_args_list if Path(c.args[0]) == cfg],
                        listado.call_args_list)
        # Nomeia a raiz: uma asserção generica de `unknown:` seria satisfeita por
        # qualquer um dos tres ramos que a versao anterior (com `chmod(0o000)` no
        # ancestral) disparava de uma vez. Com a injecao dirigida a `cfg`, so este
        # ramo dispara — e a mensagem prova qual foi.
        self.assertTrue([q for q in producers if q.startswith(f"unknown: {cfg} ilegivel")],
                        producers)

if __name__ == "__main__":
    unittest.main()
