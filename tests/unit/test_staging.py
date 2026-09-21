"""Testes de cli/asb/staging.py — o que sai do host para o sandbox."""

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.staging import StagingError, build_staging  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.stage = Path(tempfile.mkdtemp()) / "staging"
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".codex").mkdir(parents=True)

    def manifest(self, body: str) -> Path:
        path = Path(tempfile.mkdtemp()) / "m.toml"
        path.write_text(body)
        return path

    def staged(self) -> dict[str, str]:
        lines = (self.stage / "manifest.tsv").read_text().splitlines()
        return {dst: src for src, dst in (line.split("\t") for line in lines)}


class TestDenyList(Fixture):
    def test_declared_credential_file_is_refused(self):
        (self.home / ".claude" / ".credentials.json").write_text("{}")
        with self.assertRaises(StagingError):
            build_staging(self.manifest(
                '[[entry]]\nsrc = "~/.claude/.credentials.json"\n'
                'dst = "~/.claude/.credentials.json"\n'),
                self.stage, self.home)

    def test_credential_hidden_inside_a_declared_directory_is_refused(self):
        skills = self.home / ".claude" / "skills"
        skills.mkdir()
        (skills / "auth.json").write_text("{}")
        with self.assertRaises(StagingError):
            build_staging(self.manifest(
                '[[entry]]\nsrc = "~/.claude/skills"\ndst = "~/.claude/skills"\n'),
                self.stage, self.home)

    def test_symlink_with_an_innocent_name_pointing_at_a_credential(self):
        """O nome nao e negado; o ALVO e. Sem resolver, passaria."""
        secret = self.home / ".claude" / ".credentials.json"
        secret.write_text("{}")
        skills = self.home / ".claude" / "skills"
        skills.mkdir()
        os.symlink(secret, skills / "inocente.json")
        with self.assertRaises(StagingError):
            build_staging(self.manifest(
                '[[entry]]\nsrc = "~/.claude/skills"\ndst = "~/.claude/skills"\n'),
                self.stage, self.home)

    def test_destination_outside_the_agent_config_roots_is_refused(self):
        (self.home / ".claude" / "settings.json").write_text("{}")
        with self.assertRaises(StagingError):
            build_staging(self.manifest(
                '[[entry]]\nsrc = "~/.claude/settings.json"\n'
                'dst = "~/.ssh/authorized_keys"\n'),
                self.stage, self.home)


class TestMountPointDestinationsAreRefused(Fixture):
    """I4: `~/.claude` e `~/.codex` viraram PONTOS DE MONTAGEM do volume
    compartilhado, e os subdiretorios de sessao viraram pontos de montagem do
    volume do workspace.

    O entrypoint substitui cada destino do manifesto, e nao se substitui um
    mountpoint: na raiz da credencial isso apagaria o
    `.credentials.json`/`auth.json` de TODOS os workspaces antes de falhar;
    num subdiretorio de sessao o `rename` devolve EBUSY e derruba o entrypoint
    inteiro com `set -e`. Nenhuma entrega nossa faz isso; UMA linha de
    operador bastava.
    """

    def _entry(self, dst: str, src: str = "~/.claude/plugins") -> Path:
        return self.manifest(f'[[entry]]\nsrc = "{src}"\ndst = "{dst}"\n')

    def test_the_claude_mount_root_is_refused(self):
        (self.home / ".claude" / "plugins").mkdir()
        with self.assertRaises(StagingError) as ctx:
            build_staging(self._entry("~/.claude"), self.stage, self.home)
        self.assertIn("ponto de montagem", str(ctx.exception))

    def test_the_codex_mount_root_is_refused(self):
        (self.home / ".codex" / "plugins").mkdir()
        with self.assertRaises(StagingError):
            build_staging(self._entry("~/.codex", "~/.codex/plugins"),
                          self.stage, self.home)

    def test_a_trailing_slash_does_not_slip_past(self):
        (self.home / ".claude" / "plugins").mkdir()
        with self.assertRaises(StagingError):
            build_staging(self._entry("~/.claude/"), self.stage, self.home)

    def test_subdirectories_of_the_mount_root_stay_allowed(self):
        """A recusa e da RAIZ. Todo destino real do `provision.toml` esta um
        nivel abaixo, e continua valendo."""
        (self.home / ".claude" / "plugins").mkdir()
        build_staging(self._entry("~/.claude/plugins"), self.stage, self.home)
        self.assertIn(str(self.home / ".claude" / "plugins"), self.staged())

    def test_the_gemini_root_is_not_a_mount_and_stays_allowed(self):
        """`~/.gemini` nao e montado de volume algum: a credencial do agy vai
        para o Secret Service pelo socket do keyring."""
        (self.home / ".gemini").mkdir()
        (self.home / ".gemini" / "config").mkdir()
        build_staging(
            self.manifest('[[entry]]\nsrc = "~/.gemini/config"\n'
                          'dst = "~/.gemini"\n'),
            self.stage, self.home)
        self.assertIn(str(self.home / ".gemini"), self.staged())

    def test_the_session_mount_points_are_refused_too(self):
        """Estes viraram mountpoints no MESMO commit que o resto do I6. Um
        `dst` igual a um deles nao apaga nada compartilhado, mas o `rename`
        sobre mountpoint devolve EBUSY e o agente nunca sobe."""
        for rel in (".claude/todos", ".claude/shell-snapshots",
                    ".claude/projects", ".codex/sessions"):
            with self.subTest(dst=rel):
                (self.home / ".claude" / "plugins").mkdir(exist_ok=True)
                with self.assertRaises(StagingError):
                    build_staging(self._entry(f"~/{rel}"), self.stage,
                                  self.home)

    def test_a_path_inside_a_session_mount_point_stays_allowed(self):
        """So o mountpoint e recusado. O que esta DENTRO dele aterrissa no
        volume de sessao do proprio workspace e nao alcanca nada
        compartilhado."""
        from asb.staging import _mount_point_destinations
        self.assertNotIn(self.home / ".claude" / "todos" / "algo",
                         _mount_point_destinations(self.home))

    def test_the_refused_destinations_match_every_mount_point(self):
        """Guarda de deriva: `staging` repete a lista em vez de importar
        `runtime.storage` (que `lifecycle` importa, e que importa `staging`
        transitivamente via `lifecycle` — o import direto de `staging`
        fecharia um ciclo). Cobre as DUAS familias: se qualquer uma crescer
        sem a lista crescer junto, este teste cai.

        Tarefa 6 (rodada final de revisao): repontado de `asb.lifecycle`
        para `asb.runtime.storage`, o modulo DONO de `CREDENTIAL_DIRS`/
        `SESSION_STATE_DIRS` — `lifecycle.py` so os reexportava, e essa
        reexportacao nao tinha nenhum consumidor de PRODUCAO (so este
        teste, indiretamente)."""
        from asb.runtime.storage import CREDENTIAL_DIRS, SESSION_STATE_DIRS
        from asb.staging import _mount_point_destinations

        self.assertEqual(
            set(_mount_point_destinations(self.home)),
            {self.home / rel for rel in CREDENTIAL_DIRS.values()}
            | {self.home / rel for rel in SESSION_STATE_DIRS.values()})


class TestMaterialization(Fixture):
    def test_missing_source_is_skipped_not_fatal(self):
        count = build_staging(self.manifest(
            '[[entry]]\nsrc = "~/.claude/nao-existe"\n'
            'dst = "~/.claude/nao-existe"\n'), self.stage, self.home)
        self.assertEqual(count, 0)

    def test_symlink_into_an_allowed_root_is_resolved_into_the_stage(self):
        """As skills do host apontam para fora do home. Sem resolver, chegam
        como links quebrados: presentes num ls, inuteis para o agente."""
        external = self.home / ".agents" / "skills" / "revisar"
        external.mkdir(parents=True)
        (external / "SKILL.md").write_text("conteudo\n")
        skills = self.home / ".claude" / "skills"
        skills.mkdir()
        os.symlink(external, skills / "revisar")

        build_staging(self.manifest(
            '[[entry]]\nsrc = "~/.claude/skills"\ndst = "~/.claude/skills"\n'),
            self.stage, self.home)
        landed = self.stage / self.staged()[str(self.home / ".claude/skills")]
        target = landed / "revisar" / "SKILL.md"
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "conteudo\n")

    def test_symlink_to_an_untrusted_root_is_refused_not_followed(self):
        outside = Path(tempfile.mkdtemp()) / "qualquer"
        outside.mkdir()
        skills = self.home / ".claude" / "skills"
        skills.mkdir()
        os.symlink(outside, skills / "estranho")
        with self.assertRaises(StagingError):
            build_staging(self.manifest(
                '[[entry]]\nsrc = "~/.claude/skills"\ndst = "~/.claude/skills"\n'),
                self.stage, self.home)

    def test_same_basename_from_different_sources_does_not_collide(self):
        """~/.claude/plugins e ~/.codex/plugins tem o mesmo basename; sem uma
        chave por ORIGEM, o segundo sobrescreveria o primeiro em silencio."""
        for agent in (".claude", ".codex"):
            plugins = self.home / agent / "plugins"
            plugins.mkdir()
            (plugins / "marca.txt").write_text(agent)
        build_staging(self.manifest(
            '[[entry]]\nsrc = "~/.claude/plugins"\ndst = "~/.claude/plugins"\n'
            '[[entry]]\nsrc = "~/.codex/plugins"\ndst = "~/.codex/plugins"\n'),
            self.stage, self.home)
        staged = self.staged()
        claude = self.stage / staged[str(self.home / ".claude/plugins")]
        codex = self.stage / staged[str(self.home / ".codex/plugins")]
        self.assertEqual((claude / "marca.txt").read_text(), ".claude")
        self.assertEqual((codex / "marca.txt").read_text(), ".codex")


class TestFilters(Fixture):
    def test_claude_settings_loses_hooks_and_statusline(self):
        """Elas apontam para BINARIOS do host, que nao existem no container.
        Com caminho identico o path resolve para um lugar plausivel e vazio:
        falha silenciosa em vez de erro visivel."""
        import json
        (self.home / ".claude" / "settings.json").write_text(json.dumps({
            "model": "opus", "hooks": {"Stop": "x"}, "statusLine": {"c": "y"}}))
        build_staging(self.manifest(
            '[[entry]]\nsrc = "~/.claude/settings.json"\n'
            'dst = "~/.claude/settings.json"\nfilter = "claude-settings"\n'),
            self.stage, self.home)
        landed = self.stage / self.staged()[
            str(self.home / ".claude/settings.json")]
        data = json.loads(landed.read_text())
        self.assertEqual(data["model"], "opus")
        self.assertNotIn("hooks", data)
        self.assertNotIn("statusLine", data)

    def test_codex_config_loses_host_project_trust(self):
        """projects.* guarda confianca por caminho do HOST. Herdado, o sandbox
        carrega os nomes dos outros projetos e nao reconhece o proprio."""
        (self.home / ".codex" / "config.toml").write_text(
            'model = "gpt"\n[projects."/home/outro/x"]\ntrust_level = "trusted"\n')
        build_staging(self.manifest(
            '[[entry]]\nsrc = "~/.codex/config.toml"\n'
            'dst = "~/.codex/config.toml"\nfilter = "codex-config"\n'),
            self.stage, self.home)
        landed = self.stage / self.staged()[
            str(self.home / ".codex/config.toml")]
        text = landed.read_text()
        self.assertIn("gpt", text)
        self.assertNotIn("/home/outro/x", text)


if __name__ == "__main__":
    unittest.main()
