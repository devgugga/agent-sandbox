"""Testes de cli/asb/squid.py — geracao do squid.conf."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.profile import Profile  # noqa: E402
from asb.squid import SquidError, normalize_domains, render  # noqa: E402


def a_file(body: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "f.txt"
    path.write_text(body)
    return path


TEMPLATE = "acl allowed_domains dstdomain __ALLOWLIST__\n"


class TestNormalize(unittest.TestCase):
    def test_child_is_pruned_when_parent_wildcard_is_present(self):
        """Squid aborta com 'FATAL: Bungled' quando .github.com e
        api.github.com aparecem no mesmo ACL dstdomain."""
        self.assertEqual(normalize_domains([".github.com", "api.github.com"]),
                         [".github.com"])

    def test_apex_is_pruned_by_its_own_wildcard(self):
        self.assertEqual(
            normalize_domains(["antigravity.google", ".antigravity.google"]),
            [".antigravity.google"])

    def test_exact_duplicates_collapse(self):
        self.assertEqual(normalize_domains(["a.com", "a.com"]), ["a.com"])

    def test_unrelated_domains_all_survive_and_are_sorted(self):
        self.assertEqual(normalize_domains(["b.com", "a.com"]),
                         ["a.com", "b.com"])

    def test_similar_suffix_is_not_treated_as_a_child(self):
        """notgithub.com termina em 'github.com' como texto, mas nao e
        subdominio de github.com."""
        self.assertIn("notgithub.com",
                      normalize_domains([".github.com", "notgithub.com"]))


class TestRender(unittest.TestCase):
    def test_project_domains_are_merged_into_the_allowlist(self):
        out = render(Profile(allow=("pypi.org",)),
                     a_file(".anthropic.com\n"), a_file(TEMPLATE))
        self.assertIn("pypi.org", out)
        self.assertIn(".anthropic.com", out)

    def test_comments_and_blank_lines_in_the_base_are_ignored(self):
        out = render(Profile(), a_file("# comentario\n\n.anthropic.com\n"),
                     a_file(TEMPLATE))
        self.assertNotIn("comentario", out)

    def test_placeholder_is_fully_substituted(self):
        out = render(Profile(), a_file(".anthropic.com\n"), a_file(TEMPLATE))
        self.assertNotIn("__ALLOWLIST__", out)

    def test_empty_allowlist_is_refused(self):
        """Um squid.conf sem dominio algum sobe e nega tudo: o sandbox fica
        sem egresso e o sintoma nao aponta para a causa."""
        with self.assertRaises(SquidError):
            render(Profile(), a_file("# so comentario\n"), a_file(TEMPLATE))

    def test_nested_mode_adds_registry_domains(self):
        """Com mode = nested o agente puxa imagens pelo proxy; sem os
        registries a falha aparece como 'o build nao funciona'."""
        out = render(Profile(container_mode="nested"),
                     a_file(".anthropic.com\n"), a_file(TEMPLATE))
        self.assertIn("registry-1.docker.io", out)
        self.assertIn("quay.io", out)

    def test_default_mode_does_not_add_registry_domains(self):
        out = render(Profile(), a_file(".anthropic.com\n"), a_file(TEMPLATE))
        self.assertNotIn("registry-1.docker.io", out)


if __name__ == "__main__":
    unittest.main()


class TestAllowlistBaseCobreOsAgentes(unittest.TestCase):
    """A imagem instala claude, codex e agy. Se a base nao alcanca a API de um
    deles, o agente nao inicia e o sintoma e um CONNECT 403 no Squid —
    indistinguivel de bloqueio proposital, que e o pior tipo de falha aqui.

    Foi exatamente o que aconteceu: o Codex migrou de api.openai.com para
    chatgpt.com e a allowlist base ficou para tras.
    """

    BASE = (Path(__file__).resolve().parents[2] / "image" / "squid"
            / "allowlist-base.txt")

    @staticmethod
    def _cobre(host: str, domains: list[str]) -> bool:
        """Semantica do dstdomain do Squid: '.x.com' casa x.com e subdominios."""
        for d in domains:
            if d == host:
                return True
            if d.startswith(".") and (host == d[1:] or host.endswith(d)):
                return True
        return False

    def test_base_alcanca_a_api_de_cada_agente_instalado(self):
        from asb.squid import read_base
        domains = read_base(self.BASE)
        for agente, host in (("claude", "api.anthropic.com"),
                             # O Claude Code >= v2.1 tambem fala com
                             # platform.claude.com, que NAO e coberto por
                             # .anthropic.com. Sem ele o agente morre em
                             # "Failed to connect to platform.claude.com:
                             # Status 403" — de novo indistinguivel de
                             # bloqueio proposital.
                             ("claude", "platform.claude.com"),
                             ("codex", "chatgpt.com"),
                             ("agy", "antigravity.google")):
            with self.subTest(agente=agente):
                self.assertTrue(
                    self._cobre(host, domains),
                    f"a allowlist base nao alcanca {host}, de que o {agente} "
                    f"depende para iniciar")
