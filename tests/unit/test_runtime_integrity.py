"""tests/unit/test_runtime_integrity.py — I1: o runtime nao se autentica pelo proprio manifesto.

O conjunto esperado vem de fora do diretorio validado: derivado do checkout
(caminho de producao) ou passado pelo chamador que montou o runtime
(`helper_path` + `runtime_manifest`). Adulterar payload e `manifest.json`
juntos nao cria uma nova raiz de confianca.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import install, supervisor  # noqa: E402


def forge(dest: Path, rel: str, data: bytes) -> None:
    """Adultera um arquivo E reescreve o manifesto adjacente de forma coerente."""
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest = json.loads((dest / "manifest.json").read_text())
    manifest["files"][rel] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode": target.stat().st_mode & 0o777,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest))


class _CheckoutCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.checkout = self.tmp / "checkout"
        pkg = self.checkout / "cli" / "asb"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("# init\n")
        (pkg / "readiness.py").write_text("# readiness\n")
        (pkg / "runtime_check.py").write_text("def main(): return 0\n")
        self.target_base = self.tmp / "runtime_base"

    def _resolve(self):
        with mock.patch.object(supervisor, "_current_revision", return_value="rev1") as rev:
            result = supervisor._resolve_versioned_runtime(target_base=self.target_base, root=self.checkout)
        rev.assert_called_once()
        return result


class TestCheckoutRevision(_CheckoutCase):
    """R6: falha do git nao vira "dev", um valor indistinguivel de uma revisao real."""

    def test_valid_revision_is_returned(self) -> None:
        done = subprocess.CompletedProcess([], 0, "0123456789ab\n", "")
        with mock.patch("subprocess.run", return_value=done) as run:
            self.assertEqual(supervisor._current_revision(self.checkout), "0123456789ab")
        run.assert_called_once()

    def test_git_failures_raise_instead_of_returning_dev(self) -> None:
        failures = {
            "rc 128": subprocess.CalledProcessError(128, ["git"], "", "fatal: not a git repository"),
            "git ausente": FileNotFoundError(2, "No such file or directory", "git"),
        }
        for name, exc in failures.items():
            with self.subTest(name), mock.patch("subprocess.run", side_effect=exc) as run:
                with self.assertRaises(RuntimeError) as cm:
                    supervisor._current_revision(self.checkout)
                run.assert_called_once()
                self.assertIn("revisao do checkout", str(cm.exception))

    def test_malformed_revision_raises(self) -> None:
        for out in ("", "abc/def\n", "a b\n", "..\n"):
            with self.subTest(out=out), \
                    mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, out, "")):
                with self.assertRaises(RuntimeError):
                    supervisor._current_revision(self.checkout)

    def test_resolution_without_revision_refuses_before_installing(self) -> None:
        err = subprocess.CalledProcessError(128, ["git"], "", "fatal: not a git repository")
        with mock.patch("subprocess.run", side_effect=err), \
                mock.patch.object(supervisor, "install_runtime") as reinstall, \
                self.assertRaises(RuntimeError):
            supervisor._resolve_versioned_runtime(target_base=self.target_base, root=self.checkout)
        reinstall.assert_not_called()
        self.assertFalse(self.target_base.exists())


class TestCheckoutAnchoredRuntime(_CheckoutCase):
    def test_joint_launcher_and_manifest_tamper_is_reinstalled_from_checkout(self) -> None:
        launcher, _, rev = self._resolve()
        pristine = launcher.read_bytes()
        forge(launcher.parent, "launcher.sh", b"#!/bin/sh\necho forjado\n")
        launcher2, _, rev2 = self._resolve()
        self.assertEqual((rev, rev2), ("rev1", "rev1"))
        self.assertEqual(launcher2.read_bytes(), pristine)

    def test_joint_package_module_tamper_is_reinstalled(self) -> None:
        dest = self._resolve()[0].parent
        forge(dest, "asb/readiness.py", b"# forjado\n")
        self._resolve()
        self.assertEqual((dest / "asb" / "readiness.py").read_text(), "# readiness\n")

    def test_forged_extra_file_listed_in_manifest_is_removed(self) -> None:
        dest = self._resolve()[0].parent
        forge(dest, "asb/extra.py", b"x = 1\n")
        self._resolve()
        self.assertFalse((dest / "asb" / "extra.py").exists())

    def test_launcher_mode_change_triggers_reinstallation(self) -> None:
        launcher = self._resolve()[0]
        launcher.chmod(0o644)
        self.assertEqual(self._resolve()[0].stat().st_mode & 0o777, 0o755)

    def test_reinstallation_that_still_fails_validation_raises(self) -> None:
        dest = self._resolve()[0].parent
        forge(dest, "launcher.sh", b"#!/bin/sh\n")
        with mock.patch.object(supervisor, "install_runtime") as reinstall, self.assertRaises(RuntimeError):
            self._resolve()
        reinstall.assert_called_once()

    def test_expected_manifest_is_derived_from_checkout(self) -> None:
        dest = install.install_runtime(self.checkout, "rev1", target_base=self.target_base)
        self.assertEqual(install.runtime_manifest(self.checkout, "rev1"),
                         json.loads((dest / "manifest.json").read_text()))


class TestRuntimeRootSymlinks(_CheckoutCase):
    """Raiz de confianca: nem o diretorio do runtime nem o manifesto podem ser symlink."""

    def test_runtime_dir_as_symlink_is_refused(self) -> None:
        dest = self._resolve()[0].parent
        moved = dest.parent / f"{dest.name}-real"
        dest.rename(moved)
        dest.symlink_to(moved, target_is_directory=True)
        self.assertFalse(supervisor._validate_installed_runtime(dest, install.runtime_manifest(self.checkout, "rev1")))

    def test_manifest_as_symlink_is_refused(self) -> None:
        dest = self._resolve()[0].parent
        manifest = dest / "manifest.json"
        elsewhere = dest.parent / "manifest-real.json"
        manifest.rename(elsewhere)
        manifest.symlink_to(elsewhere)
        self.assertFalse(supervisor._validate_installed_runtime(dest, install.runtime_manifest(self.checkout, "rev1")))


class TestCallerAnchoredRuntime(_CheckoutCase):
    def _custom(self):
        dest = install.install_runtime(self.checkout, "rev1", target_base=self.tmp / "custom")
        return dest, json.loads((dest / "manifest.json").read_text())

    def test_helper_path_without_caller_manifest_is_refused(self) -> None:
        dest, _ = self._custom()
        with self.assertRaises(ValueError):
            supervisor._resolve_versioned_runtime(helper_path=dest / "launcher.sh")

    def test_helper_path_with_caller_manifest_is_accepted(self) -> None:
        dest, expected = self._custom()
        launcher, check, rev = supervisor._resolve_versioned_runtime(
            helper_path=dest / "launcher.sh", runtime_manifest=expected)
        self.assertEqual((launcher, check, rev), (dest / "launcher.sh", dest / "runtime_check.py", "rev1"))

    def test_joint_tamper_after_caller_anchor_is_refused(self) -> None:
        dest, expected = self._custom()
        forge(dest, "launcher.sh", b"#!/bin/sh\necho forjado\n")
        with self.assertRaises(RuntimeError):
            supervisor._resolve_versioned_runtime(helper_path=dest / "launcher.sh", runtime_manifest=expected)

    def test_sibling_that_is_not_the_launcher_is_refused(self) -> None:
        dest, expected = self._custom()
        with self.assertRaises(ValueError):
            supervisor._resolve_versioned_runtime(helper_path=dest / "runtime_check.py", runtime_manifest=expected)

    def test_symlinked_launcher_is_refused(self) -> None:
        dest, expected = self._custom()
        real = self.tmp / "real-launcher.sh"
        real.write_bytes((dest / "launcher.sh").read_bytes())
        real.chmod(0o755)
        (dest / "launcher.sh").unlink()
        (dest / "launcher.sh").symlink_to(real)
        with self.assertRaises(RuntimeError):
            supervisor._resolve_versioned_runtime(helper_path=dest / "launcher.sh", runtime_manifest=expected)

    def test_missing_runtime_check_is_refused(self) -> None:
        dest, expected = self._custom()
        (dest / "runtime_check.py").unlink()
        with self.assertRaises(RuntimeError):
            supervisor._resolve_versioned_runtime(helper_path=dest / "launcher.sh", runtime_manifest=expected)

    def test_nonexistent_helper_path_is_refused(self) -> None:
        _, expected = self._custom()
        with self.assertRaises(RuntimeError):
            supervisor._resolve_versioned_runtime(
                helper_path=self.tmp / "nada" / "launcher.sh", runtime_manifest=expected)


class TestLauncherExecution(_CheckoutCase):
    def _run_launcher(self, podman_script: str) -> subprocess.CompletedProcess[str]:
        dest = install.install_runtime(self.checkout, "rev1", target_base=self.target_base)
        fake_bin = self.tmp / "bin"
        fake_bin.mkdir()
        podman = fake_bin / "podman"
        podman.write_text(podman_script)
        podman.chmod(0o755)
        env = dict(os.environ, PATH=f"{fake_bin}:{os.environ.get('PATH', '')}")
        return subprocess.run([str(dest / "launcher.sh"), "my-container"], capture_output=True, text=True, env=env)

    def test_running_container_is_attached(self) -> None:
        res = self._run_launcher(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"inspect\" ]; then echo running; exit 0; fi\n"
            "if [ \"$1\" = \"attach\" ]; then echo \"ATTACHED $*\"; exit 0; fi\n"
            "exit 1\n")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ATTACHED attach --sig-proxy=false my-container", res.stdout)

    def test_stopped_container_is_started_attached(self) -> None:
        res = self._run_launcher(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"inspect\" ]; then echo exited; exit 0; fi\n"
            "if [ \"$1\" = \"start\" ]; then echo \"STARTED $*\"; exit 0; fi\n"
            "exit 1\n")
        self.assertEqual(res.returncode, 0)
        self.assertIn("STARTED start --attach --sig-proxy=false my-container", res.stdout)

    def test_unexpected_state_fails(self) -> None:
        res = self._run_launcher(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"inspect\" ]; then echo corrupt; exit 0; fi\n"
            "exit 1\n")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("estado inesperado", res.stderr)


if __name__ == "__main__":
    unittest.main()
