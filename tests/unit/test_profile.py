"""Testes de cli/asb/profile.py — leitura de .agent-sandbox.toml."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.profile import ProfileError, load_profile  # noqa: E402


def repo_with(body: str) -> Path:
    directory = Path(tempfile.mkdtemp())
    (directory / ".agent-sandbox.toml").write_text(body)
    return directory


class TestDefaults(unittest.TestCase):
    def test_missing_file_is_fully_closed(self):
        profile = load_profile(Path(tempfile.mkdtemp()))
        self.assertEqual(profile.allow, ())
        self.assertEqual(profile.host_ports, ())
        self.assertEqual(profile.container_mode, "none")
        self.assertEqual(profile.host_api, "none")
        self.assertEqual(profile.services, ())

    def test_empty_file_matches_missing_file(self):
        self.assertEqual(load_profile(repo_with("")),
                         load_profile(Path(tempfile.mkdtemp())))


class TestNetwork(unittest.TestCase):
    def test_allow_is_read_in_order_given(self):
        profile = load_profile(repo_with(
            '[network]\nallow = ["pypi.org", ".sentry.io"]\n'))
        self.assertEqual(profile.allow, ("pypi.org", ".sentry.io"))

    def test_allow_must_be_a_list_of_strings(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[network]\nallow = "pypi.org"\n'))


class TestDockerAxes(unittest.TestCase):
    def test_three_axes_are_independent(self):
        profile = load_profile(repo_with(
            '[docker]\nhost_ports = [5432]\nmode = "nested"\n'
            'host_api = "read"\n'))
        self.assertEqual(profile.host_ports, (5432,))
        self.assertEqual(profile.container_mode, "nested")
        self.assertEqual(profile.host_api, "read")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ProfileError) as caught:
            load_profile(repo_with('[docker]\nmode = "full"\n'))
        self.assertIn("nested", str(caught.exception))

    def test_unknown_host_api_is_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[docker]\nhost_api = "write"\n'))

    def test_port_outside_range_is_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[docker]\nhost_ports = [70000]\n'))

    def test_non_integer_port_is_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[docker]\nhost_ports = ["5432"]\n'))


class TestServices(unittest.TestCase):
    def test_service_carries_name_image_and_env(self):
        profile = load_profile(repo_with(
            '[services.db]\nimage = "docker.io/library/postgres:17"\n'
            'env = { POSTGRES_USER = "sandbox" }\n'))
        self.assertEqual(len(profile.services), 1)
        service = profile.services[0]
        self.assertEqual(service.name, "db")
        self.assertEqual(service.image, "docker.io/library/postgres:17")
        self.assertEqual(service.env, {"POSTGRES_USER": "sandbox"})

    def test_service_without_image_is_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[services.db]\nenv = {}\n'))

    def test_service_name_must_be_container_safe(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with(
                '[services."my db"]\nimage = "postgres:17"\n'))


class TestRemovedV1Schema(unittest.TestCase):
    """Um perfil do v1 aceito em silencio produz um sandbox que nao faz o que
    o arquivo diz. Recusar, nomeando o substituto."""

    def test_sandbox_mode_names_its_replacement(self):
        with self.assertRaises(ProfileError) as caught:
            load_profile(repo_with('[sandbox]\nmode = "attached"\n'))
        self.assertIn("host_ports", str(caught.exception))

    def test_tools_extra_names_mise(self):
        with self.assertRaises(ProfileError) as caught:
            load_profile(repo_with('[tools]\nextra = ["uv"]\n'))
        self.assertIn("mise", str(caught.exception))

    def test_proxy_java_is_rejected(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[proxy]\njava = true\n'))


class TestMalformedInput(unittest.TestCase):
    def test_broken_toml_raises_profile_error_not_toml_error(self):
        with self.assertRaises(ProfileError):
            load_profile(repo_with('[network\nallow = []\n'))


if __name__ == "__main__":
    unittest.main()
