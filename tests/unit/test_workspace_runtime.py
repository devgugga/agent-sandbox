"""tests/unit/test_workspace_runtime.py — orquestracao de preparo de
recursos do workspace, `cli/asb/runtime/workspace.py::WorkspaceRuntime`.

Tarefa 4 da decomposicao de modulos (brief Passo 2): testa `prepare()`
isolado de `lifecycle.up()` — sem sonda de prontidao, sem mise install, sem
`emit()`, porque nenhum desses pertence a `prepare()` (a ruling R16 do
controlador confirma: `WorkspaceRuntime` e so `prepare/start/suspend/
resume/remove_resources`, nao o fluxo inteiro de `up`). Cobre a ORDEM REAL
de eventos que `prepare()` emite (nao a lista ilustrativa do brief — ver
R6 no relatorio da Tarefa 4) e que uma falha em cada evento com efeito
colateral resulta em rollback que atinge SOMENTE os recursos ja registrados
ate aquele ponto.

Colaboradores (Podman, supervisor) sao mockados nos modulos REAIS
compartilhados (`cli.asb.podman`, `cli.asb.supervisor`) — nao ha protocolo
novo aqui: `SandboxRuntime` e `RuntimeStorage` ja estabelecem o padrao de
injecao por parametro com default real, e criar cinco Protocols novos para
isto seria estrutura especulativa (YAGNI).
"""
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from cli.asb.profile import Profile
from cli.asb.runtime.storage import RuntimeStorage
from cli.asb.runtime.transaction import WorkspaceTransaction
from cli.asb.runtime.workspace import WorkspaceRuntime
from cli.asb.workspace import Layout


def _fake_storage(**overrides):
    """`RuntimeStorage` REAL com os quatro pontos que tocariam disco ou
    Podman trocados por valores fixos — mesmo padrao de
    `test_lifecycle.py::_fake_storage`."""
    import os

    storage = RuntimeStorage(Path(os.path.expanduser("~")))
    storage.ensure_credentials = mock.Mock(
        return_value=overrides.get("credentials", "asb-credentials"))
    storage.credential_mounts = mock.Mock(
        return_value=list(overrides.get("credential_mounts", ())))
    storage.ensure_sessions = mock.Mock(
        return_value=overrides.get("session", "asb-test-ws-session"))
    storage.ensure_toolcache = mock.Mock(
        return_value=overrides.get("toolcache", "t-vol"))
    return storage


class _Harness:
    """Prepara um `WorkspaceRuntime().prepare(...)` isolado: nenhuma
    invocacao real de Podman, systemd, disco fora de um diretorio temporario,
    ou rede. Devolve o `ExitStack` aberto para o chamador poder injetar
    falhas antes de `run()`."""

    def __init__(self, tmp: Path, *, host_ports=(), container_mode="standard",
                host_api="none", events: list[str] | None = None):
        self.tmp = tmp
        self.events = events if events is not None else []
        self.ws = "demo"
        self.root = tmp / "root"
        self.repo = tmp / "origin"
        self.home = tmp / "home"
        for d in (self.root, self.repo, self.home):
            d.mkdir(parents=True, exist_ok=True)
        self.runtime_dir = tmp / "runtime" / "rev1"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.key = tmp / "key"
        self.key.write_text("dummy")
        (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")

        self.layout = Layout(ws=self.ws, project="proj", mount=tmp / "mount",
                             project_root=tmp / "mount" / "proj",
                             state=tmp / "state")
        self.profile = Profile(services=[], host_ports=list(host_ports),
                               publish_ports=[], host_api=host_api,
                               container_mode=container_mode, allow=[])
        self.storage = _fake_storage()
        self.tx = WorkspaceTransaction(self.ws, is_existing=False)
        self.runtime = WorkspaceRuntime()

        self._network_exists = {"asb-demo": False, "asb-demo-out": False}
        self.podman_calls: list[tuple] = []

    def _fake_exists(self, kind, name):
        if kind == "image":
            return True
        if kind == "network":
            return self._network_exists.get(name, False)
        if kind == "volume":
            return False
        return False

    def _fake_run(self, *args, **kwargs):
        self.podman_calls.append(args)
        if args[:1] == ("network",) and args[1:2] == ("create",):
            name = args[-1]
            self._network_exists[name] = True
            self.events.append("create-network")
        elif "--name" in args:
            idx = args.index("--name") + 1
            target = args[idx]
            if target == "asb-demo-proxy":
                self.events.append("create-proxy")
            elif target == "asb-demo-agent":
                self.events.append("create-agent")
            elif target.endswith("-fwd"):
                self.events.append("create-forwarder")
            elif target.endswith("-docker"):
                self.events.append("create-docker-broker")
            elif "-svc-" in target:
                self.events.append("create-service")
        return mock.MagicMock(returncode=0, stdout="cid")

    def build(self):
        stack = ExitStack()
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.podman.exists",
            side_effect=self._fake_exists))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.podman.run", side_effect=self._fake_run))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.podman.out",
            side_effect=lambda *a, **k: f"cid-{a[1]}" if len(a) > 1 else "cid"))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.prepare_clone",
            side_effect=lambda *a, **k: self.events.append("prepare-clone")))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.layout_for", return_value=self.layout))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.load_profile", return_value=self.profile))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.render", return_value="acl allow ..."))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.build_staging", return_value=0))
        stack.enter_context(mock.patch(
            "cli.asb.lifecycle.ensure_ssh_key", return_value=self.key))
        stack.enter_context(mock.patch(
            "cli.asb.lifecycle.ensure_runtime", return_value=self.runtime_dir))
        stack.enter_context(mock.patch(
            "cli.asb.lifecycle.ensure_keyring_service",
            side_effect=lambda *a, **k: self.events.append("ensure-keyring")))
        stack.enter_context(mock.patch(
            "cli.asb.lifecycle.ensure_keyring_runtime_volume",
            return_value="asb-keyring-runtime"))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.supervisor.unit_dir",
            return_value=self.tmp / "units"))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.supervisor.network_unit_name",
            return_value="asb-network.service"))
        stack.enter_context(mock.patch(
            "cli.asb.runtime.workspace.supervisor.install_workspace",
            side_effect=lambda *a, **k: self.events.append("install-units") or []))
        if self.profile.host_api == "read":
            # §4 (broker Docker) checa a existencia REAL de
            # /run/asb-docker/docker.sock antes de criar o container;
            # so este caminho especifico e forjado, o resto de `Path.exists`
            # segue real.
            orig_exists = Path.exists

            def fake_path_exists(p):
                if str(p) == "/run/asb-docker/docker.sock":
                    return True
                return orig_exists(p)
            stack.enter_context(mock.patch.object(Path, "exists", fake_path_exists))
        return stack


class TestPrepareEventOrder(unittest.TestCase):
    """Ordem REAL de `WorkspaceRuntime.prepare()` (R6): prepare-clone,
    create-network (x2), create-proxy, create-agent, write-manifest,
    install-units — a lista ilustrativa do brief inclui eventos de `up()`
    (host-ready, start-target, proxy-ready, mise-install, ports-ready,
    ssh-ready) que NAO pertencem a `prepare()` sob a R16: ficam fora daqui
    de proposito."""

    def test_default_profile_order(self):
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), events=events)
            with h.build():
                # Grava o manifesto e instala as unidades com um marcador
                # proprio: write_text nao passa por podman.run/exists.
                orig_write_text = Path.write_text

                def tracking_write_text(self_path, *a, **kw):
                    if self_path.name == "runtime.json":
                        events.append("write-manifest")
                    return orig_write_text(self_path, *a, **kw)

                with mock.patch.object(Path, "write_text", tracking_write_text):
                    h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

        self.assertEqual(events, [
            "prepare-clone",
            "create-network",
            "create-network",
            "create-proxy",
            "ensure-keyring",
            "create-agent",
            "write-manifest",
            "install-units",
        ])

    def test_forwarder_and_service_events_land_between_proxy_and_agent(self):
        """§2-4 (servicos, forwarder, broker docker) rodam DEPOIS do proxy e
        ANTES do agente — a ordem real do codigo (secoes 1 a 5), nao a lista
        ilustrativa do brief que so cita 'create-agent'."""
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), host_ports=[8080], events=events)
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

        proxy_idx = events.index("create-proxy")
        forwarder_idx = events.index("create-forwarder")
        agent_idx = events.index("create-agent")
        self.assertLess(proxy_idx, forwarder_idx)
        self.assertLess(forwarder_idx, agent_idx)

    def test_ensure_keyring_service_precedes_agent_creation(self):
        """Ja coberto em test_lifecycle.py via `up()`; repetido aqui no
        nivel de `prepare()` porque e o proprio `prepare()` que garante essa
        ordem agora, nao mais `lifecycle.prepare_workspace` diretamente."""
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), events=events)
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

        self.assertLess(events.index("ensure-keyring"), events.index("create-agent"))


class TestPrepareFailureInjectionRollsBackOnlyEarlierResources(unittest.TestCase):
    """Brief Passo 2: uma falha em CADA evento com efeito colateral deixa a
    transacao com SOMENTE os recursos criados ANTES daquele ponto — nunca o
    que a secao que falhou (ou uma posterior) teria criado."""

    def _prepare_with_failure(self, *, fail_at: str):
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), events=events)
            with h.build():
                if fail_at == "create-network":
                    boom_run = h._fake_run

                    def failing_run(*args, **kwargs):
                        if args[:2] == ("network", "create") or (
                                args[:1] == ("network",) and "create" in args):
                            raise RuntimeError("boom-network")
                        return boom_run(*args, **kwargs)
                    patcher = mock.patch(
                        "cli.asb.runtime.workspace.podman.run", side_effect=failing_run)
                elif fail_at == "create-proxy":
                    def failing_run(*args, **kwargs):
                        if "--name" in args and args[args.index("--name") + 1] == "asb-demo-proxy":
                            raise RuntimeError("boom-proxy")
                        return h._fake_run(*args, **kwargs)
                    patcher = mock.patch(
                        "cli.asb.runtime.workspace.podman.run", side_effect=failing_run)
                elif fail_at == "create-agent":
                    def failing_run(*args, **kwargs):
                        if "--name" in args and args[args.index("--name") + 1] == "asb-demo-agent":
                            raise RuntimeError("boom-agent")
                        return h._fake_run(*args, **kwargs)
                    patcher = mock.patch(
                        "cli.asb.runtime.workspace.podman.run", side_effect=failing_run)
                elif fail_at == "write-manifest":
                    orig_write_text = Path.write_text

                    def failing_write_text(self_path, *a, **kw):
                        if self_path.name == "runtime.json":
                            raise OSError("boom-manifest")
                        return orig_write_text(self_path, *a, **kw)
                    patcher = mock.patch.object(
                        Path, "write_text", failing_write_text)
                elif fail_at == "install-units":
                    patcher = mock.patch(
                        "cli.asb.runtime.workspace.supervisor.install_workspace",
                        side_effect=RuntimeError("boom-units"))
                else:
                    raise AssertionError(fail_at)

                with patcher:
                    with self.assertRaises((RuntimeError, OSError)):
                        h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)
            return h.tx

    def test_failure_creating_network_records_nothing(self):
        tx = self._prepare_with_failure(fail_at="create-network")
        self.assertEqual(tx.created_networks, [])
        self.assertEqual(tx.created_containers, [])

    def test_failure_creating_proxy_keeps_only_the_two_networks(self):
        tx = self._prepare_with_failure(fail_at="create-proxy")
        self.assertEqual(len(tx.created_networks), 2)
        self.assertEqual(tx.created_containers, [])

    def test_failure_creating_agent_keeps_networks_and_proxy_but_not_agent(self):
        tx = self._prepare_with_failure(fail_at="create-agent")
        self.assertEqual(len(tx.created_networks), 2)
        self.assertEqual(len(tx.created_containers), 1)  # so o proxy

    def test_failure_writing_manifest_keeps_networks_and_both_containers(self):
        tx = self._prepare_with_failure(fail_at="write-manifest")
        self.assertEqual(len(tx.created_networks), 2)
        self.assertEqual(len(tx.created_containers), 2)  # proxy + agent
        self.assertEqual(tx.created_units, [])

    def test_failure_installing_units_keeps_everything_created_so_far(self):
        tx = self._prepare_with_failure(fail_at="install-units")
        self.assertEqual(len(tx.created_networks), 2)
        self.assertEqual(len(tx.created_containers), 2)
        # `install_workspace` falhou ANTES de devolver a lista de unidades:
        # nenhuma unidade foi registrada (o loop de `tx.record_unit` nunca
        # roda porque a excecao interrompe antes dele).
        self.assertEqual(tx.created_units, [])

    def test_a_failure_never_lets_rollback_touch_a_resource_it_did_not_create(self):
        """Reforca a garantia de posse (ja coberta em profundidade por
        test_runtime_transaction.py): rodar o rollback real depois de cada
        falha injetada acima nunca nomeia um recurso fora do que a propria
        transacao registrou."""
        for fail_at in ("create-network", "create-proxy", "create-agent",
                        "write-manifest", "install-units"):
            with self.subTest(fail_at=fail_at):
                tx = self._prepare_with_failure(fail_at=fail_at)
                with mock.patch("cli.asb.runtime.transaction.podman.run") as run, \
                     mock.patch("cli.asb.runtime.transaction.podman.exists", return_value=True), \
                     mock.patch("cli.asb.runtime.transaction.supervisor.remove_workspace_units"):
                    tx.rollback()
                removed_ids = {c.args[2] for c in run.call_args_list
                               if c.args[:2] == ("rm", "-f")}
                self.assertTrue(removed_ids.issubset(set(tx.created_containers)))


class TestPrepareManifestAndAgentArgvMatchPreExtraction(unittest.TestCase):
    """Regressao de comportamento: argv do agente e conteudo do manifesto
    identicos ao que `lifecycle.prepare_workspace` produzia antes da
    extracao (mesmos testes de fundo que `test_lifecycle.py` ja cobria)."""

    def test_proxy_argv(self):
        """§1: cobertura direta do argv do container do proxy — nada mais
        neste arquivo (nem em test_lifecycle.py) inspecionava esta linha,
        e a fatia B a extraiu sem nenhum teste focado. Achado durante o
        proprio red-proof da fatia B (ver relatorio da Tarefa 4)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir))
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

            proxy_call = next(
                c for c in h.podman_calls
                if "--name" in c and c[c.index("--name") + 1] == "asb-demo-proxy")
            self.assertEqual(proxy_call[0], "create")
            self.assertIn("--restart", proxy_call)
            self.assertEqual(proxy_call[proxy_call.index("--restart") + 1], "no")
            self.assertIn("--user", proxy_call)
            self.assertEqual(proxy_call[proxy_call.index("--user") + 1], "900")
            self.assertIn("--network", proxy_call)
            self.assertEqual(
                proxy_call[proxy_call.index("--network") + 1],
                "asb-demo,asb-demo-out")
            self.assertIn(
                f"{h.layout.state / 'squid.conf'}:/etc/squid/squid.conf:ro,Z",
                proxy_call)
            self.assertEqual(
                list(proxy_call[proxy_call.index("agent-sandbox-proxy:latest"):]),
                ["agent-sandbox-proxy:latest", "squid", "-N", "-f", "/etc/squid/squid.conf"])

    def test_docker_broker_argv_when_host_api_is_read(self):
        """§4: cobertura direta do argv do broker Docker — achado durante o
        red-proof da fatia C (services/forwarder/broker), o mesmo padrao do
        `test_proxy_argv` na fatia B: nada neste arquivo nem em
        `test_broker.py` checava `--user` do broker."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), host_api="read")
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

            broker_call = next(
                c for c in h.podman_calls
                if "--name" in c and c[c.index("--name") + 1] == "asb-demo-docker")
            self.assertEqual(broker_call[0], "create")
            self.assertIn("--restart", broker_call)
            self.assertEqual(broker_call[broker_call.index("--restart") + 1], "no")
            self.assertIn("--user", broker_call)
            self.assertEqual(broker_call[broker_call.index("--user") + 1], "900")
            self.assertIn("--network", broker_call)
            self.assertEqual(broker_call[broker_call.index("--network") + 1], "asb-demo")
            self.assertIn("/run/asb-docker/docker.sock:/var/run/docker.sock:Z", broker_call)
            self.assertEqual(
                list(broker_call[broker_call.index("--entrypoint"):]),
                ["--entrypoint", "sh", "agent-sandbox-proxy:latest", "-c",
                 "socat TCP-LISTEN:2375,fork,reuseaddr UNIX-CONNECT:/var/run/docker.sock"])

    def test_agent_argv_and_manifest_content(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), host_ports=[5432])
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

            agent_call = next(
                c for c in h.podman_calls
                if "--name" in c and c[c.index("--name") + 1] == "asb-demo-agent")
            self.assertEqual(agent_call[0], "create")
            self.assertIn("--restart", agent_call)
            self.assertEqual(agent_call[agent_call.index("--restart") + 1], "no")
            self.assertIn("--userns", agent_call)
            self.assertEqual(
                agent_call[agent_call.index("--userns") + 1],
                "keep-id:uid=1000,gid=1000")
            self.assertIn(
                "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000",
                agent_call)
            self.assertEqual(agent_call[-1], "agent-sandbox:latest")

            manifest_file = h.layout.state / "runtime.json"
            manifest = json.loads(manifest_file.read_text())
            self.assertEqual(manifest["runtime_type"], "systemd")
            self.assertEqual(manifest["revision"], "rev1")
            self.assertIn("forwarder", manifest["containers"])

    def test_nested_container_mode_splices_device_flags_before_the_image(self):
        """A fatia D e a mais arriscada (advisor): `agent_args[-1:-1] = [...]`
        e posicional — se `IMAGE` deixar de ser o ultimo elemento a insercao
        vai para o lugar errado. Afirma isso diretamente."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            h = _Harness(Path(tmp_dir), container_mode="nested")
            with h.build():
                h.runtime.prepare(h.root, h.ws, h.repo, tx=h.tx, storage=h.storage)

            agent_call = next(
                c for c in h.podman_calls
                if "--name" in c and c[c.index("--name") + 1] == "asb-demo-agent")
            self.assertEqual(agent_call[-1], "agent-sandbox:latest")
            self.assertIn("--device", agent_call)
            device_idx = agent_call.index("--device")
            # Os flags de nested-mode terminam logo ANTES da imagem (ultimo
            # elemento), nunca depois.
            self.assertLess(device_idx, len(agent_call) - 1)
            self.assertIn("/dev/fuse", agent_call)
            self.assertIn("/dev/net/tun", agent_call)
            self.assertIn("asb-demo-containers", " ".join(agent_call))
            self.assertIn("asb-demo-containers", h.tx.created_volumes)


if __name__ == "__main__":
    unittest.main()
