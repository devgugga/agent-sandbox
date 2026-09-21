"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from . import install, podman, readiness, supervisor
from .checkouts.git import GitError, GitRepository
from .install import install_runtime
from .keyring import (
    CONFIG,
    KEYRING_BUS,
    KEYRING_CONTAINER,
    KEYRING_DATA_VOLUME,
    KEYRING_PASS,
    KEYRING_RUNTIME_VOLUME,
    KEYRING_SCHEMA,
    _inspect_keyring_container,
    _keyring_mount_contract_issue,
    check_keyring_service,
    ensure_keyring_data_volume,
    ensure_keyring_pass,
    ensure_keyring_runtime_volume,
    ensure_keyring_service,
)
from .profile import load_profile
from .runtime.connection import ConnectionInfo
from .runtime.storage import (
    CREDENTIAL_DIRS,
    CREDENTIALS_VOLUME,
    LEGACY_ROOT_CREDENTIAL_FILES,
    SESSION_STATE_DIRS,
    TOOLCACHE_VOLUME,
    RuntimeStorage,
    _mkdir_private,
    _volume_mountpoint,
    credential_mount_args,
    ensure_credential_dirs,
    ensure_credentials_volume,
    ensure_session_volume,
    ensure_toolcache_volume,
    session_mount_args,
    warn_about_legacy_credential_layout,
)
from .runtime.transaction import WorkspaceTransaction
from .runtime.workspace import (
    WorkspaceRuntime,
    build_proxy,
    start_forwarder,
    start_services,
)
from .squid import render
from .workspace import (
    Layout,
    layout_for,
    remove_state,
    remove_workspace,
)

# CONFIG, SSH_KEY e as constantes/funcoes de keyring (KEYRING_*, ensure_keyring_*,
# check_keyring_service, _inspect_keyring_container, _keyring_mount_contract_issue)
# foram extraidas para cli/asb/keyring.py (Tarefa A2). CREDENTIALS_VOLUME,
# TOOLCACHE_VOLUME, CREDENTIAL_DIRS, LEGACY_ROOT_CREDENTIAL_FILES,
# SESSION_STATE_DIRS e as funcoes ensure_credentials_volume,
# ensure_credential_dirs, _volume_mountpoint, _mkdir_private,
# warn_about_legacy_credential_layout, credential_mount_args,
# ensure_session_volume, session_mount_args e ensure_toolcache_volume foram
# extraidas para cli/asb/runtime/storage.py (Tarefa 3). `WorkspaceTransaction`
# foi extraida para cli/asb/runtime/transaction.py, e a implementacao de
# `prepare_workspace` (junto com `build_proxy`, `start_services` e
# `start_forwarder`) para cli/asb/runtime/workspace.py::WorkspaceRuntime
# (Tarefa 4). `prepare_workspace` continua aqui como uma funcao fina que
# delega a `WorkspaceRuntime().prepare(...)`.
# Os nomes acima sao reexports temporarios: mantem `lifecycle.X` funcionando para
# quem ja importava daqui, sem duplicar a logica.
IMAGE = "agent-sandbox:latest"
PROXY_IMAGE = "agent-sandbox-proxy:latest"
PROXY_PORT = 3128
SSH_KEY = CONFIG / "id_ed25519"


def names(ws: str) -> dict[str, str]:
    """Nomes derivados do workspace. Um lugar so: no v1 a derivacao duplicada
    entre create e destroy divergiu e vazou um pod a cada divergencia."""
    return {
        "net": f"asb-{ws}",
        "out": f"asb-{ws}-out",
        "agent": f"asb-{ws}-agent",
        "proxy": f"asb-{ws}-proxy",
        # Volume de ESTADO DE SESSAO deste workspace (transcricoes, todos).
        # Nao e container: derivado aqui pelo mesmo motivo dos demais nomes.
        "session": f"asb-{ws}-session",
    }


def ensure_ssh_key() -> Path:
    if SSH_KEY.exists():
        return SSH_KEY
    CONFIG.mkdir(parents=True, exist_ok=True)
    CONFIG.chmod(0o700)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(SSH_KEY),
                    "-C", "agent-sandbox"], check=True,
                    stdout=subprocess.DEVNULL)
    return SSH_KEY


def build(root: Path) -> int:
    """Constroi a imagem base espelhando o usuario do host.

    id -un e $HOME entram como build args. Nunca literais: um nome assado
    quebraria a imagem no primeiro host diferente (spec §16).
    """
    user = getpass.getuser()
    home = os.path.expanduser("~")
    print(f"construindo {IMAGE} para {user} ({home})")
    # Contexto de build e a raiz do repo: o Containerfile copia cli/asb-guard
    # e image/*, e assim o guarda existe uma vez so.
    podman.run("build", "--build-arg", f"ASB_USER={user}",
               "--build-arg", f"ASB_HOME={home}",
               "-t", IMAGE, "-f", str(root / "image" / "Containerfile"),
               str(root))
    return 0


def _origin_of(ws: str, home: Path) -> Path | None:
    """Le o caminho de origem gravado no estado. `down` precisa dele para achar
    o layout, e um workspace sem estado nao e erro: nao ha o que limpar."""
    marker = home / ".local" / "state" / "agent-sandbox" / ws / "origin"
    return Path(marker.read_text().strip()) if marker.is_file() else None


def _sweep_containers(ws: str) -> None:
    """Remove todo container do workspace pelo LABEL, nunca por prefixo solto:
    casar prefixo sem delimitador casava workspaces irmaos (ex: asb-demo- casava asb-demo-2-)."""
    found: set[str] = set()
    for container in podman.out(
            "ps", "-a", "--filter", f"label=asb.workspace={ws}",
            "--format", "{{.Names}}").splitlines():
        c = container.strip()
        if c:
            found.add(c)
    n = names(ws)
    for c in (n["agent"], n["proxy"], f"{n['net']}-fwd", f"{n['net']}-docker"):
        if podman.exists("container", c):
            found.add(c)
    for container in sorted(found):
        podman.run("rm", "-f", container, check=False)


PRUNED_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    ".next",
    "__pycache__",
}


def discover_mise_dirs(root: Path) -> list[Path]:
    """Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes."""
    if not root.exists():
        return []
    dirs: list[Path] = []
    if (root / "mise.toml").is_file():
        dirs.append(root)
    for item in root.rglob("mise.toml"):
        p = item.parent
        if p == root:
            continue
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(part in PRUNED_DIRS for part in rel_parts):
            continue
        dirs.append(p)
    dirs.sort(key=lambda d: (0 if d == root else 1, len(d.parts), str(d)))
    return dirs


def _run_mise_installs(agent_container: str, project_root: Path) -> list[tuple[Path, int, str]]:
    mise_errors: list[tuple[Path, int, str]] = []
    for d in discover_mise_dirs(project_root):
        print(f"  info executando mise install em {d.name}...", file=sys.stderr)
        res = podman.run("exec", "-u", "1000", "-w", str(d),
                         agent_container, "mise", "install", "-y", check=False)
        rc = getattr(res, "returncode", 1)  # ausente = falha, nunca sucesso
        if rc == 0:
            print(f"  ok   ferramentas mise instaladas ({d.name})", file=sys.stderr)
        else:
            stderr = getattr(res, "stderr", "") or ""
            print(f"  erro falha ao executar mise install em {d.name} (código {rc})",
                  file=sys.stderr)
            if stderr:
                print(stderr.strip(), file=sys.stderr)
            mise_errors.append((d, rc, stderr))
    return mise_errors


def _current_revision(root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, check=True
        )
        rev = res.stdout.strip()
        if rev and all(c not in rev for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            return rev
    except Exception:
        pass
    # `dev` era compartilhado: dois checkouts sem git instalariam o runtime no
    # MESMO diretorio, e `install_runtime` o substitui em lugar — inclusive o
    # `network_gate.py` que as unidades de TODOS os workspaces executam.
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    return f"nogit-{digest}"


def ensure_runtime(root: Path) -> Path:
    """Instala o runtime versionado desta revisao e devolve o diretorio.

    Emenda A: todo workspace e o keyring sao unidades systemd, e as unidades
    executam `launcher.sh`, `runtime_check.py` e `network_gate.py` desse
    diretorio, nunca do checkout.
    """
    return install_runtime(root, _current_revision(root))


def prepare_workspace(
    root: Path,
    ws: str,
    repo: Path,
    tx: WorkspaceTransaction | None = None,
    storage: RuntimeStorage | None = None,
) -> None:
    """Prepara clone, redes, containers e manifesto sem restauracao global.

    Delega inteiramente a `WorkspaceRuntime.prepare()` (Tarefa 4 da
    decomposicao de modulos). Mantida como funcao de nivel de modulo, e nao
    apenas reexportada, para nao quebrar quem ja chamava
    `lifecycle.prepare_workspace(root, ws, repo, tx=..., storage=...)`.
    """
    WorkspaceRuntime().prepare(root, ws, repo, tx=tx, storage=storage)


def up(root: Path, ws: str, repo: Path) -> int:
    """Cria o workspace. Ou completa, ou nao deixa nada para tras.

    Falha em workspace existente NUNCA executa sweep destrutivo de containers preexistentes.
    Em novo workspace, rollback remove EXCLUSIVAMENTE os recursos criados nesta transacao.
    """
    n = names(ws)
    is_existing = podman.exists("container", n["agent"])
    if is_existing:
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    # Emenda A §5: o drop-in legado do podman-restart criava o namespace
    # rootless cedo em todo boot. Remocao idempotente e segura: so sai se o
    # conteudo for exatamente o do projeto; drop-ins alheios ficam intactos.
    if install.remove_project_dropin():
        print("drop-in legado do podman-restart removido", file=sys.stderr)

    # Emenda A §4: a espera de boot e sem limite, mas um `up` interativo sem
    # rede ficaria preso em `systemctl start`. Falha antes de criar qualquer
    # recurso, com sonda so do host: nao cria o namespace rootless.
    host_res = readiness.wait_until(
        lambda to: readiness.probe_host(timeout=to), timeout=30.0)
    if host_res.state != "healthy":
        raise podman.PodmanError(
            f"sem conectividade real ({host_res.code}); conecte a rede e "
            "rode 'asb-agent up' de novo")

    tx = WorkspaceTransaction(ws, is_existing=False)
    home = Path(os.path.expanduser("~"))
    layout = layout_for(repo, ws, home)
    try:
        prepare_workspace(root, ws, repo, tx=tx)
        WorkspaceRuntime().start(ws, enable=True)

        # 1. Sonda de conectividade do proxy antes de operacoes que exigem rede (ex: mise install)
        proxy_res = readiness.wait_until(
            lambda to: readiness.probe_proxy(n["agent"], n["proxy"], timeout=to),
            timeout=30.0,
        )
        if proxy_res.state != "healthy":
            print(f"erro: proxy nao esta pronto ({proxy_res.code}): {proxy_res.remediation}", file=sys.stderr)
            raise podman.PodmanError(f"proxy nao esta pronto: {proxy_res.code}")

        # 2. Executar mise install
        mise_errors = _run_mise_installs(n["agent"], layout.project_root)
        if mise_errors:
            failed_names = ", ".join(d.name for d, _, _ in mise_errors)
            print(f"\nerro: falha na instalacao de ferramentas mise em: {failed_names}",
                  file=sys.stderr)
            print("workspace mantido no ar; corrija a allowlist ou mise.toml e "
                  "execute 'asb-agent up' novamente.", file=sys.stderr)
            return 1

        # 3. Conferir porta e handshake SSH via probe_ssh antes de emitir JSON
        mapping = podman.out("port", n["agent"], "22")
        port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
        if not port:
            raise podman.PodmanError("nao foi possivel determinar a porta SSH")

        # `host_ports` e uma pos-condicao prometida ao projeto: o entrypoint
        # sobe um socat por porta declarada, em segundo plano, e sem sonda o
        # `up` imprimia a conexao com o servico simplesmente ausente.
        declared_ports = load_profile(repo).host_ports
        if declared_ports:
            ports_res = readiness.wait_until(
                lambda to: readiness.probe_host_ports(
                    n["agent"], declared_ports, timeout=to),
                timeout=20.0,
            )
            if ports_res.state != "healthy":
                print(f"erro: portas de host_ports sem listener no agente "
                      f"({ports_res.code}): {ports_res.remediation}",
                      file=sys.stderr)
                print("workspace mantido no ar; corrija e execute "
                      "'asb-agent up' novamente.", file=sys.stderr)
                return 1

        key = ensure_ssh_key()
        ssh_res = readiness.wait_until(
            lambda to: readiness.probe_ssh(
                int(port), user=getpass.getuser(), key=key, timeout=to),
            timeout=30.0,
        )
        if ssh_res.state != "healthy":
            print(f"erro: SSH nao esta pronto ({ssh_res.code}): {ssh_res.remediation}", file=sys.stderr)
            raise podman.PodmanError(f"SSH nao esta pronto na porta {port}: {ssh_res.code}")

        return emit(ws, layout, port=port)
    except BaseException:
        tx.rollback()
        raise


def _up(root: Path, ws: str, repo: Path) -> int:
    return up(root, ws, repo)


def emit(ws: str, layout: Layout, port: str | None = None) -> int:
    """A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca
    inventada: o Orca guarda a que o create devolveu e disca nela para sempre.

    Aceita a porta ja resolvida pelo chamador (ex: `up`, que ja a consultou
    para o gate SSH) para evitar uma segunda chamada `podman port` redundante;
    se omitida, resolve por conta propria.
    """
    n = names(ws)
    resolved_port = port
    if not resolved_port:
        mapping = podman.out("port", n["agent"], "22")
        resolved_port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
    if not resolved_port:
        raise podman.PodmanError("nao foi possivel determinar a porta SSH")
    # A serializacao e delegada a `ConnectionInfo` (Tarefa 3): mesmas quatro
    # chaves, mesma ordem, mesmos tipos que o Orca ja consome. Um
    # `staticmethod` em vez de construir um `ConnectionInfo` completo de
    # proposito — este caminho nunca resolveu `host` nem `identity_file`
    # (isso pediria uma nova chamada a `ensure_ssh_key`), e nao pode passar a
    # resolver so para preencher um dataclass.
    print(json.dumps(ConnectionInfo.lifecycle_payload(
        ws, int(resolved_port), getpass.getuser(), layout.project_root)))
    return 0


def down(ws: str) -> int:
    """Remove unidades do systemd, containers e redes.

    NAO remove ~/asb-agent/<proj>/<ws>: ali vive o trabalho do agente.
    NUNCA remove auth global nem keyring singleton compartilhado.

    Delega a `WorkspaceRuntime.remove_resources()` (Tarefa 4 da
    decomposicao de modulos) a parte de unidades/containers/redes; a
    remocao do ESTADO em disco (arquivos, nao recursos de Podman/systemd)
    continua aqui.
    """
    home = Path(os.path.expanduser("~"))

    WorkspaceRuntime().remove_resources(ws, home)

    # O volume de containers aninhados guarda o que o agente puxou e
    # construiu: e dado do workspace, como a sessao, e `down` preserva dado.
    # So `purge` o remove.
    origin = _origin_of(ws, home)
    if origin is not None:
        remove_state(layout_for(origin, ws, home))
    return 0


def _require_workspace(ws: str) -> tuple[dict[str, str], Path, Path]:
    n = names(ws)
    if not podman.exists("container", n["agent"]):
        raise podman.PodmanError(f"workspace inexistente: {ws} (use 'up')")
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(
            f"estado ausente para {ws}; recrie o workspace com 'up'")
    return n, home, origin


def suspend(ws: str) -> int:
    """Para o workspace: desabilita e para o target systemd e verifica que todos os containers pararam.

    Delega a orquestracao a `WorkspaceRuntime.suspend()` (Tarefa 4 da
    decomposicao de modulos) a partir da resolucao de `n`, que fica aqui —
    e validacao de fachada (`_require_workspace`), nao orquestracao de
    recursos. A impressao e a politica de codigo de saida continuam aqui
    tambem (Interfaces do brief): o metodo do runtime so devolve um
    resultado, nunca imprime.
    """
    n, _, _ = _require_workspace(ws)
    result = WorkspaceRuntime().suspend(ws, n)
    for warning in result.warnings:
        print(warning, file=sys.stderr)
    if not result.ok:
        print(result.error, file=sys.stderr)
        return 1
    return 0


def resume(root: Path, ws: str) -> int:
    """Religa o workspace pelo systemd.

    Verifica a conectividade do host, garante o keyring, habilita o target,
    executa reset-failed nas unidades do workspace e inicia o target. O JSON
    de conexao so e emitido depois que readiness.probe_workspace reporta tudo
    saudavel.

    Delega a orquestracao a `WorkspaceRuntime.resume()` (Tarefa 4 da
    decomposicao de modulos) a partir da resolucao de `layout`, que fica
    aqui — e validacao de fachada (`_require_workspace`/`layout_for`), nao
    orquestracao de recursos. A impressao, a politica de codigo de saida e
    a chamada a `emit()` continuam aqui tambem (Interfaces do brief): o
    metodo do runtime so devolve um resultado, nunca imprime nem emite.
    """
    _, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)
    result = WorkspaceRuntime().resume(root, ws, layout)
    if not result.ok:
        print(result.error, file=sys.stderr)
        return 1
    return emit(ws, layout)


def reload_allowlist(root: Path, ws: str) -> int:
    """Recarrega a allowlist do proxy sem tocar no container do agente.

    Preserva a porta SSH publicada (evita desconexao de sessoes do Orca).
    Regenera squid.conf a partir do .agent-sandbox.toml e reinicia o proxy.
    """
    n, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)
    # SEMPRE o perfil do checkout do operador, NUNCA o do clone. O clone vive
    # dentro do mount gravavel e o agente o edita a vontade; preferi-lo faria
    # do operador o carteiro da politica do agente, que acrescentaria um
    # dominio ao proprio .agent-sandbox.toml e esperaria o proximo reload.
    # E a mesma invariante que poe `state/` fora do mount (workspace.py), e a
    # mesma fonte que o `up` usa — as duas rotas nao podem divergir.
    profile = load_profile(origin)
    conf = layout.state / "squid.conf"
    conf.write_text(render(profile,
                           root / "image" / "squid" / "allowlist-base.txt",
                           root / "image" / "squid" / "squid.conf.tmpl"))
    conf.chmod(0o644)
    # Pela unidade, nunca `podman restart`: o proxy roda sob `start --attach`
    # da unidade, e o ExecStopPost dela derrubaria o container recem-reiniciado.
    # `try-restart` nao sobe o proxy de um workspace suspenso; o `resume` le o
    # squid.conf novo.
    subprocess.run(["systemctl", "--user", "try-restart", f"{n['proxy']}.service"],
                   check=True)
    print(f"allowlist recarregada para {ws} (proxy reiniciado, agente preservado)")
    return 0


def pull(ws: str) -> int:
    """Traz o trabalho do workspace para o checkout primario, SEM merge.

    O operador testa e faz o push. Se precisar de ajuste, o workspace continua
    vivo, o agente commita mais, e um novo pull traz a diferenca — e por isso
    que o merge nao acontece aqui.
    """
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    layout = layout_for(origin, ws, home)
    # O checkout do workspace e ESCRITO pelo agente: o nome do branch que
    # dele sai so chega ao `git fetch` do host validado, depois do `--` e
    # como ref completa. `runner` resolve `subprocess.run` na hora da
    # chamada (os testes o simulam).
    sandbox = GitRepository(layout.project_root, runner=subprocess.run)
    host = GitRepository(origin, runner=subprocess.run)
    try:
        branch = sandbox.symbolic_branch()
        if branch is None:
            raise podman.PodmanError(
                f"o checkout de {ws} nao esta em um branch (HEAD destacado): "
                f"{layout.project_root}; faca checkout de um branch e repita")
        if not sandbox.valid_branch_name(branch):
            raise podman.PodmanError(
                f"nome de branch recusado no checkout de {ws}: {branch!r}")
        dest = f"refs/asb/{ws}/{branch}"
        if not host.valid_ref(dest):
            raise podman.PodmanError(f"ref de destino recusada: {dest!r}")
    except GitError as error:
        raise podman.PodmanError(str(error)) from error
    subprocess.run(["git", "-C", str(origin), "fetch", "--",
                    str(layout.project_root), f"refs/heads/{branch}:{dest}"],
                   check=True)
    print(f"buscado em {origin}: refs/asb/{ws}/{branch}\n"
          f"  revise:  git -C {origin} log refs/asb/{ws}/{branch}\n"
          f"  integre: git -C {origin} merge refs/asb/{ws}/{branch}",
          file=sys.stderr)
    return 0


def purge(ws: str, confirmed: bool) -> int:
    """Remove tambem os ARQUIVOS do workspace. Irreversivel, logo explicito."""
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    # `down` apaga o estado, mas PRESERVA os volumes de sessao e de containers
    # aninhados. Sem este ramo, um `purge` depois de um `down` so respondia
    # "workspace desconhecido" e os volumes ficavam orfaos, sem nenhum comando
    # do CLI capaz de remove-los.
    layout = layout_for(origin, ws, home) if origin is not None else None
    leftovers = [v for v in (names(ws)["session"], f"asb-{ws}-containers")
                 if podman.exists("volume", v)]
    if layout is None and not leftovers:
        # Nada com este nome existe: e engano de digitacao, nao um workspace
        # derrubado. Sucesso silencioso aqui esconderia o erro do operador.
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    if not confirmed:
        alvo = layout.mount if layout is not None else f"os volumes de {ws}"
        raise podman.PodmanError(
            f"purge apaga {alvo}, incluindo commits que ainda nao "
            f"voltaram para o host. Rode 'asb-agent pull --workspace {ws}' "
            "antes, e repita com --yes se for isso mesmo.")
    down(ws)
    # O estado de sessao deste workspace some junto com os arquivos dele — e
    # so aqui. `down` preserva o trabalho, entao um `down`/`up` mantem as
    # transcricoes. Este volume nunca guarda credencial: a credencial vive no
    # volume compartilhado, que purge algum jamais toca.
    for volume in leftovers:
        podman.run("volume", "rm", "-f", volume, check=False)
    if layout is None:
        print(f"removidos os volumes de {ws}; os arquivos do workspace ja "
              "tinham saido com um 'down' anterior", file=sys.stderr)
        return 0
    remove_workspace(layout)
    print(f"removido: {layout.mount}", file=sys.stderr)
    return 0


def login(root: Path, provider: str = "all") -> int:
    """Reexport de `auth.login` (Tarefa A3).

    O fluxo de login inteiro mudou de casa: ele vive agora ao lado do
    diagnostico que o verifica, em `cli/asb/auth.py`, e nao mais no meio do
    ciclo de vida dos workspaces. Este invólucro existe apenas para nao
    quebrar quem ja importava `lifecycle.login`; o import e adiado porque
    `auth` importa `lifecycle`.

    A tabela `LOGIN_CHECKS` que ficava aqui foi REMOVIDA, e nao migrada: as
    checagens `claude -p ping` e `agy -p ping` mandavam um PROMPT ao modelo
    para descobrir se havia sessao, e A1 mediu que a do agy bloqueia 60s
    quando deslogado. A verificacao correta e `auth.verify_fresh_client`, que
    pergunta a um cliente NOVO usando o status nativo do fornecedor.
    """
    from . import auth

    return auth.login(root, provider)


def list_workspaces() -> int:
    home = Path(os.path.expanduser("~"))
    root = home / ".local" / "state" / "agent-sandbox"
    found = False
    for state in sorted(root.glob("*/origin")) if root.is_dir() else []:
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            status = "sem container"
        else:
            status = "rodando" if podman.running(agent) else "parado"
        print(f"{ws}\t{status}\t{state.read_text().strip()}")
        found = True
    if not found:
        print("nenhum workspace", file=sys.stderr)
    return 0
