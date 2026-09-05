"""Testes de cli/asb/workspace.py — identidade, layout e clone."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.workspace import layout_for, prepare_clone, workspace_id  # noqa: E402


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def origin_repo() -> Path:
    directory = Path(tempfile.mkdtemp()) / "hexmed-stack"
    directory.mkdir()
    git("init", "-b", "main", cwd=directory)
    git("config", "user.email", "t@example.com", cwd=directory)
    git("config", "user.name", "T", cwd=directory)
    (directory / "README.md").write_text("origem\n")
    git("add", "README.md", cwd=directory)
    git("commit", "-m", "inicial", cwd=directory)
    return directory


class TestWorkspaceId(unittest.TestCase):
    def test_orca_instance_id_wins_and_is_sanitized(self):
        got = workspace_id(Path("/x/hexmed-stack"),
                           {"ORCA_VM_INSTANCE_ID": "orca-c349::/a/b"})
        # Tracos repetidos colapsam: "::/" viraria "---" e produziria nomes
        # como hexmed-stack--f05b729e, que o v1 gerava.
        self.assertEqual(got, "orca-c349-a-b")

    def test_derivation_is_deterministic_without_orca(self):
        first = workspace_id(Path("/x/hexmed-stack"), {})
        second = workspace_id(Path("/x/hexmed-stack"), {})
        self.assertEqual(first, second)

    def test_trailing_slash_does_not_change_the_name(self):
        self.assertEqual(workspace_id(Path("/x/hexmed-stack"), {}),
                         workspace_id(Path("/x/hexmed-stack/"), {}))

    def test_different_repos_get_different_names(self):
        self.assertNotEqual(workspace_id(Path("/x/a"), {}),
                            workspace_id(Path("/x/b"), {}))

    def test_name_has_no_newline_or_double_dash_artifacts(self):
        got = workspace_id(Path("/x/hexmed-stack"), {})
        self.assertNotIn("\n", got)
        self.assertNotIn("--", got)

    def test_empty_orca_id_falls_back_to_derivation(self):
        self.assertEqual(workspace_id(Path("/x/hexmed-stack"),
                                      {"ORCA_VM_INSTANCE_ID": ""}),
                         workspace_id(Path("/x/hexmed-stack"), {}))


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_mount_is_grouped_by_project_then_workspace(self):
        layout = layout_for(Path("/x/hexmed-stack"), "mvp", self.home)
        self.assertEqual(layout.mount,
                         self.home / "asb-agent" / "hexmed-stack" / "mvp")

    def test_project_root_is_the_checkout_inside_the_mount(self):
        layout = layout_for(Path("/x/hexmed-stack"), "mvp", self.home)
        self.assertEqual(layout.project_root, layout.mount / "hexmed-stack")

    def test_orca_sibling_worktree_would_land_inside_the_mount(self):
        """F7: o Orca cria <projectRoot>-<Nome>. Se isso cair fora do mount,
        a worktree fica invisivel no host — o problema #2 do operador."""
        layout = layout_for(Path("/x/hexmed-stack"), "mvp", self.home)
        sibling = layout.project_root.with_name(
            layout.project_root.name + "-Add-Url")
        self.assertTrue(sibling.is_relative_to(layout.mount))

    def test_state_is_outside_the_mount(self):
        """Spec §5.2: squid.conf dentro do mount deixaria o agente editar a
        propria allowlist."""
        layout = layout_for(Path("/x/hexmed-stack"), "mvp", self.home)
        self.assertFalse(layout.state.is_relative_to(layout.mount))
        self.assertFalse(layout.state.is_relative_to(self.home / "asb-agent"))

    def test_state_is_derived_from_home_never_from_a_temp_dir(self):
        """O v1 escrevia o squid.conf com mktemp, em /tmp — que e tmpfs e
        some no reboot, deixando o bind mount apontando para caminho
        inexistente. O estado tem que sair do home, deterministicamente."""
        layout = layout_for(Path("/x/hexmed-stack"), "mvp", self.home)
        self.assertEqual(
            layout.state,
            self.home / ".local" / "state" / "agent-sandbox" / "mvp")


class TestClone(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.origin = origin_repo()

    def test_clone_is_self_contained(self):
        """Um `git worktree` dentro do container precisa de um .git proprio;
        um gitdir apontando para fora do mount nao existiria la."""
        layout = layout_for(self.origin, "mvp", self.home)
        prepare_clone(self.origin, layout)
        self.assertTrue((layout.project_root / ".git").is_dir())

    def test_clone_has_the_origin_content(self):
        layout = layout_for(self.origin, "mvp", self.home)
        prepare_clone(self.origin, layout)
        self.assertEqual((layout.project_root / "README.md").read_text(),
                         "origem\n")

    def test_sibling_worktree_can_be_created_in_the_clone(self):
        layout = layout_for(self.origin, "mvp", self.home)
        prepare_clone(self.origin, layout)
        sibling = layout.project_root.with_name(
            layout.project_root.name + "-Add-Url")
        git("worktree", "add", "-b", "add-url", str(sibling),
            cwd=layout.project_root)
        self.assertTrue((sibling / "README.md").is_file())
        self.assertTrue(sibling.is_relative_to(layout.mount))

    def test_second_call_is_idempotent_and_keeps_local_commits(self):
        layout = layout_for(self.origin, "mvp", self.home)
        prepare_clone(self.origin, layout)
        (layout.project_root / "novo.txt").write_text("trabalho do agente\n")
        git("add", "novo.txt", cwd=layout.project_root)
        git("commit", "-m", "trabalho", cwd=layout.project_root)
        prepare_clone(self.origin, layout)
        self.assertTrue((layout.project_root / "novo.txt").is_file())


if __name__ == "__main__":
    unittest.main()
