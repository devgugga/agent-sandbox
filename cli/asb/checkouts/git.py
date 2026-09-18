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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .model import CheckoutState

GIT_TIMEOUT_SECONDS = 10.0
_HEADS = "refs/heads/"
_ORIGIN = "refs/remotes/origin/"


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
        """Primeira linha nao vazia do stderr, ou o codigo de saida."""
        for line in self.stderr.splitlines():
            if line.strip():
                return line.strip()
        return f"git exited with code {self.returncode}"


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

    # -- mutacoes -------------------------------------------------------------------

    def worktree_add(self, branch: str, path: Path, base: str) -> GitResult:
        _refuse_option(branch)
        _refuse_option(base)
        return self.run("worktree", "add", "-b", branch, str(path), base)

    def worktree_remove(self, path: Path) -> GitResult:
        """Nunca `--force`: um worktree com mudancas e recusado pelo Git."""
        return self.run("worktree", "remove", str(path))

    def delete_branch(self, name: str) -> GitResult:
        """So para o rollback que ja provou ter criado `name` no commit
        registrado."""
        _refuse_option(name)
        return self.run("branch", "-D", name)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data if isinstance(data, str) else os.fsdecode(data)


def _refuse_option(value: str) -> None:
    if not value or value.startswith("-"):
        raise GitError(f"refusing git argument {value!r}")
