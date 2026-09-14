"""tests/unit/test_isolation_guard.py — guardas de isolamento, CLI publico e teardown (C3, C4, S2).

`FixtureHost` responde aos comandos que `SandboxFixture.teardown()` e
`assert_no_orphans()` emitem. Cada classe de comando do teardown (stop,
disable, reset-failed, daemon-reload, remocao Podman, consulta de existencia,
estado da unit no manager) tem um prisoner test proprio que injeta a falha e
exige `IsolationError`.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "cli"))
sys.path.insert(0, str(REPO))

from asb import install, supervisor  # noqa: E402
from tests.integration.sandbox_fixture import IsolationError, SandboxFixture  # noqa: E402

CLI_PATH = REPO / "cli" / "asb-agent"


def _load_cli_module():
    loader = importlib.machinery.SourceFileLoader("asb_agent_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestPathSeams(unittest.TestCase):
    def test_state_root_seam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ASB_STATE_ROOT": tmp}):
            self.assertEqual(supervisor._resolve_paths("myws")[0], Path(tmp) / "myws")

    def test_explicit_target_dir_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ASB_SYSTEMD_UNIT_DIR": "/nope"}):
            self.assertEqual(supervisor._resolve_paths("myws", target_dir=Path(tmp))[1], Path(tmp))

    def test_dropin_default_root_is_config_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ASB_CONFIG_ROOT": tmp}):
            self.assertEqual(install.get_dropin_path(),
                             Path(tmp) / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf")


class TestPublicCli(unittest.TestCase):
    def test_no_unit_name_or_bypass_flags(self) -> None:
        parser = _load_cli_module().build_parser()
        sub = next(a for a in parser._actions if type(a).__name__ == "_SubParsersAction")
        for name in ("adopt-runtime", "rollback-runtime"):
            opts = [o for act in sub.choices[name]._actions for o in act.option_strings]
            for forbidden in ("--unit-name", "--unit", "--keyring-unit", "--bypass", "--target-dir", "--state-dir"):
                self.assertNotIn(forbidden, opts)

    def test_keyring_core_has_no_unit_name_parameter(self) -> None:
        for fn in (supervisor.adopt_keyring, supervisor.rollback_keyring, supervisor.adopt_workspace):
            params = inspect.signature(fn).parameters
            self.assertNotIn("unit_name", params)
            self.assertNotIn("keyring_unit", params)

    def test_cli_forwards_only_apply(self) -> None:
        cli = _load_cli_module()
        for argv, expected in ((["--keyring", "--apply", "--json"], True), (["--keyring"], False)):
            with self.subTest(argv=argv), mock.patch("asb.supervisor.adopt_keyring") as adopt, \
                    mock.patch("sys.argv", ["asb-agent", "adopt-runtime", *argv]):
                adopt.return_value = {"status": "applied", "component": "keyring", "phase": "readiness_verified"}
                self.assertEqual(cli.main(), 0)
                adopt.assert_called_once_with(apply=expected)

    def test_cli_rollback_calls(self) -> None:
        cli = _load_cli_module()
        with mock.patch("asb.supervisor.rollback_keyring") as rb, \
                mock.patch("sys.argv", ["asb-agent", "rollback-runtime", "--keyring", "--json"]):
            rb.return_value = {"status": "rolled_back", "component": "keyring"}
            self.assertEqual(cli.main(), 0)
            rb.assert_called_once_with()
        with mock.patch("asb.supervisor.rollback_workspace") as rb, \
                mock.patch("sys.argv", ["asb-agent", "rollback-runtime", "--workspace", "ws-test"]):
            rb.return_value = {"status": "rolled_back", "workspace": "ws-test"}
            self.assertEqual(cli.main(), 0)
            rb.assert_called_once_with("ws-test")


class FixtureHost:
    """systemctl/podman/pgrep simulados para o teardown da SandboxFixture."""

    ENABLED_RC = {"enabled": 0, "enabled-runtime": 0, "static": 0, "disabled": 1, "not-found": 4}

    def __init__(self) -> None:
        self.units: dict[str, dict] = {}
        self.resources: dict[tuple[str, str], bool] = {}
        self.running: set[str] = set()
        self.sticky: set[tuple[str, str]] = set()
        self.fail: dict[tuple, tuple[int, str, str]] = {}
        self.calls: list[tuple] = []
        self.pgrep = (1, "", "")

    def unit(self, name: str, *, enabled: str = "not-found", active: str = "inactive", loaded: bool = False):
        self.units[name] = {"enabled": enabled, "active": active, "loaded": loaded}

    def run(self, argv, *args, **kwargs):
        argv = [str(a) for a in argv]
        key = (Path(argv[0]).name, *argv[1:])
        self.calls.append(key)
        if key in self.fail:
            rc, out, err = self.fail[key]
        elif key[0] == "systemctl":
            rc, out, err = self._systemctl(list(key[2:]))
        elif key[0] == "podman":
            rc, out, err = self._podman(list(key[1:]))
        elif key[0] == "pgrep":
            rc, out, err = self.pgrep
        else:
            raise AssertionError(f"comando inesperado no teardown: {argv}")
        return subprocess.CompletedProcess(argv, rc, out, err)

    def _systemctl(self, args: list[str]):
        verb = args[0]
        if verb == "daemon-reload":
            for u in self.units.values():
                if u["active"] != "active" and not u.get("keep"):
                    u.update(enabled="not-found", loaded=False)
            return 0, "", ""
        name = args[-1]
        u = self.units.setdefault(name, {"enabled": "not-found", "active": "inactive", "loaded": False})
        if verb == "is-enabled":
            return self.ENABLED_RC[u["enabled"]], u["enabled"] + "\n", ""
        if verb == "is-active":
            if u["active"] == "active":
                return 0, "active\n", ""
            if u["active"] == "failed" and not u["loaded"]:
                # systemd real: unit cujo arquivo sumiu mas segue 'failed' no manager.
                return 4, "failed\n", ""
            return (3 if u["loaded"] or u["active"] in ("failed", "activating") else 4), u["active"] + "\n", ""
        if verb == "stop":
            u["active"] = "inactive"
        elif verb == "reset-failed":
            u["active"] = "inactive"
        elif verb == "disable":
            u["enabled"] = "disabled"
        else:
            raise AssertionError(args)
        return 0, "", ""

    def _podman(self, args: list[str]):
        if args[0] in ("container", "volume", "network") and args[1] == "exists":
            return (0 if self.resources.get((args[0], args[2])) else 1), "", ""
        if args[0] == "ps":
            name = args[2][len("name=^"):-1]
            return 0, ("cid\n" if name in self.running else ""), ""
        if args[:2] == ["rm", "-f"]:
            kind, name = "container", args[2]
        elif args[1:3] == ["rm", "-f"]:
            kind, name = args[0], args[3]
        else:
            raise AssertionError(args)
        if (kind, name) not in self.sticky:
            self.resources[(kind, name)] = False
            self.running.discard(name)
        return 0, "", ""


class _FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.fx = SandboxFixture("isoguard", auto_setup=False)
        self.addCleanup(lambda fx=self.fx: fx.state_root.exists() and __import__("shutil").rmtree(fx.state_root))
        # A unit dir real do manager nunca e tocada por teste unitario.
        self.fx._unit_dir = self.tmp / "run-units"
        self.fx._unit_dir.mkdir()
        self.fx._unit_file = self.fx._unit_dir / self.fx.unit
        self.fx._forwarder_unit_file = self.fx._unit_dir / self.fx.forwarder_unit
        self.host = FixtureHost()
        p = self.fx._prefix
        self.container = self.fx.register_container(f"{p}-agent")
        self.volume = self.fx.register_volume(f"{p}-vol")
        self.network = self.fx.register_network(f"{p}-net")
        self.target = self.fx.register_unit(f"{p}.target")
        for kind, name in (("container", self.container), ("volume", self.volume), ("network", self.network)):
            self.host.resources[(kind, name)] = True
        self.host.running.add(self.container)
        self.host.unit(self.target, enabled="enabled-runtime", active="active", loaded=True)

    def teardown(self):
        with mock.patch("subprocess.run", side_effect=self.host.run):
            self.fx.teardown()

    def assert_teardown_fails(self, *needles: str) -> None:
        with self.assertRaises(IsolationError) as cm:
            self.teardown()
        for needle in needles:
            self.assertIn(needle, str(cm.exception))


class TestTeardownCommandClasses(_FixtureCase):
    def test_clean_teardown_quiesces_units_and_removes_everything(self) -> None:
        self.teardown()
        self.assertIn(("systemctl", "--user", "stop", self.target), self.host.calls)
        self.assertIn(("systemctl", "--user", "disable", "--runtime", self.target), self.host.calls)
        self.assertIn(("systemctl", "--user", "daemon-reload"), self.host.calls)
        self.assertFalse(any(self.host.resources.values()))
        self.assertEqual(self.host.units[self.target]["enabled"], "not-found")
        self.assertFalse(self.fx.state_root.exists())
        self.assertTrue(any(c[0] == "pgrep" for c in self.host.calls), "assert_no_orphans nao rodou no teardown")

    def test_auto_restarting_unit_is_stopped(self) -> None:
        self.host.unit(self.target, enabled="disabled", active="activating", loaded=True)
        self.teardown()
        self.assertIn(("systemctl", "--user", "stop", self.target), self.host.calls)

    def test_failed_unit_without_file_is_reset(self) -> None:
        """`down` remove o arquivo, mas o manager guarda o service 'failed' (is-active rc=4)."""
        self.host.unit(self.target, enabled="not-found", active="failed", loaded=False)
        self.teardown()
        self.assertIn(("systemctl", "--user", "reset-failed", self.target), self.host.calls)
        self.assertEqual(self.host.units[self.target]["active"], "inactive")

    def test_persistently_enabled_unit_is_disabled_without_runtime_flag(self) -> None:
        self.host.unit(self.target, enabled="enabled", active="inactive", loaded=True)
        self.teardown()
        self.assertIn(("systemctl", "--user", "disable", self.target), self.host.calls)
        self.assertNotIn(("systemctl", "--user", "disable", "--runtime", self.target), self.host.calls)

    def test_stop_failure(self) -> None:
        self.host.fail[("systemctl", "--user", "stop", self.target)] = (1, "", "Job failed")
        self.assert_teardown_fails("stop", self.target, "Job failed")

    def test_disable_failure_rc1_is_not_tolerated(self) -> None:
        self.host.fail[("systemctl", "--user", "disable", "--runtime", self.target)] = (1, "", "Access denied")
        self.assert_teardown_fails("disable", "Access denied")

    def test_reset_failed_failure(self) -> None:
        self.host.unit(self.target, enabled="disabled", active="failed", loaded=True)
        self.host.fail[("systemctl", "--user", "reset-failed", self.target)] = (1, "", "Access denied")
        self.assert_teardown_fails("reset-failed", "Access denied")

    def test_daemon_reload_failure(self) -> None:
        self.host.fail[("systemctl", "--user", "daemon-reload")] = (1, "", "Access denied")
        self.assert_teardown_fails("daemon-reload")

    def test_container_removal_failure_is_not_matched_by_substring(self) -> None:
        self.host.fail[("podman", "rm", "-f", self.container)] = (2, "", "Error: no such container (falso)")
        self.assert_teardown_fails(self.container)

    def test_volume_removal_failure(self) -> None:
        self.host.fail[("podman", "volume", "rm", "-f", self.volume)] = (2, "", "volume is being used")
        self.assert_teardown_fails(self.volume)

    def test_network_removal_failure(self) -> None:
        self.host.fail[("podman", "network", "rm", "-f", self.network)] = (2, "", "network in use")
        self.assert_teardown_fails(self.network)

    def test_existence_query_error_is_not_absence(self) -> None:
        for kind in ("container", "volume", "network"):
            with self.subTest(kind=kind):
                self.setUp()  # fixture nova: prefixo novo, entao o nome e lido depois
                name = getattr(self, kind)
                self.host.fail[("podman", kind, "exists", name)] = (125, "", "storage error")
                self.assert_teardown_fails(name, "125")

    def test_resource_still_present_after_successful_removal(self) -> None:
        self.host.sticky.add(("volume", self.volume))
        self.assert_teardown_fails(self.volume, "ainda existe")

    def test_unit_still_known_to_manager_after_reload(self) -> None:
        self.host.units[self.target]["keep"] = True
        self.assert_teardown_fails(self.target)

    def test_unsupported_unit_state_fails_closed(self) -> None:
        self.host.fail[("systemctl", "--user", "is-enabled", self.target)] = (1, "masked\n", "")
        self.assert_teardown_fails(self.target, "masked")

    def test_stderr_from_state_query_fails_closed(self) -> None:
        self.host.fail[("systemctl", "--user", "is-active", self.target)] = (3, "inactive\n", "Connection refused")
        self.assert_teardown_fails("Connection refused")

    def test_quiesce_gives_up_when_the_unit_never_leaves_the_active_state(self) -> None:
        """Exaustao do laco de `_quiesce_unit`: rc=0 em todo `stop`, estado imovel.

        O laco so devolve pelo `else` — estado limpo. Um manager que aceita o
        `stop` (rc=0) e mantem a unit ativa faria as cinco voltas passarem sem
        progresso; sem o teto, o teardown seguiria adiante com a unit de pe.
        """
        self.host.fail[("systemctl", "--user", "stop", self.target)] = (0, "", "")
        self.assert_teardown_fails(self.target, "nao ficou parada e desabilitada")

    def test_sentinel_query_error_is_not_absence(self) -> None:
        """`sentinel_exists` so traduz rc 0/1; qualquer outro e falha de consulta.

        Colapsar rc 125 (container morto, storage quebrado) em "sentinela
        ausente" faria um teste de reinicio passar por engano — R6 aplicado a
        sonda do piloto.
        """
        res = subprocess.CompletedProcess(["podman"], 125, "", "container nao esta em execucao")
        with mock.patch("subprocess.run", return_value=res) as run:
            with self.assertRaises(RuntimeError) as cm:
                self.fx.sentinel_exists()
        run.assert_called_once()
        self.assertIn("125", str(cm.exception))

    def test_state_root_removal_failure(self) -> None:
        with mock.patch("shutil.rmtree", side_effect=OSError("disco protegido")) as rm:
            self.assert_teardown_fails("state_root", "disco protegido")
        rm.assert_called()

    def test_unit_file_removal_failure(self) -> None:
        unit_file = self.fx._unit_dir / self.target
        unit_file.write_text("[Unit]\n")
        real_unlink = Path.unlink

        def unlink(path, *a, **kw):
            if path == unit_file:
                raise OSError("permissao negada na unit")
            return real_unlink(path, *a, **kw)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=unlink) as ul:
            self.assert_teardown_fails("permissao negada na unit")
        ul.assert_called()

    def test_residual_wants_link_is_an_error_and_is_removed(self) -> None:
        wants = self.tmp / "home" / ".config" / "systemd" / "user" / "default.target.wants"
        wants.mkdir(parents=True)
        (wants / self.target).symlink_to("/nonexistent")
        self.assert_teardown_fails("wants", self.target)
        self.assertFalse((wants / self.target).is_symlink())


class TestAssertNoOrphans(_FixtureCase):
    def _check(self, **kw) -> None:
        with mock.patch("subprocess.run", side_effect=self.host.run):
            self.fx.assert_no_orphans(**kw)

    def test_default_scope_is_the_supervised_container(self) -> None:
        self.host.unit(self.target)
        self.host.running = {self.container}
        self._check()  # o container do workspace nao e o `self.container` da fixture

    def test_all_registered_running_container_is_an_orphan(self) -> None:
        self.host.unit(self.target)
        with self.assertRaises(AssertionError) as cm:
            self._check(all_registered=True)
        self.assertIn(self.container, str(cm.exception))

    def test_active_registered_unit_is_an_orphan(self) -> None:
        self.host.running.clear()
        with self.assertRaises(AssertionError) as cm:
            self._check()
        self.assertIn(self.target, str(cm.exception))

    def test_container_query_failure_is_not_absence(self) -> None:
        """Falha do `podman ps` na propria rede de seguranca nao pode passar por 'nada rodando'."""
        self.host.unit(self.target, enabled="disabled", active="inactive", loaded=True)  # so o ps deve falhar
        # escopo default consulta o container supervisionado da fixture, nao o registrado no setUp
        key = ("podman", "ps", "--filter", f"name=^{self.fx.container}$", "--filter", "status=running", "--quiet")
        self.host.fail[key] = (125, "", "Error: connection refused")
        with mock.patch("subprocess.run", side_effect=self.host.run), \
                self.assertRaises(AssertionError) as cm:
            self.fx.assert_no_orphans()
        self.assertIn("podman ps", str(cm.exception))
        self.assertIn("125", str(cm.exception))

    def test_orphan_process_is_reported(self) -> None:
        self.host.running.clear()
        self.host.unit(self.target)
        self.host.pgrep = (0, "4242 conmon\n", "")
        with self.assertRaises(AssertionError) as cm:
            self._check(all_registered=True)
        self.assertIn("4242", str(cm.exception))

    def test_pgrep_error_is_not_absence(self) -> None:
        self.host.running.clear()
        self.host.unit(self.target)
        self.host.pgrep = (2, "", "pgrep: bad regex")
        with self.assertRaises(AssertionError):
            self._check(all_registered=True)


class TestI6CliGuards(unittest.TestCase):
    """As guardas de autodefesa do runner do CLI isolado, exercitadas de proposito."""

    def _settings(self, **over) -> Path:
        import json
        base = {"env": {"ASB_CONFIG_ROOT": "/tmp/nao-existe"}, "home": "/tmp/nao-existe/home",
                "units": [], "containers": [], "crash_at": None, "host_target": None}
        base.update(over)
        path = Path(self.tmp) / f"settings-{len(list(Path(self.tmp).iterdir()))}.json"
        path.write_text(json.dumps(base))
        return path

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        from tests.integration.test_adoption import i6_cli
        self.i6_cli = i6_cli

    def test_environment_divergence_is_refused(self) -> None:
        settings = self._settings(env={"ASB_CONFIG_ROOT": "/tmp/esperado-outro"})
        with mock.patch.dict(os.environ, {"ASB_CONFIG_ROOT": "/tmp/valor-diferente"}), \
                self.assertRaises(IsolationError) as cm:
            self.i6_cli(settings, ["adopt-runtime", "--workspace", "x"])
        self.assertIn("ambiente do CLI divergente", str(cm.exception))

    def test_state_root_leak_is_refused(self) -> None:
        env = {"ASB_CONFIG_ROOT": "/tmp/coerente"}
        settings = self._settings(env=env)
        with mock.patch.dict(os.environ, {**env, "ASB_STATE_ROOT": "/tmp/vazou"}), \
                self.assertRaises(IsolationError) as cm:
            self.i6_cli(settings, ["adopt-runtime", "--workspace", "x"])
        self.assertIn("ASB_STATE_ROOT", str(cm.exception))


class TestGuardCommand(unittest.TestCase):
    """A guarda da integracao recusa sozinha o que foge da fixture, sem depender do fluxo de producao."""

    UNITS = {"asb-test-g-1.target", "asb-test-g-1-agent.service"}
    CONTAINERS = {"asb-test-g-1-agent"}
    NAMES = {"cid-agent": "/asb-test-g-1-agent", "cid-other": "/asb-keyring"}

    def setUp(self) -> None:
        from tests.integration.test_adoption import guard_command
        self.guard = guard_command
        self.inspected: list[list[str]] = []

    def real_run(self, argv, **kwargs):
        """`podman inspect --format {{.Name}} <ref>` simulado: resolve IDs conhecidos, 125 para o resto."""
        self.inspected.append(list(argv))
        ref = argv[-1]
        if ref in self.NAMES:
            return subprocess.CompletedProcess(argv, 0, self.NAMES[ref] + "\n", "")
        return subprocess.CompletedProcess(argv, 125, "", "Error: no such container")

    def check(self, argv: list[str]) -> None:
        self.guard(argv, self.UNITS, self.CONTAINERS, self.real_run)

    def test_out_of_contract_commands_are_refused(self) -> None:
        cases = (
            ["systemctl", "start", "asb-test-g-1.target"],                       # sem --user
            ["systemctl", "--user", "mask", "asb-test-g-1.target"],              # verbo fora do contrato
            ["systemctl", "--user", "stop"],                                     # mutacao global
            ["systemctl", "--user", "reset-failed"],                             # mutacao global
            ["systemctl", "--user", "show", "--property=Environment"],           # consulta global
            ["systemctl", "--user", "start", "asb-keyring.service"],             # unit do operador
            ["systemctl", "--user", "stop", "asb-test-g-1.target", "asb-test-g-10.target"],  # irma
            ["podman", "container", "rm", "asb-test-g-1-agent"],
            ["podman", "volume", "rm", "asb-test-g-1-vol"],
            ["podman", "exec", "-u", "root", "asb-keyring", "true"],
            ["podman", "exec", "cid-other", "true"],                             # ID de container alheio
            ["podman", "exec", "-u", "root"],                                    # sem container
            ["podman", "update", "--restart=no"],                                # sem alvo
            ["podman", "stop", "-t", "5", "asb-keyring"],
            ["podman", "run", "--name", "asb-keyring", "img"],
            ["podman", "create", "img"],
            ["podman", "rm", "-f", "asb-test-g-1-agent"],                        # rm nunca, nem registrado
            ["podman", "system", "reset"],
        )
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(IsolationError):
                self.check(argv)

    def test_contract_commands_are_allowed(self) -> None:
        cases = (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "show", "--property=UnitPath", "--value"],
            ["systemctl", "--user", "is-active", "asb-test-g-1.target"],
            ["systemctl", "--user", "enable", "--runtime", "asb-test-g-1.target"],
            ["podman", "container", "exists", "asb-keyring"],                    # leitura
            ["podman", "inspect", "qualquer"],
            ["podman", "exec", "-u", "root", "asb-test-g-1-agent", "true"],
            ["podman", "update", "--restart=no", "cid-agent"],                   # ID resolvido por inspect
            ["podman", "stop", "-t", "5", "asb-test-g-1-agent"],
            ["podman", "run", "--name", "asb-test-g-1-agent", "img"],
            ["ssh", "-p", "2222", "localhost"],                                  # nem systemctl nem podman
        )
        for argv in cases:
            with self.subTest(argv=argv):
                self.check(argv)
        self.assertTrue(any(a[-1] == "cid-agent" and "inspect" in a for a in self.inspected))


class TestResourceNames(unittest.TestCase):
    def test_sibling_prefix_extension_is_refused(self) -> None:
        fx = SandboxFixture("adoptguard", auto_setup=False)
        try:
            fx._validate_resource_name(f"{fx._prefix}-agent")
            fx._validate_resource_name(f"{fx._prefix}.target")
            fx._validate_resource_name(fx._prefix)
            for sibling in (f"{fx._prefix}2", f"{fx._prefix}_other", "asb-keyring.service"):
                with self.subTest(sibling=sibling), self.assertRaises(IsolationError):
                    fx._validate_resource_name(sibling)
        finally:
            __import__("shutil").rmtree(fx.state_root)


if __name__ == "__main__":
    unittest.main()
