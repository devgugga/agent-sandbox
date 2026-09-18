"""Testes de `asb.checkouts.git` (Tarefa 11) contra repositorios Git REAIS.

Cada teste cria um repositorio temporario com a configuracao global e de
sistema do Git isoladas (`GIT_CONFIG_GLOBAL=/dev/null`) e identidade local;
nada aqui toca este repositorio, Podman, SSH ou tmux. O `runner` injetado so
aparece onde um Git real nao produz a falha sob demanda (binario ausente,
timeout) ou para conferir o argv exato.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.git import (  # noqa: E402
    BranchInfo, GitError, GitRepository, GitResult, Worktree,
    parse_worktrees,
)
from asb.checkouts.model import CheckoutState  # noqa: E402

_ISOLATED_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_SYSTEM": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"}
_INHERITED_GIT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                  "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")


def isolate_git(case: unittest.TestCase) -> None:
    """Configuracao global/de sistema do Git fora do teste, ate o fim dele."""
    patcher = mock.patch.dict(os.environ, _ISOLATED_ENV)
    patcher.start()
    case.addCleanup(patcher.stop)
    for name in _INHERITED_GIT:
        os.environ.pop(name, None)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], shell=False,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "init")
    return path


class _RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        isolate_git(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = init_repo(self.tmp / "repo")
        self.git = GitRepository(self.repo)


class TestWorktreeList(_RepoCase):
    def test_paths_with_spaces_and_newlines_survive_the_parser(self):
        spaced = self.tmp / "with space"
        newline = self.tmp / "new\nline"
        git(self.repo, "worktree", "add", "-q", "-b", "spaced", str(spaced))
        git(self.repo, "worktree", "add", "-q", "-b", "nl", str(newline))

        found = {wt.path: wt for wt in self.git.worktrees()}

        self.assertEqual(set(found), {self.repo, spaced, newline})
        self.assertEqual(found[spaced].branch, "spaced")
        self.assertEqual(found[newline].branch, "nl")

    def test_the_primary_is_the_first_record_even_from_a_linked_worktree(self):
        linked = self.tmp / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "topic", str(linked))

        for where in (self.repo, linked):
            with self.subTest(where=where):
                worktrees = GitRepository(where).worktrees()
                self.assertEqual([wt.primary for wt in worktrees],
                                 [True, False])
                self.assertEqual(worktrees[0].path, self.repo)
                self.assertEqual(worktrees[0].branch, "main")

    def test_a_detached_head_has_no_branch(self):
        head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach")

        [primary] = self.git.worktrees()

        self.assertTrue(primary.detached)
        self.assertIsNone(primary.branch)
        self.assertEqual(primary.head, head)

    def test_a_deleted_worktree_is_listed_as_prunable_not_hidden(self):
        gone = self.tmp / "gone"
        git(self.repo, "worktree", "add", "-q", "-b", "gone", str(gone))
        shutil.rmtree(gone)

        found = {wt.path: wt for wt in self.git.worktrees()}

        self.assertTrue(found[gone].prunable)
        self.assertFalse(found[self.repo].prunable)

    def test_the_parser_reads_every_documented_field(self):
        output = ("worktree /r\0HEAD abc\0branch refs/heads/main\0\0"
                  "worktree /b\0bare\0\0"
                  "worktree /l\0HEAD def\0detached\0locked why\0"
                  "prunable gone\0\0")
        self.assertEqual(parse_worktrees(output), [
            Worktree(Path("/r"), "abc", "main", False, True),
            Worktree(Path("/b"), None, None, False, False, bare=True),
            Worktree(Path("/l"), "def", None, True, False, locked=True,
                     prunable=True),
        ])

    def test_a_record_without_a_path_is_an_error(self):
        with self.assertRaises(GitError):
            parse_worktrees("HEAD abc\0\0")

    def test_a_failing_list_raises(self):
        with self.assertRaises(GitError):
            GitRepository(self.tmp).worktrees()


class TestBranch(_RepoCase):
    def test_the_branch_of_a_checkout(self):
        self.assertEqual(self.git.branch(), BranchInfo("main", False))

    def test_a_detached_head_is_the_short_commit(self):
        short = git(self.repo, "rev-parse", "--short", "HEAD")
        git(self.repo, "checkout", "-q", "--detach")
        self.assertEqual(self.git.branch(), BranchInfo(short, True))

    def test_not_a_checkout_is_an_unknown_branch(self):
        self.assertIsNone(GitRepository(self.tmp).branch())
        self.assertIsNone(GitRepository(self.tmp / "absent").branch())


class TestBranchRunner(unittest.TestCase):
    """O comportamento de `read_branch` da Tarefa 10, agora aqui (§C)."""

    def _runner(self, *results):
        calls = []
        queue = list(results)

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            result = queue.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        return calls, run

    def test_reads_the_symbolic_ref_with_an_argv_and_a_timeout(self):
        calls, run = self._runner(
            subprocess.CompletedProcess([], 0, b"main\n", b""))
        self.assertEqual(GitRepository(Path("/r"), runner=run).branch(),
                         BranchInfo("main", False))
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["git", "-C", "/r", "symbolic-ref", "--short",
                                "HEAD"])
        self.assertIs(kwargs["shell"], False)
        self.assertTrue(kwargs["capture_output"])
        self.assertIs(kwargs["check"], False)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertGreater(kwargs["timeout"], 0)

    def test_a_detached_head_falls_back_to_the_short_commit(self):
        calls, run = self._runner(
            subprocess.CompletedProcess([], 128, b"", b"not a symbolic ref"),
            subprocess.CompletedProcess([], 0, b"abc1234\n", b""))
        self.assertEqual(GitRepository(Path("/r"), runner=run).branch(),
                         BranchInfo("abc1234", True))
        self.assertEqual(calls[1][0], ["git", "-C", "/r", "rev-parse",
                                       "--short", "HEAD"])

    def test_any_git_failure_is_an_unknown_branch(self):
        for results in (
                (subprocess.CompletedProcess([], 128, b"", b""),
                 subprocess.CompletedProcess([], 128, b"", b"")),
                (FileNotFoundError("git"),),
                (subprocess.TimeoutExpired("git", 5),),
                (subprocess.CompletedProcess([], 128, b"", b""),
                 subprocess.TimeoutExpired("git", 5)),
                (subprocess.CompletedProcess([], 0, b"\n", b""),
                 subprocess.CompletedProcess([], 0, b"", b""))):
            with self.subTest(results=results):
                calls, run = self._runner(*results)
                self.assertIsNone(
                    GitRepository(Path("/r"), runner=run).branch())
                # Um Git que nem executa nao ganha a segunda tentativa.
                self.assertEqual(len(calls), len(results))

    def test_a_git_that_cannot_run_is_a_git_error(self):
        _, run = self._runner(FileNotFoundError("git"))
        with self.assertRaises(GitError):
            GitRepository(Path("/r"), runner=run).run("status")


class TestFailureReason(unittest.TestCase):
    """Rodada 1: o motivo de uma falha e a causa, nunca o progresso."""

    def test_the_progress_line_alone_is_never_the_reason(self):
        result = GitResult(128, "", "Preparing worktree (new branch 'x')\n")
        self.assertEqual(result.reason(), "git exited with code 128")

    def test_fatal_and_error_lines_come_first_then_other_output(self):
        result = GitResult(3, "", "Preparing worktree (new branch 'x')\n"
                                  "hook: lint failed\n"
                                  "fatal: boom\n"
                                  "error: bang\n")
        self.assertEqual(result.reason(),
                         "fatal: boom; error: bang; hook: lint failed")

    def test_the_reason_is_bounded_and_has_no_control_characters(self):
        result = GitResult(1, "", "fatal: \x1b[2J" + "x" * 1000 + "\n")
        reason = result.reason()
        self.assertLessEqual(len(reason), 300)
        self.assertTrue(reason.startswith("fatal: ?[2Jx"))
        self.assertFalse(any(ord(ch) < 32 or 127 <= ord(ch) < 160
                             for ch in reason))

    def test_an_empty_stderr_is_the_exit_code(self):
        self.assertEqual(GitResult(1, "", "\n").reason(),
                         "git exited with code 1")


class TestStatus(_RepoCase):
    def test_clean_then_dirty_by_untracked_and_by_modified_file(self):
        self.assertIs(self.git.status(), CheckoutState.CLEAN)
        (self.repo / "new.txt").write_text("x", encoding="utf-8")
        self.assertIs(self.git.status(), CheckoutState.DIRTY)
        (self.repo / "new.txt").unlink()
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertIs(self.git.status(), CheckoutState.DIRTY)

    def test_an_unreadable_status_raises_instead_of_reading_clean(self):
        with self.assertRaises(GitError):
            GitRepository(self.tmp).status()


class TestRemoteDefaultBranch(_RepoCase):
    def test_absent_origin_head_is_none(self):
        self.assertIsNone(self.git.remote_default_branch())

    def test_an_unambiguous_origin_head_names_its_branch(self):
        git(self.repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD",
            "refs/remotes/origin/trunk")
        self.assertEqual(self.git.remote_default_branch(), "trunk")

    def test_an_origin_head_outside_origin_is_none(self):
        git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD",
            "refs/heads/main")
        self.assertIsNone(self.git.remote_default_branch())


class TestRefs(_RepoCase):
    def test_branch_names_are_validated_by_git_and_kept_verbatim(self):
        git(self.repo, "checkout", "-q", "-b", "other")
        git(self.repo, "checkout", "-q", "main")
        for name in ("feat/x", "topic", "fix-1.2"):
            with self.subTest(name=name):
                self.assertTrue(self.git.valid_branch_name(name))
        # `@{-1}` passa em `check-ref-format --branch`, EXPANDIDO para
        # `other`: nao e o nome pedido e e recusado.
        for name in ("@{-1}", "a..b", "-x", "-", "", "HEAD", "with space",
                     "trailing/", "x.lock"):
            with self.subTest(name=name):
                self.assertFalse(self.git.valid_branch_name(name))

    def test_commit_and_branch_commit_resolve_or_are_none(self):
        head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.git.commit("main"), head)
        self.assertEqual(self.git.branch_commit("main"), head)
        self.assertIsNone(self.git.commit("nope"))
        self.assertIsNone(self.git.branch_commit("nope"))
        with self.assertRaises(GitError):
            self.git.commit("--all")

    def test_ancestry_true_false_and_unknown(self):
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "b.txt").write_text("b", encoding="utf-8")
        git(self.repo, "add", "b.txt")
        git(self.repo, "commit", "-q", "-m", "b")
        tip = git(self.repo, "rev-parse", "HEAD")

        self.assertTrue(self.git.is_ancestor(base, tip))
        self.assertFalse(self.git.is_ancestor(tip, base))
        with self.assertRaises(GitError):
            self.git.is_ancestor("0" * 40, tip)

    def test_primary_and_linked_worktree_share_the_common_dir(self):
        linked = self.tmp / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "topic", str(linked))
        self.assertEqual(self.git.common_dir(), self.repo / ".git")
        self.assertEqual(GitRepository(linked).common_dir(), self.repo / ".git")
        with self.assertRaises(GitError):
            GitRepository(self.tmp).common_dir()


if __name__ == "__main__":
    unittest.main()
