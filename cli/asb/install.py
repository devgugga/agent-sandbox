"""cli/asb/install.py — o que o sandbox instala no host.

Regra da §16: tudo aqui e idempotente, reexecutavel, e NAO grava o caminho
absoluto deste checkout em arquivo de sistema algum. No v1 o ExecStart da
unidade systemd tinha o caminho assado, e mover a pasta quebrava a restauracao
no boot em silencio.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

BROKER_SCRIPT = Path("/usr/local/lib/asb-docker-broker.py")
BROKER_UNIT = Path("/etc/systemd/system/asb-docker-broker.service")
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
PODMAN_RESTART_UNIT = Path("/usr/lib/systemd/user/podman-restart.service")
PROJECT_DROPIN_HEADER = "# Managed by agent-sandbox: podman-restart netns initialization\n"


def podman_restart(target_dir: Path | None = None) -> int:
    """Habilita a unidade que o proprio podman ja instala.

    `podman start --all --filter should-start-on-boot=true`, puxada por
    default.target e ordenada apos network-online.target. Substitui inteiros o
    restore-all do v1, a espera por rota/DNS do host, a unidade customizada e o
    codigo de saida 2 para pods legados — e, por nao ser nossa, nao carrega
    caminho nenhum deste checkout.

    Sem linger de proposito: o Orca so roda apos o login, entao uma unidade que
    parte no login e cedo o bastante.
    """
    if not PODMAN_RESTART_UNIT.is_file():
        print("podman-restart.service nao encontrado; sem restauracao "
              "automatica no boot. Use 'asb-agent resume' apos religar.",
              file=sys.stderr)
        return 1

    podman_bin = shutil.which("podman")
    if not podman_bin:
        print("podman nao encontrado no PATH", file=sys.stderr)
        return 1

    true_bin = shutil.which("true")
    if not true_bin:
        print("true nao encontrado no PATH", file=sys.stderr)
        return 1

    base = target_dir or (Path.home() / ".config" / "systemd" / "user")
    dropin = base / "podman-restart.service.d" / "agent-sandbox.conf"
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text(
        PROJECT_DROPIN_HEADER
        + f"[Service]\nExecStartPre={podman_bin} unshare --rootless-netns {true_bin}\n",
        encoding="utf-8",
    )

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "podman-restart.service"],
                   check=True)
    print("restauracao no boot habilitada (podman-restart.service)",
          file=sys.stderr)
    return 0


def get_dropin_path(target_dir: Path | None = None) -> Path:
    """Retorna o caminho do drop-in do podman-restart.service."""
    if target_dir is not None:
        base = target_dir
    elif "ASB_CONFIG_ROOT" in os.environ:
        base = Path(os.environ["ASB_CONFIG_ROOT"]) / "systemd" / "user"
    else:
        base = Path.home() / ".config" / "systemd" / "user"
    return base / "podman-restart.service.d" / "agent-sandbox.conf"


def _is_project_dropin(content: str) -> bool:
    """O conteudo e um dos drop-ins que este projeto ja instalou (com ou sem cabecalho)?"""
    podman_bin = shutil.which("podman") or "/usr/bin/podman"
    true_bin = shutil.which("true") or "/usr/bin/true"
    canonical = {
        f"[Service]\nExecStartPre={podman_bin} unshare --rootless-netns {true_bin}",
        "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true",
        "[Service]\nExecStartPre=/bin/true",
    }
    if content.startswith(PROJECT_DROPIN_HEADER):
        content = content[len(PROJECT_DROPIN_HEADER):]
    return content.strip() in canonical


def _read_regular_at(dir_fd: int, name: str) -> tuple[os.stat_result, str] | None:
    """(stat, conteudo) do arquivo regular `name` sob `dir_fd`, sem seguir symlink.

    None somente quando ali nao ha arquivo regular: entrada ausente, symlink
    (ELOOP com O_NOFOLLOW) ou entrada nao regular. Qualquer outro erro
    (EACCES, EIO) levanta: tratar "ilegivel" como "ausente" faria a adocao
    seguir com o drop-in legado ainda ativo.

    `O_NONBLOCK` e obrigatorio, nao decorativo. `O_NOFOLLOW` so restringe
    symlink; num FIFO o `open(2)` para leitura BLOQUEIA no kernel enquanto nao
    houver escritor — antes de `fstat` e portanto antes do `S_ISREG` que
    rejeitaria a entrada. Medido: um FIFO no nome do drop-in travava esta
    funcao indefinidamente. E como as duas chamadas de producao rodam dentro do
    `_AdoptionLock`, que segura um `flock` exclusivo durante todo o `with`, o
    travamento levaria o lock consigo e nenhuma adocao de keyring voltaria a
    rodar no host — exatamente o que o invariante 3 do brief proibe ("sem
    travar indefinidamente"). Com `O_NONBLOCK` o FIFO abre na hora e cai no
    `S_ISREG`; em arquivo regular a flag e inerte.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None
        raise RuntimeError(f"drop-in ilegivel ({name}): {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        with open(fd, "rb", closefd=False) as fh:
            return st, fh.read().decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def read_project_dropin(
    target_dir: Path | None = None,
) -> tuple[bool, bool, str | None, int | None]:
    """(existe, pertence_ao_projeto, conteudo, modo) numa unica leitura.

    Uma leitura, um inode: quem precisa do conteudo e do modo para gravar
    baseline nao pode obte-los em tres chamadas separadas — `read_text()` e
    `stat()` depois de `check_project_dropin()` seguem symlink e podem cair
    noutro arquivo, e um baseline colhido de arquivo alheio e restaurado de
    volta como se fosse nosso. Aqui conteudo e modo saem do mesmo descritor
    aberto com `O_NOFOLLOW` que decidiu a existencia.
    """
    dropin = get_dropin_path(target_dir)
    try:
        dir_fd = os.open(dropin.parent, os.O_RDONLY | os.O_DIRECTORY)
    except FileNotFoundError:
        return False, False, None, None
    except OSError as exc:
        raise RuntimeError(f"diretorio do drop-in ilegivel ({dropin.parent}): {exc}") from exc
    try:
        found = _read_regular_at(dir_fd, dropin.name)
    finally:
        os.close(dir_fd)
    if found is None:
        return False, False, None, None
    st, content = found
    return True, _is_project_dropin(content), content, st.st_mode & 0o777


def check_project_dropin(target_dir: Path | None = None) -> tuple[bool, bool]:
    """Retorna (existe, pertence_ao_projeto)."""
    exists, ours, _, _ = read_project_dropin(target_dir)
    return exists, ours


def remove_project_dropin(
    target_dir: Path | None = None,
    expected_content: str | None = None,
    expected_mode: int | None = None,
    verify: Callable[[], None] | None = None,
) -> bool:
    """Remove o drop-in legado apenas se pertencer ao projeto e coincidir com o baseline.

    POSIX nao oferece "comparar e remover" atomico para uma entrada de
    diretorio, e este codigo nao promete isso. O contrato verificavel e
    outro: a entrada validada e movida por rename(2) para um nome de
    quarentena no mesmo diretorio e SO ENTAO comparada (inode, modo e
    conteudo) ao que foi validado. Se alguem trocou a entrada entre a
    validacao e o rename, o que foi para a quarentena e o arquivo alheio: ele
    volta ao nome original por link(2), que nunca sobrescreve, e a remocao
    recusa fail-closed.

    `verify` e o gancho de revalidacao do chamador, chamado imediatamente
    antes de CADA mutacao desta funcao: o rename(2) da quarentena, o unlink da
    quarentena e o daemon-reload. As tres acontecem DEPOIS de o chamador ter
    autorizado a entrada aqui; sem o gancho, uma identidade que deixou de
    valer nesse intervalo ainda as veria acontecer. O rename e a PRIMEIRA
    delas, e precisa do gancho tanto quanto as outras duas: entre a
    autorizacao do chamador e esta linha correm a leitura do arquivo, a
    classificacao de autoria e as comparacoes de conteudo e modo. Levantar
    dentro do gancho aborta a remocao sem mutar nada.

    O unlink final tambem confere o inode do nome de quarentena logo antes de
    remover, porque quem observa o diretorio pode reapontar esse nome depois
    da validacao; divergindo, nada e removido. E, apos remover, o nome
    original e relido, e ausencia e o unico estado que libera: um drop-in do
    projeto de volta ali, ou um symlink/entrada nao-regular ocupando o nome
    (que o systemd seguiria dentro de um `.d`), significam que a remocao nao
    entregou o contrato, e a funcao recusa em vez de devolver True.

    Nenhum arquivo colocado no nome original depois da
    validacao e removido.

    Preserva arquivos e configuracoes alheias. Nao desabilita o
    podman-restart.service globalmente.
    """
    dropin = get_dropin_path(target_dir)
    parent = dropin.parent
    try:
        dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"diretorio do drop-in ilegivel ({parent}): {exc}") from exc

    try:
        found = _read_regular_at(dir_fd, dropin.name)
        if found is None:
            return False
        st, current_content = found
        if not _is_project_dropin(current_content):
            return False
        if expected_content is not None and current_content != expected_content:
            raise RuntimeError("drop-in alterado externamente antes da remocao; recusa fail-closed")
        if expected_mode is not None and (st.st_mode & 0o777) != (expected_mode & 0o777):
            raise RuntimeError("modo do drop-in alterado externamente antes da remocao; recusa fail-closed")

        quarantine = f".{dropin.name}.asb-remove-{os.getpid()}-{os.urandom(4).hex()}"
        if verify is not None:
            verify()
        try:
            os.rename(dropin.name, quarantine, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except OSError as exc:
            raise RuntimeError(f"falha ao mover drop-in para quarentena: {exc}") from exc

        # Ilegivel e substituido levam ao mesmo desfecho seguro — devolver ao
        # nome original e recusar — mas nao podem dar o mesmo diagnostico:
        # acusar troca quando houve falha de leitura manda o operador cacar um
        # invasor que nao existe.
        unreadable: str | None = None
        try:
            moved = _read_regular_at(dir_fd, quarantine)
        except RuntimeError as exc:
            moved, unreadable = None, str(exc)
        if (
            moved is None
            or (moved[0].st_dev, moved[0].st_ino) != (st.st_dev, st.st_ino)
            or (moved[0].st_mode & 0o777) != (st.st_mode & 0o777)
            or moved[1] != current_content
        ):
            causa = (
                f"quarentena ilegivel apos o rename ({unreadable})" if unreadable
                else "drop-in substituido entre a validacao e a remocao"
            )
            try:
                os.link(quarantine, dropin.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
                os.unlink(quarantine, dir_fd=dir_fd)
            except OSError as exc:
                raise RuntimeError(
                    f"{causa}; o arquivo ficou em {parent / quarantine} ({exc}); recusa fail-closed"
                ) from exc
            raise RuntimeError(
                f"{causa}; arquivo devolvido ao nome original, recusa fail-closed"
            )

        if verify is not None:
            verify()

        # O unlink e por NOME, e o nome da quarentena e visivel no diretorio.
        # Entre a releitura que validou o inode e a remocao, alguem pode
        # reapontar esse nome: o unlink levaria o arquivo alheio enquanto o
        # drop-in validado sobrevive, e a funcao ainda reportaria sucesso.
        # Reconferir a identidade aqui e o mais tarde que da para olhar; a
        # janela restante entre stat(2) e unlink(2) e irredutivel no Linux,
        # que nao tem funlinkat(2) para remover "este inode".
        try:
            pre = os.stat(quarantine, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as exc:
            raise RuntimeError(
                f"quarentena {parent / quarantine} ilegivel antes da remocao ({exc}); recusa fail-closed"
            ) from exc
        if (pre.st_dev, pre.st_ino) != (st.st_dev, st.st_ino) or (pre.st_mode & 0o777) != (st.st_mode & 0o777):
            raise RuntimeError(
                f"nome de quarentena {parent / quarantine} reapontado para outro arquivo antes da remocao; "
                "nada foi removido, recusa fail-closed"
            )

        try:
            os.unlink(quarantine, dir_fd=dir_fd)
        except OSError as exc:
            raise RuntimeError(f"falha ao remover drop-in em quarentena {parent / quarantine}: {exc}") from exc

        # Pos-condicao: o nome original nao pode voltar a ter um drop-in do
        # projeto. Se voltou, a remocao nao entregou o que promete, e dizer
        # `True` aqui faria o chamador seguir como se o podman-restart tivesse
        # sido desarmado.
        # `_read_regular_at` devolve None para tres estados: ausente, symlink e
        # entrada nao-regular. Na releitura da quarentena esse colapso e inocuo,
        # porque todo None leva a recusa. AQUI A POLARIDADE E INVERSA: None cai
        # no caminho de SUCESSO. Como o systemd segue symlink dentro de um `.d`,
        # um symlink plantado no nome depois do unlink faria a funcao reportar
        # "podman-restart desarmado" com o drop-in ainda ativo. Ausencia e o
        # unico estado que libera — e `_require_keyring_phase` ja trata symlink
        # como presente (`is_file() or is_symlink()`).
        try:
            st_back = os.stat(dropin.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            st_back = None
        except OSError as exc:
            raise RuntimeError(
                f"nome do drop-in ilegivel apos a remocao ({exc}); recusa fail-closed"
            ) from exc
        if st_back is not None and not stat.S_ISREG(st_back.st_mode):
            raise RuntimeError(
                f"entrada nao-regular ocupou {dropin} apos a remocao; recusa fail-closed")
        try:
            back = _read_regular_at(dir_fd, dropin.name) if st_back is not None else None
        except RuntimeError as exc:
            raise RuntimeError(
                f"drop-in ilegivel no nome original apos a remocao ({exc}); recusa fail-closed"
            ) from exc
        if back is not None and _is_project_dropin(back[1]):
            raise RuntimeError(
                f"drop-in do projeto reapareceu em {dropin} apos a remocao; recusa fail-closed"
            )
    finally:
        os.close(dir_fd)

    # Remover diretório se ficou vazio
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass

    if verify is not None:
        verify()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return True


def _default_dropin_body() -> str:
    """O drop-in que `podman_restart()` instala, sintetizado a partir do PATH."""
    podman_bin = shutil.which("podman") or "/usr/bin/podman"
    true_bin = shutil.which("true") or "/usr/bin/true"
    return (
        PROJECT_DROPIN_HEADER
        + f"[Service]\nExecStartPre={podman_bin} unshare --rootless-netns {true_bin}\n"
    )


def _fchmod_regular_at(dir_fd: int, name: str, st: os.stat_result, mode: int) -> None:
    """chmod do arquivo regular `name` sob `dir_fd`, pelo descritor.

    Linux nao implementa `AT_SYMLINK_NOFOLLOW` em `fchmodat(2)`, entao
    `os.chmod(..., follow_symlinks=False)` nao existe aqui: a unica forma de
    nao seguir link e abrir com `O_NOFOLLOW` e mudar o modo do descritor. O
    inode aberto ainda e conferido contra o que foi validado, porque entre o
    stat e o open o nome pode ter sido reapontado.
    """
    # `O_NONBLOCK` pelo mesmo motivo de `_read_regular_at`: um FIFO plantado
    # entre a validacao e este reopen bloquearia o open antes do `S_ISREG`.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        cur = os.fstat(fd)
        if not stat.S_ISREG(cur.st_mode) or (cur.st_dev, cur.st_ino) != (st.st_dev, st.st_ino):
            raise RuntimeError(
                f"{name} deixou de ser o arquivo validado antes do chmod; recusa fail-closed")
        os.fchmod(fd, mode & 0o777)
    finally:
        os.close(fd)


def restore_project_dropin(
    target_dir: Path | None = None,
    content: str | None = None,
    mode: int | None = None,
    verify: Callable[[], None] | None = None,
) -> bool:
    """Restaura o drop-in do projeto caso a adocao o tenha removido.

    Toda decisao e toda mutacao acontecem sob um `dir_fd` do diretorio pai e
    SEM seguir symlink. `is_file()`, `read_text()`, `stat()`, `chmod()` e
    `write_text()` seguem link, e seguir link aqui e mudar arquivo alheio: um
    symlink plantado no nome do drop-in fazia esta funcao medir e `chmod` o
    ARQUIVO APONTADO, fora do `.d` do projeto, e um symlink pendurado a fazia
    CRIAR o alvo — nos dois casos violando a preservacao de configuracao de
    terceiros. Entrada existente que nao seja arquivo regular recusa fechado;
    a criacao usa `O_CREAT|O_EXCL|O_NOFOLLOW`, que recusa inclusive o link
    pendurado.

    `verify` e o gancho de revalidacao de identidade do chamador, chamado
    imediatamente antes de cada mutacao: a criacao do diretorio, a escrita do
    arquivo, a correcao de modo e o daemon-reload. Uma unica validacao no
    chamador nao cobre nenhuma delas — todas acontecem depois. Levantar dentro
    do gancho aborta a restauracao antes da mutacao seguinte.
    """
    dropin = get_dropin_path(target_dir)
    parent, name = dropin.parent, dropin.name

    try:
        dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    except FileNotFoundError:
        dir_fd = None
    except OSError as exc:
        raise RuntimeError(f"diretorio do drop-in ilegivel ({parent}): {exc}") from exc

    if dir_fd is not None:
        try:
            try:
                st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                st = None
            except OSError as exc:
                raise RuntimeError(f"nome do drop-in ilegivel ({dropin}): {exc}") from exc

            if st is not None:
                if not stat.S_ISREG(st.st_mode):
                    raise RuntimeError(
                        f"{dropin} e symlink ou entrada nao-regular: restaurar ali mudaria um "
                        "arquivo alheio em vez do drop-in do projeto; recusa fail-closed")
                found = _read_regular_at(dir_fd, name)
                if found is None:
                    raise RuntimeError(
                        f"{dropin} deixou de ser arquivo regular durante a restauracao; "
                        "recusa fail-closed")
                st, cur = found
                if content is not None and cur != content:
                    raise RuntimeError(
                        "drop-in criado/modificado externamente durante supervisao; recusa fail-closed")
                if mode is not None and (st.st_mode & 0o777) != (mode & 0o777):
                    if verify is not None:
                        verify()
                    _fchmod_regular_at(dir_fd, name, st, mode)
                return True
        finally:
            os.close(dir_fd)

    if verify is not None:
        verify()
    parent.mkdir(parents=True, exist_ok=True)
    payload = content if content is not None else _default_dropin_body()

    dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if verify is not None:
            verify()
        try:
            # O_EXCL recusa qualquer entrada que ja ocupe o nome, symlink
            # pendurado incluido — o caso em que `write_text` criava o alvo.
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666,
                         dir_fd=dir_fd)
        except FileExistsError as exc:
            raise RuntimeError(
                f"{dropin} apareceu entre a checagem e a criacao (symlink ou arquivo de "
                f"terceiro): nao foi sobrescrito, recusa fail-closed ({exc})") from exc
        try:
            with open(fd, "wb", closefd=False) as fh:
                fh.write(payload.encode("utf-8"))
            if mode is not None:
                if verify is not None:
                    verify()
                os.fchmod(fd, mode & 0o777)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)

    if verify is not None:
        verify()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return True


def _link(link: Path, dest: Path) -> None:
    """Symlink para o checkout, nunca copia: uma copia envelhece em silencio e
    o agente passa a se comportar diferente do que este repositorio diz."""
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(dest)
    print(f"instalado: {link}", file=sys.stderr)


def guards(root: Path) -> int:
    """Instala os nomes que vao no campo Command do Orca, e o proprio CLI."""
    target = Path.home() / ".local" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for agent in ("claude", "codex", "agy"):
        _link(target / f"asb-{agent}", root / "cli" / "asb-guard")
    # Sem o CLI no PATH o operador so consegue opera-lo de dentro do checkout.
    # O entrypoint ja resolve o proprio caminho com Path(__file__).resolve(),
    # que segue o symlink — o link era a unica peca faltando.
    _link(target / "asb-agent", root / "cli" / "asb-agent")
    print("Em Orca -> Settings -> Agents, troque o campo Command:\n"
          "  claude -> asb-claude | codex -> asb-codex | agy -> asb-agy\n"
          "asb-agent passa a rodar de qualquer diretorio.",
          file=sys.stderr)
    return 0


def broker(root: Path) -> int:
    """Instala o broker so-leitura. Requer sudo, uma vez.

    O script e COPIADO para /usr/local/lib: a unidade nao pode apontar para
    este checkout, senao mover a pasta quebraria o servico em silencio — o
    mesmo erro que o v1 cometeu com o ExecStart do restore (spec §16.1).
    """
    source = root / "broker" / "asb-docker-broker.py"
    docker_sock = next((s for s in DOCKER_SOCKETS if Path(s).exists()), None)
    if docker_sock is None:
        print("socket do Docker nao encontrado; nada a instalar. O eixo "
              "host_api fica indisponivel; os outros dois seguem normais.",
              file=sys.stderr)
        return 1

    unit = (root / "broker" / "asb-docker-broker.service.tmpl").read_text()
    unit = (unit.replace("__PYTHON__", sys.executable)
                .replace("__SCRIPT__", str(BROKER_SCRIPT))
                .replace("__DOCKER_SOCK__", docker_sock)
                .replace("__UID__", str(os.getuid())))

    print(f"instalando o broker (socket real: {docker_sock}).", file=sys.stderr)
    print("Isso concede LEITURA de Docker sem senha ao seu usuario: ps, logs, "
          "inspect. Mutacao recebe 403 e nao e configuravel.", file=sys.stderr)
    subprocess.run(["sudo", "install", "-m", "0755", str(source),
                    str(BROKER_SCRIPT)], check=True)
    subprocess.run(["sudo", "tee", str(BROKER_UNIT)], input=unit, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now",
                    "asb-docker-broker.service"], check=True)
    print("broker instalado. Habilite por projeto com [docker] host_api = "
          '"read" no .agent-sandbox.toml.', file=sys.stderr)
    return 0


# Scripts gerados no runtime versionado. Fazem parte do conjunto esperado
# (runtime_manifest), derivado do checkout e nunca do diretorio instalado.
_LAUNCHER_SH = (
    "#!/bin/sh\n"
    "set -eu\n"
    "podman_bin=\"$(command -v podman || echo /usr/bin/podman)\"\n"
    "container=\"\"\n"
    "for arg in \"$@\"; do\n"
    "    case \"$arg\" in\n"
    "        --attach|--sig-proxy=false|--sig-proxy=*|start)\n"
    "            ;;\n"
    "        *)\n"
    "            container=\"$arg\"\n"
    "            ;;\n"
    "    esac\n"
    "done\n"
    "if [ -z \"$container\" ]; then\n"
    "    echo \"asb-launcher: missing container name\" >&2\n"
    "    exit 2\n"
    "fi\n"
    "status=$(\"$podman_bin\" inspect \"$container\" --format '{{.State.Status}}')\n"
    "if [ \"$status\" = \"running\" ]; then\n"
    "    exec \"$podman_bin\" attach --sig-proxy=false \"$container\"\n"
    "elif [ \"$status\" = \"created\" ] || [ \"$status\" = \"exited\" ] || [ \"$status\" = \"stopped\" ]; then\n"
    "    exec \"$podman_bin\" start --attach --sig-proxy=false \"$container\"\n"
    "else\n"
    "    echo \"asb-launcher: container '$container' em estado inesperado ou inspecao falhou: $status\" >&2\n"
    "    exit 1\n"
    "fi\n"
)

_RUNTIME_CHECK_PY = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "runtime_dir = Path(__file__).resolve().parent\n"
    "if str(runtime_dir) not in sys.path:\n"
    "    sys.path.insert(0, str(runtime_dir))\n"
    "\n"
    "from asb.runtime_check import main\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    sys.exit(main())\n"
)

_NETWORK_GATE_PY = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "runtime_dir = Path(__file__).resolve().parent\n"
    "if str(runtime_dir) not in sys.path:\n"
    "    sys.path.insert(0, str(runtime_dir))\n"
    "\n"
    "from asb.network_gate import main\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    sys.exit(main())\n"
)


def runtime_payload(root: Path) -> dict[str, tuple[bytes, int]]:
    """Arquivos do runtime versionado derivados do checkout: caminho relativo -> (bytes, modo)."""
    src_asb = root / "cli" / "asb"
    if not src_asb.is_dir():
        raise FileNotFoundError(f"Pacote asb nao encontrado em {src_asb}")
    payload = {
        "launcher.sh": (_LAUNCHER_SH.encode("utf-8"), 0o755),
        "runtime_check.py": (_RUNTIME_CHECK_PY.encode("utf-8"), 0o755),
        "network_gate.py": (_NETWORK_GATE_PY.encode("utf-8"), 0o755),
    }
    for path in sorted(src_asb.rglob("*")):
        rel = path.relative_to(src_asb)
        if "__pycache__" in rel.parts or path.suffix == ".pyc" or not path.is_file():
            continue
        payload[f"asb/{rel.as_posix()}"] = (path.read_bytes(), path.stat().st_mode & 0o777)
    return payload


def _manifest_of(payload: dict[str, tuple[bytes, int]], revision: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "revision": revision,
        "files": {
            rel: {"sha256": hashlib.sha256(data).hexdigest(), "mode": mode}
            for rel, (data, mode) in sorted(payload.items())
        },
    }


def runtime_manifest(root: Path, revision: str) -> dict[str, object]:
    """Manifesto ESPERADO do runtime `revision`, calculado a partir do checkout."""
    return _manifest_of(runtime_payload(root), revision)


def install_runtime(
    root: Path,
    revision: str,
    target_base: Path | None = None,
) -> Path:
    """Instala o runtime versionado em ~/.local/lib/agent-sandbox/runtime/<revisao>/.

    Garante cópia independente (sem symlinks para o checkout), idempotência
    atômica e escrita dos scripts helper (launcher e runtime_check).
    """
    if not revision or not isinstance(revision, str):
        raise ValueError("Revisao nao pode ser vazia")
    if any(c in revision for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise ValueError(f"Revisao invalida ou insegura: {revision!r}")

    base = (
        target_base
        if target_base is not None
        else (Path.home() / ".local" / "lib" / "agent-sandbox" / "runtime")
    )
    dest = base / revision
    base.mkdir(parents=True, exist_ok=True)

    staging = base / f".staging-{revision}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        payload = runtime_payload(root)
        for rel, (data, mode) in payload.items():
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        (staging / "manifest.json").write_text(
            json.dumps(_manifest_of(payload, revision), indent=2), encoding="utf-8")

        # Troca atômica de staging para dest
        if dest.exists():
            backup = base / f".old-{revision}-{os.getpid()}"
            dest.rename(backup)
            staging.rename(dest)
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.rename(dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return dest
