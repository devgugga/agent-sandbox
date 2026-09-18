"""cli/asb/checkouts/git.py — o unico ponto que fala com o Git de um checkout.

`GitRepository(path)` roda `git -C <path> ...` com lista de argumentos,
`shell=False`, stdin fechado, stdout/stderr capturados e timeout: nenhum
texto do operador vira comando de shell. A saida e decodificada com
`os.fsdecode` (sem traducao de newline), entao um caminho com espaco, `\\r`
ou newline chega intacto ao parser de `worktree list --porcelain -z`.

Um Git que nem executa (binario ausente, timeout) vira `GitError`; um
comando que executa e sai com codigo diferente de zero volta como
`GitResult` para quem chamou decidir. Consultas cuja resposta "nao sei" nao
pode passar por "limpo" ou "nao existe" (`status`, `worktrees`,
`is_ancestor`) levantam em vez de adivinhar.
"""
from __future__ import annotations

import os
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .model import CheckoutState

GIT_TIMEOUT_SECONDS = 10.0
_HEADS = "refs/heads/"
_ORIGIN = "refs/remotes/origin/"
# Progresso que o Git escreve no stderr mesmo quando o comando falha
# (`worktree add` sempre abre com "Preparing worktree (...)").
_PROGRESS = ("Preparing worktree", "Updating files:", "HEAD is now at")
_REASON_LIMIT = 300
# Mesmas categorias de `interfaces.tui_model.sanitize`: C0/C1/DEL,
# formatacao invisivel, separadores de linha/paragrafo, surrogates.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


class GitError(Exception):
    """O Git nao pode ser executado, ou respondeu algo que nao se prova."""


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def reason(self) -> str:
        """A causa de uma falha: as linhas `fatal:`/`error:` do stderr
        primeiro, depois qualquer outra (a saida de um hook), nunca uma
        linha de progresso como `Preparing worktree` sozinha. Limitada e
        sem caracteres de controle; sem causa, o codigo de saida."""
        lines = [line.strip() for line in self.stderr.splitlines()]
        lines = [line for line in lines
                 if line and not line.startswith(_PROGRESS)]
        causes = [line for line in lines
                  if line.startswith(("fatal:", "error:"))]
        others = [line for line in lines if line not in causes]
        text = "; ".join(causes + others)
        if not text:
            return f"git exited with code {self.returncode}"
        return _printable(text)[:_REASON_LIMIT]


@dataclass(frozen=True)
class BranchInfo:
    name: str
    detached: bool


@dataclass(frozen=True)
class Worktree:
    """Um registro de `git worktree list --porcelain -z`. `branch` e o nome
    curto (sem `refs/heads/`); `primary` e o primeiro registro, que o Git
    garante ser o worktree principal."""

    path: Path
    head: str | None
    branch: str | None
    detached: bool
    primary: bool
    bare: bool = False
    locked: bool = False
    prunable: bool = False


def parse_worktrees(output: str) -> list[Worktree]:
    """Parser do formato `--porcelain -z`: campos terminados por NUL,
    registros separados por um NUL extra (campo vazio)."""
    records: list[list[str]] = []
    current: list[str] = []
    for field in output.split("\0"):
        if field:
            current.append(field)
        elif current:
            records.append(current)
            current = []
    if current:
        records.append(current)

    worktrees: list[Worktree] = []
    for index, fields in enumerate(records):
        values: dict[str, str | None] = {}
        for field in fields:
            key, sep, value = field.partition(" ")
            values[key] = value if sep else None
        path = values.get("worktree")
        if not path:
            raise GitError(f"worktree record without a path: {fields!r}")
        ref = values.get("branch")
        worktrees.append(Worktree(
            path=Path(path),
            head=values.get("HEAD"),
            branch=(ref[len(_HEADS):] if ref and ref.startswith(_HEADS)
                    else ref),
            detached="detached" in values,
            primary=index == 0,
            bare="bare" in values,
            locked="locked" in values,
            prunable="prunable" in values,
        ))
    return worktrees


class GitRepository:
    """Git de UM caminho. `runner` e injetavel so para simular falhas que um
    repositorio real nao produz sob demanda."""

    def __init__(self, path: Path, *,
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 timeout: float = GIT_TIMEOUT_SECONDS) -> None:
        self.path = Path(path)
        self._runner = runner
        self._timeout = timeout

    def run(self, *args: str) -> GitResult:
        argv = ["git", "-C", str(self.path), *args]
        try:
            completed = self._runner(argv, shell=False, capture_output=True,
                                     timeout=self._timeout, check=False,
                                     stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitError(f"could not run git in {self.path}: {exc}") from exc
        return GitResult(completed.returncode, _decode(completed.stdout),
                         _decode(completed.stderr))

    def _value(self, *args: str) -> str:
        result = self.run(*args)
        if not result.ok:
            raise GitError(f"git {args[0]} failed in {self.path}: "
                           f"{result.reason()}")
        value = result.stdout.strip()
        if not value:
            raise GitError(f"git {args[0]} returned nothing in {self.path}")
        return value

    # -- consultas --------------------------------------------------------------

    def common_dir(self) -> Path:
        return Path(self._value("rev-parse", "--path-format=absolute",
                                "--git-common-dir"))

    def worktrees(self) -> list[Worktree]:
        result = self.run("worktree", "list", "--porcelain", "-z")
        if not result.ok:
            raise GitError(f"git worktree list failed in {self.path}: "
                           f"{result.reason()}")
        return parse_worktrees(result.stdout)

    def branch(self) -> BranchInfo | None:
        """Branch do checkout, ou o commit abreviado num HEAD destacado;
        `None` em qualquer falha (nunca levanta). Um Git que nem executa nao
        ganha a segunda tentativa."""
        try:
            result = self.run("symbolic-ref", "--short", "HEAD")
        except GitError:
            return None
        name = result.stdout.strip() if result.ok else ""
        if name:
            return BranchInfo(name, False)
        try:
            result = self.run("rev-parse", "--short", "HEAD")
        except GitError:
            return None
        commit = result.stdout.strip() if result.ok else ""
        return BranchInfo(commit, True) if commit else None

    def status(self) -> CheckoutState:
        """`DIRTY` com qualquer mudanca, inclusive arquivo nao rastreado;
        senao `CLEAN`. Levanta se nao da para saber: incerto nunca e
        limpo."""
        result = self.run("status", "--porcelain=v1", "-z",
                          "--untracked-files=normal")
        if not result.ok:
            raise GitError(f"git status failed in {self.path}: "
                           f"{result.reason()}")
        return CheckoutState.DIRTY if result.stdout else CheckoutState.CLEAN

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        _refuse_option(ancestor)
        _refuse_option(descendant)
        result = self.run("merge-base", "--is-ancestor", ancestor, descendant)
        if result.returncode in (0, 1):
            return result.returncode == 0
        raise GitError(f"git merge-base failed in {self.path}: "
                       f"{result.reason()}")

    def remote_default_branch(self) -> str | None:
        """O branch que um `refs/remotes/origin/HEAD` simbolico e inequivoco
        nomeia, ou `None` (ausente, nao simbolico, fora de `origin/`)."""
        result = self.run("symbolic-ref", "refs/remotes/origin/HEAD")
        ref = result.stdout.strip() if result.ok else ""
        if not ref.startswith(_ORIGIN) or ref == _ORIGIN:
            return None
        return ref[len(_ORIGIN):]

    def valid_branch_name(self, name: str) -> bool:
        """`git check-ref-format --branch` aceita E devolve o nome intacto:
        a forma expandida de `@{-1}` ou `@{u}` nao e o nome pedido."""
        if not name or name.startswith("-"):
            return False
        result = self.run("check-ref-format", "--branch", name)
        return result.ok and result.stdout.rstrip("\n") == name

    def branch_commit(self, name: str) -> str | None:
        """Commit do branch LOCAL `name`, ou `None` se ele nao existe."""
        _refuse_option(name)
        return self.commit(f"{_HEADS}{name}")

    def commit(self, rev: str) -> str | None:
        """Commit completo que `rev` nomeia, ou `None` se nao resolve."""
        _refuse_option(rev)
        result = self.run("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        value = result.stdout.strip() if result.ok else ""
        return value or None

    def symbolic_branch(self) -> str | None:
        """O branch de `HEAD` como o Git o nomeia, ou `None` num HEAD
        destacado (ou em qualquer falha). Diferente de `branch()`, nunca
        devolve um commit no lugar do nome."""
        result = self.run("symbolic-ref", "--short", "HEAD")
        name = result.stdout.strip() if result.ok else ""
        return name or None

    def valid_ref(self, ref: str) -> bool:
        """`git check-ref-format <ref>` para um nome de ref completo."""
        if not ref or ref.startswith("-"):
            return False
        return self.run("check-ref-format", ref).ok

    def refs(self, *patterns: str) -> list[tuple[str, str]]:
        """`(commit, ref)` de cada ref sob `patterns`. Levanta se nao da
        para listar: uma lista vazia tem de significar "nenhuma ref"."""
        for pattern in patterns:
            _refuse_option(pattern)
        result = self.run("for-each-ref", "--format=%(objectname) %(refname)",
                          *patterns)
        if not result.ok:
            raise GitError(f"git for-each-ref failed in {self.path}: "
                           f"{result.reason()}")
        found = []
        for line in result.stdout.splitlines():
            commit, _, ref = line.partition(" ")
            found.append((commit, ref))
        return found

    def reflog_commits(self, ref: str) -> list[str]:
        """Commits do reflog de `ref`, do mais novo ao mais antigo. E como
        se leem as entradas de `refs/stash` alem da primeira, que
        `for-each-ref` nao lista. Levanta se nao da para ler."""
        _refuse_option(ref)
        result = self.run("rev-list", "--walk-reflogs", ref, "--")
        if not result.ok:
            raise GitError(f"git rev-list --walk-reflogs failed in "
                           f"{self.path}: {result.reason()}")
        return result.stdout.split()

    def unmerged_paths(self) -> list[str]:
        """Caminhos em conflito no indice (`ls-files -u`), sem repeticao."""
        result = self.run("ls-files", "-u", "-z")
        if not result.ok:
            raise GitError(f"git ls-files failed in {self.path}: "
                           f"{result.reason()}")
        paths: list[str] = []
        for record in result.stdout.split("\0"):
            _, tab, path = record.partition("\t")
            if tab and path not in paths:
                paths.append(path)
        return paths

    # -- mutacoes -------------------------------------------------------------------

    def worktree_add(self, branch: str, path: Path, base: str) -> GitResult:
        _refuse_option(branch)
        _refuse_option(base)
        return self.run("worktree", "add", "-b", branch, str(path), base)

    def worktree_remove(self, path: Path) -> GitResult:
        """Nunca `--force`: um worktree com mudancas e recusado pelo Git."""
        return self.run("worktree", "remove", str(path))

    def fetch(self, source: Path, refspec: str) -> GitResult:
        """Busca `refspec` do repositorio local `source`. As opcoes terminam
        antes do repositorio (`--`); nenhuma tag, nenhum FETCH_HEAD."""
        _refuse_option(refspec)
        return self.run("fetch", "--no-tags", "--no-write-fetch-head", "--",
                        str(source), refspec)

    def merge(self, ref: str) -> GitResult:
        """`git merge --no-edit <ref>` com uma ref completa ja validada; sem
        `--` entre `merge` e a ref (o Git a leria como caminho)."""
        _refuse_option(ref)
        return self.run("merge", "--no-edit", ref)

    def delete_merged_branch(self, name: str) -> GitResult:
        """`git branch -d`: o proprio Git recusa um branch nao integrado.
        Nunca `-D`."""
        _refuse_option(name)
        return self.run("branch", "-d", name)

    def delete_branch(self, name: str) -> GitResult:
        """So para o rollback que ja provou ter criado `name` no commit
        registrado."""
        _refuse_option(name)
        return self.run("branch", "-D", name)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data if isinstance(data, str) else os.fsdecode(data)


def _printable(text: str) -> str:
    return "".join("?" if unicodedata.category(ch) in _UNSAFE_CATEGORIES
                   else ch for ch in text)


def _refuse_option(value: str) -> None:
    if not value or value.startswith("-"):
        raise GitError(f"refusing git argument {value!r}")
