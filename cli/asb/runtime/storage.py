"""cli/asb/runtime/storage.py — dona dos volumes de credencial, sessao e
cache de ferramentas, e dos argumentos de mount que os expoem ao agente.

Extraido de cli/asb/lifecycle.py (Tarefa 3 da decomposicao de modulos) sem
mudar nomes de volume, ordem dos argumentos de mount, modos de diretorio,
argv de subprocesso nem texto de aviso: mesmo comportamento, casa nova.
`lifecycle.py` reexporta estes nomes (mesmo padrao ja usado para a extracao
do keyring, Tarefa A2) para quem ja importava daqui; `RuntimeStorage` e a
fronteira nova que `lifecycle.prepare_workspace` passa a usar.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import podman

if TYPE_CHECKING:
    # Import so de tipo. A regra real do R4 (corrigida na revisao da
    # Tarefa 4, ronda 1): nenhum modulo de `runtime/` importa `lifecycle`
    # no NIVEL DE MODULO (isso fecharia um ciclo, ja que `lifecycle.py`
    # importa varios nomes de `runtime/` no proprio nivel de modulo);
    # import ADIADO (dentro de funcao/metodo, `from .. import lifecycle`)
    # e o padrao estabelecido neste pacote — `runtime/sandbox.py` e
    # `runtime/workspace.py` fazem o mesmo. `WorkspaceTransaction` mora em
    # runtime/transaction.py desde a Tarefa 4; dentro de `runtime/` isto
    # nao e ciclo (so entre `runtime/` e `lifecycle.py`), entao o import de
    # tipo pode ser direto, sem tardio.
    from .transaction import WorkspaceTransaction

CREDENTIALS_VOLUME = os.environ.get("ASB_CREDENTIALS_VOLUME", "asb-credentials")
TOOLCACHE_VOLUME = "asb-toolcache"


# Um DIRETORIO por fornecedor dentro do volume de credenciais, montado sobre
# o diretorio de configuracao correspondente no home.
#
# A1 provou por que tem de ser diretorio: `rename`/`os.replace` sobre um
# SYMLINK substitui o proprio symlink e corta o vinculo com o volume, e sobre
# um arquivo BIND-MONTADO o mesmo `rename` falha com EBUSY. Só o diretorio
# montado sobrevive ao padrao de escrita real dos fornecedores. O Claude ainda
# soma um segundo motivo: ele abre a credencial com `O_RDONLY | O_NOFOLLOW`, e
# num symlink o Linux devolve ELOOP, que ele trata como credencial AUSENTE.
CREDENTIAL_DIRS: dict[str, str] = {"claude": ".claude", "codex": ".codex"}

# Arquivos que o layout ANTIGO (removido na A3) deixava na RAIZ do volume,
# fora de qualquer subdiretorio de fornecedor. O layout novo nao os enxerga,
# entao eles nao sao lidos nem escritos por ninguem — mas continuam legiveis
# em /run/asb-credentials/<nome> por TODO container de agente, porque o volume
# inteiro e montado rw com apenas `keyrings` mascarado. Detectar e AVISAR: a
# politica de migracao (copiar, mover ou deixar) nao e desta funcao, e apagar
# credencial nunca e recuperacao valida.
LEGACY_ROOT_CREDENTIAL_FILES: tuple[str, ...] = (
    "claude.json", "codex-auth.json", ".credentials.json", "auth.json",
    "agy.json", "gemini.json",
)

# Estado de SESSAO por workspace, sobreposto ao diretorio de credencial
# COMPARTILHADO. A credencial precisa ser compartilhada (um login por
# fornecedor, spec); a transcricao nao — e o isolamento entre workspaces
# continua valendo. Cada entrada vira um mount aninhado: o volume do workspace
# entra POR CIMA do subdiretorio correspondente do volume compartilhado.
#
# Medido no podman 6.1 (nao suposto): o mount pai (`~/.claude`) e aplicado
# antes do filho (`~/.claude/projects`); o diretorio de destino NAO precisa
# existir dentro do volume pai (o runtime o cria); e a ORIGEM, sim, precisa
# existir no volume do workspace — dai o mkdir de `ensure_session_volume`.
#
# LIMITE EXPLICITO: so DIRETORIOS entram aqui. Estado de sessao gravado como
# ARQUIVO solto na raiz do diretorio do fornecedor (`~/.claude/history.jsonl`,
# `~/.codex/history.jsonl`) continua compartilhado: sobrepor arquivo exigiria
# bind de arquivo, e A1 mediu que `rename` sobre arquivo bind-montado falha
# com EBUSY — a mesma armadilha que este redesenho existe para sair.
SESSION_STATE_DIRS: dict[str, str] = {
    "claude-projects": ".claude/projects",
    "claude-todos": ".claude/todos",
    "claude-shell-snapshots": ".claude/shell-snapshots",
    "codex-sessions": ".codex/sessions",
}


def ensure_credentials_volume() -> str:
    """Garante que o volume de credenciais EXISTE, e devolve o nome dele.

    Deliberadamente sem efeito no sistema de arquivos: quem so precisa citar o
    volume num mount (o singleton do keyring, por exemplo) chama isto e nao
    mexe em disco. A forma INTERNA do volume e responsabilidade de
    `ensure_credential_dirs`, que so quem monta os subpaths chama.
    """
    vol = os.environ.get("ASB_CREDENTIALS_VOLUME", CREDENTIALS_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


def ensure_credential_dirs(vol: str) -> None:
    """Cria, no host, um diretorio por fornecedor dentro do volume.

    Pelo host porque `volume-subpath` do podman NAO cria o caminho: um subpath
    ausente aborta o `podman run` com "no such file or directory" (medido).
    Pelo host tambem resolve a posse: com `--userns keep-id:uid=1000,gid=1000`
    o usuario do host mapeia para o uid 1000 do container, entao o diretorio
    criado aqui ja chega gravavel para o agente — o oposto do
    `Permission denied (os error 13)` que o piloto do operador viu num volume
    cujo `_data` pertencia ao uid 0.

    NUNCA cria arquivo de credencial, so diretorio. Era exatamente a criacao
    de arquivo (`: > "$stored"` no entrypoint) que deixava `claude.json` com 0
    bytes: um arquivo que jamais poderia ser lido como JSON e indistinguivel
    de "sem credencial". Tambem nunca remove nem sobrescreve o que ja existe.

    Por ser a unica funcao que enxerga a forma INTERNA do volume, e tambem
    daqui que sai o aviso do layout ANTIGO (credencial na raiz) — avisar, sem
    apagar nem mover.
    """
    mountpoint = _volume_mountpoint(vol)
    _mkdir_private(mountpoint, CREDENTIAL_DIRS, vol)
    warn_about_legacy_credential_layout(mountpoint)


def _volume_mountpoint(vol: str) -> Path:
    raw = podman.out("volume", "inspect", vol, "--format", "{{.Mountpoint}}")
    mountpoint = Path(raw)
    if not mountpoint.is_absolute() or not mountpoint.is_dir():
        # Driver de volume nao-local, ou resposta inesperada do podman. Falhar
        # aqui, com o valor a vista, e melhor que um mkdir num caminho
        # relativo qualquer.
        raise podman.PodmanError(
            f"mountpoint do volume {vol} nao e um diretorio do host: {raw!r}")
    return mountpoint


def _mkdir_private(mountpoint: Path, subs: Iterable[str], vol: str) -> None:
    """`mkdir -m 700` de cada subpath, com erro TRADUZIDO.

    Um volume cujo `_data` pertence ao uid 0 — o estado que o piloto real
    encontrou — fazia `PermissionError` cru subir ate o operador como
    traceback. O rollback do `up` rodava, mas o diagnostico nao existia.
    """
    for sub in subs:
        target = mountpoint / sub
        try:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.chmod(0o700)
        except OSError as exc:
            raise podman.PodmanError(
                f"nao foi possivel preparar {target} no volume {vol}: {exc}. "
                f"O `_data` do volume precisa pertencer ao SEU usuario; um "
                f"`_data` de outro dono vem de um container que escreveu ali "
                f"como root. Devolva a posse com "
                f"'podman unshare chown -R 0:0 {mountpoint}' — dentro do "
                f"`podman unshare` o uid 0 e o seu proprio usuario. Se isso "
                f"falhar com EPERM, o diretorio pertence ao root do host "
                f"(podman rootful escreveu nele) e a correcao pede sudo."
            ) from exc


def warn_about_legacy_credential_layout(mountpoint: Path) -> None:
    """Avisa, alto, quando o volume ainda guarda credencial na RAIZ.

    Esta e a unica funcao que enxerga a forma INTERNA do volume, entao e a
    unica capaz de detectar o layout antigo. Ela NAO apaga, NAO move e NAO
    copia nada: a politica de migracao e de outra tarefa. O silencio e que era
    o defeito — depois de um re-login o volume passa a guardar as DUAS coisas,
    e a copia orfa da raiz continua legivel por todo container de agente.
    """
    try:
        legacy = sorted(
            name for name in LEGACY_ROOT_CREDENTIAL_FILES
            if (mountpoint / name).is_file())
    except OSError:
        return
    if not legacy:
        return
    print(
        "aviso: o volume de credenciais ainda tem arquivos no layout ANTIGO, "
        "na raiz: " + ", ".join(legacy) + ".\n"
        "  Eles NAO sao usados pelo layout novo (um diretorio por fornecedor), "
        "entao o fornecedor correspondente vai pedir login de novo.\n"
        "  Enquanto existirem, seguem legiveis em /run/asb-credentials/<nome> "
        "por qualquer container de agente: se carregam material de credencial "
        "valido, isso e exposicao.\n"
        "  Nada foi apagado nem movido aqui de proposito — decida a migracao e "
        "remova a copia obsoleta voce mesmo, depois de confirmar o login novo.",
        file=sys.stderr)


def credential_mount_args(home: Path) -> list[str]:
    """Argumentos de mount das credenciais, para o agente e para os clientes
    efemeros de login/verificacao.

    `volume-subpath` monta SOMENTE o diretorio do fornecedor: o resto do
    volume — inclusive o subdiretorio legado `keyrings/` — nao aparece por
    este caminho.
    """
    vol = ensure_credentials_volume()
    ensure_credential_dirs(vol)
    args: list[str] = []
    for sub, rel in CREDENTIAL_DIRS.items():
        args += ["--mount",
                 f"type=volume,src={vol},dst={home / rel},"
                 f"volume-subpath={sub},relabel=shared"]
    return args


def ensure_session_volume(ws: str, tx: "WorkspaceTransaction | None" = None) -> str:
    """Volume de estado de sessao DESTE workspace. Um por workspace, sempre.

    Separado do volume de credenciais de proposito: a credencial e uma so,
    compartilhada; a transcricao e de quem a gerou.
    """
    # Import tardio, mesmo padrao de `runtime/sandbox.py::session_volume_
    # mountpoint`: `names()` deriva o nome do volume por workspace e continua
    # em lifecycle.py, entao so pode ser resolvido aqui em tempo de chamada,
    # nunca no topo do modulo (ciclo de import, R4 do controlador).
    from .. import lifecycle

    vol = lifecycle.names(ws)["session"]
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
        if tx is not None:
            tx.record_volume(vol)
    mountpoint = _volume_mountpoint(vol)
    # A ORIGEM do subpath precisa existir: `volume-subpath` nao a cria (A1).
    _mkdir_private(mountpoint, SESSION_STATE_DIRS, vol)
    return vol


def session_mount_args(vol: str, home: Path) -> list[str]:
    """Mounts que sobrepoem o estado de sessao do workspace ao diretorio de
    credencial compartilhado.

    Cada um entra POR CIMA de um subdiretorio de `~/.claude` / `~/.codex`, que
    sao eles mesmos mounts do volume compartilhado. O resultado medido: os dois
    workspaces leem a MESMA credencial e nenhum dos dois enxerga a transcricao
    do outro.
    """
    args: list[str] = []
    for sub, rel in SESSION_STATE_DIRS.items():
        args += ["--mount",
                 f"type=volume,src={vol},dst={home / rel},"
                 f"volume-subpath={sub},relabel=shared"]
    return args


def ensure_toolcache_volume() -> str:
    vol = os.environ.get("ASB_TOOLCACHE_VOLUME", TOOLCACHE_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


@dataclass
class RuntimeStorage:
    """Fronteira injetavel para os volumes que `lifecycle.prepare_workspace`
    monta no agente: credenciais, sessao e cache de ferramentas.

    So encapsula os cinco pontos de entrada acima; nao reimplementa nada. O
    `home` do operador entra uma vez, no construtor, porque nao muda durante
    a preparacao de um workspace — os demais parametros (workspace, volume de
    sessao) continuam explicitos em cada chamada, porque esses SIM variam por
    invocacao.
    """

    home: Path

    def ensure_credentials(self) -> str:
        return ensure_credentials_volume()

    def credential_mounts(self) -> list[str]:
        return credential_mount_args(self.home)

    def ensure_sessions(self, workspace: str,
                        transaction: "WorkspaceTransaction | None" = None) -> str:
        return ensure_session_volume(workspace, transaction)

    def session_mounts(self, vol: str) -> list[str]:
        return session_mount_args(vol, self.home)

    def ensure_toolcache(self) -> str:
        return ensure_toolcache_volume()
