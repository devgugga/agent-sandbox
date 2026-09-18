"""cli/asb/projects/registry.py — registro atomico de projetos e checkouts.

Persiste, sob lock exclusivo `fcntl`, o mapeamento entre a identidade de um
projeto (derivada do `git rev-parse --git-common-dir` canonico) e os
checkouts que um operador vinculou a ele. Git, Podman, systemd e tmux
continuam sendo a fonte de verdade sobre o que existe de fato; este registro
guarda apenas o relacionamento.

A identidade de projeto e estavel entre o checkout primario e qualquer
worktree vinculado: ambos compartilham o mesmo diretorio `.git` comum, entao
`git rev-parse --path-format=absolute --git-common-dir` devolve o mesmo
caminho canonico nos dois casos, e o id derivado dele (prefixo SHA-256)
tambem coincide — isso e o que garante a deduplicacao.

O checkout de execucao da sandbox NUNCA e guardado aqui: ele e sempre
resolvido ao vivo a partir de `ConnectionInfo.project_root` por uma camada
posterior. `CheckoutBinding.source_path` e so o caminho de checkout do
operador.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from asb.checkouts.model import CheckoutId
from asb.projects.model import Project, ProjectId
from asb.workspace import _sanitize, workspace_id

_SCHEMA_VERSION = 1
_GIT_TIMEOUT_SECONDS = 10.0
_T = TypeVar("_T")

# (project, checkouts-do-projeto) na ordem em que aparecem no arquivo.
_ProjectEntry = tuple[Project, list["CheckoutBinding"]]


class ProjectRegistryError(Exception):
    """Falha ao resolver identidade de projeto ou ao ler/gravar o registro."""


@dataclass(frozen=True)
class CheckoutBinding:
    """Vinculo entre um checkout do operador e um projeto do registro."""

    checkout_id: CheckoutId
    project_id: ProjectId
    source_path: Path
    workspace: str


def _git_common_dir(path: Path) -> Path:
    """Diretorio `.git` comum e canonico de `path`, ou levanta o erro do módulo."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            shell=False, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProjectRegistryError(
            f"could not invoke git in {path}: {exc}") from exc
    if completed.returncode != 0:
        raise ProjectRegistryError(
            f"{path} is not a git checkout: {completed.stderr.strip()}")
    common_dir = completed.stdout.strip()
    if not common_dir:
        raise ProjectRegistryError(
            f"git returned no common directory for {path}")
    return Path(common_dir)


def _checkout_workspace(source_path: Path) -> str:
    """Nome de workspace deterministico de um checkout, ou levanta.

    Env VAZIO de proposito: um workspace criado pelo Orca tem outro nome
    (ORCA_VM_INSTANCE_ID) e nunca e adotado. O nome so e aceito se for a
    propria forma sanitizada, e nao vazio — o mesmo formato que
    `workspace._sanitize` produz."""
    name = workspace_id(source_path, {})
    if not name or _sanitize(name) != name:
        raise ProjectRegistryError(
            f"unsafe workspace name {name!r} derived from {source_path}")
    return name


def _project_id_for(common_dir: Path) -> ProjectId:
    digest = hashlib.sha256(str(common_dir).encode("utf-8")).hexdigest()
    return ProjectId(f"p-{digest[:16]}")


def _discover_integration_branch(path: Path) -> str:
    """Integration branch from `refs/remotes/origin/HEAD`, or raises.

    Only ever called when the caller did not supply an explicit branch.
    `git symbolic-ref --short` fails (non-zero exit) when the ref is
    missing, unreadable, or ambiguous, instead of guessing — so any
    failure here is turned into a `ProjectRegistryError` that demands an
    explicit choice, rather than a silent default.
    """
    try:
        completed = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=str(path), shell=False, capture_output=True, text=True,
        )
    except OSError as exc:
        raise ProjectRegistryError(
            "could not invoke git to discover the integration branch for "
            f"{path}: {exc}") from exc
    if completed.returncode != 0:
        raise ProjectRegistryError(
            f"no integration branch configured for {path} and "
            "refs/remotes/origin/HEAD could not be resolved "
            f"({completed.stderr.strip()}); supply integration_branch "
            "explicitly")
    ref = completed.stdout.strip()
    branch = ref[len("origin/"):] if ref.startswith("origin/") else ""
    if not branch:
        raise ProjectRegistryError(
            f"no integration branch configured for {path}: "
            f"refs/remotes/origin/HEAD resolved to unexpected ref {ref!r}; "
            "supply integration_branch explicitly")
    return branch


class ProjectRegistry:
    """Registro atomico, sem estado em memoria, de projetos e checkouts.

    Cada chamada le o arquivo do zero (ou o trata como vazio, se ele ainda
    nao existe) e cada escrita e feita sob um lock `fcntl` exclusivo,
    recarregando dentro do lock antes de gravar — duas instancias apontando
    para o mesmo `path` (inclusive de processos diferentes) nunca perdem a
    escrita uma da outra.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # -- leitura ----------------------------------------------------------

    def list(self) -> list[Project]:
        return [project for project, _ in self._load()]

    def get(self, project_id: ProjectId) -> Project:
        for project, _ in self._load():
            if project.id == project_id:
                return project
        raise ProjectRegistryError(f"unknown project id: {project_id}")

    def bindings(self, project_id: ProjectId) -> list[CheckoutBinding]:
        for project, checkouts in self._load():
            if project.id == project_id:
                return list(checkouts)
        raise ProjectRegistryError(f"unknown project id: {project_id}")

    def checkout(self, checkout_id: CheckoutId) -> CheckoutBinding:
        """O vinculo com esta identidade estavel, em qualquer projeto."""
        for _, checkouts in self._load():
            for binding in checkouts:
                if binding.checkout_id == checkout_id:
                    return binding
        raise ProjectRegistryError(f"unknown checkout id: {checkout_id}")

    # -- escrita ------------------------------------------------------------

    def add(self, primary: Path, integration_branch: str | None,
            worktree_root: Path) -> Project:
        primary = Path(primary).resolve()
        common_dir = _git_common_dir(primary)
        project_id = _project_id_for(common_dir)
        branch = (integration_branch if integration_branch
                 else _discover_integration_branch(primary))
        worktree_root = Path(worktree_root).resolve()

        def mutate(entries: list[_ProjectEntry]) -> Project:
            for project, _ in entries:
                if project.id == project_id:
                    return project  # add() e idempotente: entrada existente vence.
            new_project = Project(
                id=project_id,
                primary=primary,
                integration_branch=branch,
                worktree_root=worktree_root,
                git_common_dir=common_dir,
            )
            entries.append((new_project, []))
            return new_project

        return self._transact(mutate)

    def remove(self, project_id: ProjectId) -> None:
        def mutate(entries: list[_ProjectEntry]) -> None:
            entries[:] = [entry for entry in entries
                          if entry[0].id != project_id]

        self._transact(mutate)

    def register_checkout(self, project_id: ProjectId,
                          source_path: Path) -> CheckoutBinding:
        """Registro idempotente de um checkout do operador.

        Um caminho (resolvido) ja registrado no projeto devolve o vinculo
        existente, intacto; senao cunha UM `CheckoutId` e o persiste junto
        com o nome de workspace deterministico do caminho. Nenhum chamador
        escolhe o workspace: ele vem de `workspace_id(path, {})` — nunca das
        variaveis do Orca — e e validado antes de gravar.

        Recusa, antes de qualquer escrita, um caminho de OUTRO repositorio:
        o diretorio `.git` comum dele tem de ser o do projeto."""
        source_path = Path(source_path).resolve()
        workspace = _checkout_workspace(source_path)
        project = self.get(project_id)
        # Um registro antigo sem `gitCommonDir` e conferido contra o do
        # primario, ao vivo: a checagem nunca e pulada.
        expected = (project.git_common_dir
                    or _git_common_dir(project.primary)).resolve()
        actual = _git_common_dir(source_path).resolve()
        if actual != expected:
            raise ProjectRegistryError(
                f"{source_path} belongs to another repository ({actual}), "
                f"not to project {project_id} ({expected})")

        def mutate(entries: list[_ProjectEntry]) -> CheckoutBinding:
            for project, checkouts in entries:
                if project.id == project_id:
                    for binding in checkouts:
                        if binding.source_path == source_path:
                            return binding
                    binding = CheckoutBinding(
                        checkout_id=CheckoutId(f"c-{secrets.token_hex(8)}"),
                        project_id=project_id,
                        source_path=source_path,
                        workspace=workspace,
                    )
                    checkouts.append(binding)
                    return binding
            raise ProjectRegistryError(f"unknown project id: {project_id}")

        return self._transact(mutate)

    def unbind_checkout(self, checkout_id: CheckoutId) -> None:
        def mutate(entries: list[_ProjectEntry]) -> None:
            for _, checkouts in entries:
                checkouts[:] = [binding for binding in checkouts
                               if binding.checkout_id != checkout_id]

        self._transact(mutate)

    # -- lock + leitura/gravacao atomica ------------------------------------

    def _transact(self, mutate: Callable[[list[_ProjectEntry]], _T]) -> _T:
        """Executa `mutate` sob lock exclusivo, recarregando antes de gravar.

        `mutate` recebe a lista de entradas recem-lida do disco, pode
        modifica-la in place (ou substituir seu conteudo via slice), e
        devolve o resultado a repassar para o chamador. O arquivo so e
        reescrito se `mutate` nao levantar — uma versao corrompida ou de
        schema desconhecido nunca chega a ser sobrescrita.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

        lock_path = self.path.with_name(self.path.name + ".lock")
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                entries = self._load()
                result = mutate(entries)
                self._write(entries)
                return result
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    def _load(self) -> list[_ProjectEntry]:
        if not self.path.exists():
            return []
        return self._decode(self.path.read_text(encoding="utf-8"))

    def _decode(self, text: str) -> list[_ProjectEntry]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectRegistryError(
                f"corrupt registry JSON at {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProjectRegistryError(
                f"registry root must be a JSON object: {self.path}")
        if data.get("schemaVersion") != _SCHEMA_VERSION:
            raise ProjectRegistryError(
                "unsupported registry schema version "
                f"{data.get('schemaVersion')!r} at {self.path}")

        entries: list[_ProjectEntry] = []
        for raw in data.get("projects", []):
            if not isinstance(raw, dict):
                raise ProjectRegistryError(
                    f"project entry must be a JSON object at {self.path}: "
                    f"{raw!r}")
            project_id = ProjectId(self._required_field(raw, "id", "project"))
            git_common_dir = raw.get("gitCommonDir")
            project = Project(
                id=project_id,
                primary=Path(self._required_field(raw, "primary", "project")),
                integration_branch=self._required_field(
                    raw, "integrationBranch", "project"),
                worktree_root=Path(self._required_field(
                    raw, "worktreeRoot", "project")),
                git_common_dir=Path(git_common_dir) if git_common_dir else None,
            )
            checkouts: list[CheckoutBinding] = []
            for raw_checkout in raw.get("checkouts", []):
                if not isinstance(raw_checkout, dict):
                    raise ProjectRegistryError(
                        "checkout entry must be a JSON object at "
                        f"{self.path}: {raw_checkout!r}")
                checkouts.append(CheckoutBinding(
                    checkout_id=CheckoutId(
                        self._required_field(raw_checkout, "id", "checkout")),
                    project_id=project_id,
                    source_path=Path(self._required_field(
                        raw_checkout, "sourcePath", "checkout")),
                    workspace=self._required_field(
                        raw_checkout, "workspace", "checkout"),
                ))
            entries.append((project, checkouts))
        return entries

    def _required_field(self, raw: dict, key: str, what: str) -> str:
        """Retorna `raw[key]`, ou levanta `ProjectRegistryError` nomeando o
        campo quando ele esta ausente ou nao e uma string — nunca deixa um
        `KeyError`/`TypeError` bruto escapar para o chamador. Uma string
        vazia e aceita aqui: validar o *conteudo* de `workspace` (ou de
        qualquer outro campo) fica fora do escopo desta correcao."""
        value = raw.get(key)
        if not isinstance(value, str):
            raise ProjectRegistryError(
                f"{what} entry missing or invalid required field {key!r} "
                f"at {self.path}")
        return value

    def _write(self, entries: list[_ProjectEntry]) -> None:
        payload = {
            "schemaVersion": _SCHEMA_VERSION,
            "projects": [
                {
                    "id": str(project.id),
                    "primary": str(project.primary),
                    "gitCommonDir": (str(project.git_common_dir)
                                    if project.git_common_dir else None),
                    "integrationBranch": project.integration_branch,
                    "worktreeRoot": str(project.worktree_root),
                    "checkouts": [
                        {
                            "id": str(binding.checkout_id),
                            "sourcePath": str(binding.source_path),
                            "workspace": binding.workspace,
                        }
                        for binding in checkouts
                    ],
                }
                for project, checkouts in entries
            ],
        }
        text = json.dumps(payload, indent=2) + "\n"

        tmp_path = self.path.with_name(
            f"{self.path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        tmp_fd = os.open(str(tmp_path),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp_path), str(self.path))
        except BaseException:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
            raise
        os.chmod(self.path, 0o600)
