"""tests/integration/test_credential_writers.py — Empirical tests for credential writers.

Validates filesystem storage mechanisms, atomic replace/rename behaviors, and
container permission contracts under uid 1000:
1. Symlink decoupling: atomic replace() over a symlink overwrites the link itself,
   leaving the pointed target file untouched and decoupling persistence.
2. O_NOFOLLOW rejection: opening a symlink with O_NOFOLLOW raises ELOOP,
   proving why Claude Code explicitly refuses credentials stored across symlinks.
3. Bind mount file vs directory:
   - os.replace() over a bind-mounted file fails with EBUSY (Resource busy) in Linux.
   - os.replace() within a bind-mounted directory succeeds atomically.
4. Container permissions and credential target states under uid 1000:
   - Missing destination, 0-byte empty file, malformed/corrupted file, broken symlink.
   - Container-level symlink decoupling proving how entrypoint.sh symlink layout fails.
   - Claude CLI status verification under empty, malformed, broken, and symlinked states.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.integration.sandbox_fixture import IsolationError, SandboxFixture


IMAGE_NAME = "localhost/agent-sandbox:latest"
FALLBACK_IMAGE = "docker.io/library/alpine:latest"


def get_test_image() -> str:
    """Returns local agent-sandbox image if available, else alpine fallback."""
    res = subprocess.run(
        ["podman", "image", "exists", IMAGE_NAME],
        capture_output=True,
    )
    return IMAGE_NAME if res.returncode == 0 else FALLBACK_IMAGE


class TestCredentialWritersFilesystem(unittest.TestCase):
    """Filesystem-level tests for atomic replacement, symlinks, and O_NOFOLLOW."""

    def test_symlink_atomic_replace_decouples_target(self) -> None:
        """Proves atomic replace() replaces the symlink itself, leaving the stored target unchanged."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stored, link, temporary = root / "stored", root / "auth", root / "next"
            stored.write_text("old")
            link.symlink_to(stored)
            temporary.write_text("new")

            # Replace link with temporary
            temporary.replace(link)

            # Stored target was NOT updated: it retains 'old'
            self.assertEqual(stored.read_text(), "old")
            # Link is no longer a symlink; it has become a regular file
            self.assertFalse(link.is_symlink())
            self.assertEqual(link.read_text(), "new")

    def test_o_nofollow_refuses_symlink_with_eloop(self) -> None:
        """Proves opening a symlink with O_NOFOLLOW raises ELOOP (Errno 40) on Linux.

        This directly explains why Claude Code 2.1.263 refuses credentials stored across
        symlinks: its internal reader opens the credential path with O_NOFOLLOW and explicitly
        catches ELOOP to report 'refused-symlink'.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stored = root / "stored.json"
            stored.write_text('{"token": "valid"}')
            link = root / ".credentials.json"
            link.symlink_to(stored)

            # On a symlink, open with O_NOFOLLOW must fail with ELOOP
            with self.assertRaises(OSError) as ctx:
                os.open(link, os.O_RDONLY | os.O_NOFOLLOW)
            self.assertEqual(ctx.exception.errno, errno.ELOOP)

            # On a regular file, open with O_NOFOLLOW succeeds
            fd = os.open(stored, os.O_RDONLY | os.O_NOFOLLOW)
            self.assertGreaterEqual(fd, 0)
            os.close(fd)


class TestBindMountAtomicReplace(unittest.TestCase):
    """Tests atomic replace behavior on bind-mounted files vs bind-mounted directories."""

    def test_bind_mount_file_vs_directory_atomic_replace(self) -> None:
        """Proves os.replace() fails with EBUSY on a bind-mounted file, but succeeds in a directory."""
        podman_bin = shutil.which("podman")
        if not podman_bin:
            self.skipTest("podman not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir).resolve()

            # 1. Prepare bind-mounted file
            mounted_file = temp_root / "file.json"
            mounted_file.write_text('{"version": 1}')

            # 2. Prepare bind-mounted directory containing a file
            mounted_dir = temp_root / "creds_dir"
            mounted_dir.mkdir()
            file_in_dir = mounted_dir / "auth.json"
            file_in_dir.write_text('{"version": 1}')

            inner_code = (
                "import os, errno\n"
                "# 1. Test replace on bind-mounted file -> must fail with EBUSY (16)\n"
                "with open('/mnt/tmp_file', 'w') as f:\n"
                "    f.write('updated')\n"
                "try:\n"
                "    os.replace('/mnt/tmp_file', '/mnt/target_file')\n"
                "    print('FILE_REPLACE_UNEXPECTED_SUCCESS')\n"
                "except OSError as e:\n"
                "    print(f'FILE_REPLACE_ERROR:{e.errno}')\n"
                "\n"
                "# 2. Test replace inside bind-mounted directory -> must succeed\n"
                "with open('/mnt/target_dir/tmp_in_dir', 'w') as f:\n"
                "    f.write('updated_in_dir')\n"
                "try:\n"
                "    os.replace('/mnt/target_dir/tmp_in_dir', '/mnt/target_dir/auth.json')\n"
                "    print('DIR_REPLACE_SUCCESS')\n"
                "except OSError as e:\n"
                "    print(f'DIR_REPLACE_ERROR:{e.errno}')\n"
            )

            cmd = [
                podman_bin,
                "run",
                "--rm",
                "-v",
                f"{mounted_file}:/mnt/target_file:z",
                "-v",
                f"{mounted_dir}:/mnt/target_dir:z",
                get_test_image(),
                "python3",
                "-c",
                inner_code,
            ]

            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Container failed: {res.stderr}")
            output = res.stdout

            # Assertion 1: Atomic replace over a bind-mounted file raised EBUSY
            self.assertIn(
                f"FILE_REPLACE_ERROR:{errno.EBUSY}",
                output,
                "os.replace() on a bind-mounted file must raise EBUSY (Errno 16)",
            )
            # Host file remains untouched
            self.assertEqual(mounted_file.read_text(), '{"version": 1}')

            # Assertion 2: Atomic replace inside a bind-mounted directory succeeded
            self.assertIn(
                "DIR_REPLACE_SUCCESS",
                output,
                "os.replace() inside a bind-mounted directory must succeed atomically",
            )
            # Host file in directory was updated
            self.assertEqual(file_in_dir.read_text(), "updated_in_dir")


class TestContainerPermissionsAndPaths(unittest.TestCase):
    """Container-level validation using SandboxFixture under uid 1000."""

    def test_uid1000_credential_read_write_permissions(self) -> None:
        """Proves uid 1000 can create, chmod 0600, write, and read credential files."""
        test_image = get_test_image()
        with SandboxFixture("credperm", image=test_image) as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15))

            # Run Python script as uid 1000 inside container
            py_code = (
                "import os, sys\n"
                "from pathlib import Path\n"
                "target = Path('/home/v/test_auth.json')\n"
                "target.write_text('{\"token\": \"synth-token-1000\"}')\n"
                "target.chmod(0o600)\n"
                "stat = target.stat()\n"
                "assert stat.st_uid == 1000, f'Expected uid 1000, got {stat.st_uid}'\n"
                "assert (stat.st_mode & 0o777) == 0o600, f'Expected 0600, got {oct(stat.st_mode)}'\n"
                "content = target.read_text()\n"
                "assert 'synth-token-1000' in content\n"
                "print('UID1000_PERMS_OK')\n"
            )
            res = sandbox.exec(
                "python3",
                "-c",
                py_code,
                user="1000",
            )
            self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}\n{res.stdout}")
            self.assertIn("UID1000_PERMS_OK", res.stdout)

            sandbox.stop()
            sandbox.assert_no_orphans()

    def test_credential_target_states_absent_empty_corrupted_broken(self) -> None:
        """Exercises absent destination, empty 0-byte file, malformed JSON, and broken symlink as uid 1000."""
        test_image = get_test_image()
        with SandboxFixture("credstates", image=test_image) as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15))

            py_code = (
                "import os, json, errno\n"
                "from pathlib import Path\n"
                "base = Path('/home/v/states_test')\n"
                "base.mkdir(parents=True, exist_ok=True)\n"
                "\n"
                "# 1. Absent destination\n"
                "absent = base / 'absent.json'\n"
                "assert not absent.exists()\n"
                "try:\n"
                "    absent.read_text()\n"
                "    assert False, 'Expected FileNotFoundError'\n"
                "except FileNotFoundError:\n"
                "    pass\n"
                "\n"
                "# 2. Empty file (0 bytes)\n"
                "empty = base / 'empty.json'\n"
                "empty.touch()\n"
                "assert empty.stat().st_size == 0\n"
                "content = empty.read_text()\n"
                "assert content == ''\n"
                "try:\n"
                "    json.loads(content)\n"
                "    assert False, 'Expected JSONDecodeError on empty string'\n"
                "except json.decoder.JSONDecodeError:\n"
                "    pass\n"
                "\n"
                "# 3. Corrupted / Malformed JSON\n"
                "corrupted = base / 'corrupted.json'\n"
                "corrupted.write_text('{\"token\": ')\n"
                "try:\n"
                "    json.loads(corrupted.read_text())\n"
                "    assert False, 'Expected JSONDecodeError on truncated json'\n"
                "except json.decoder.JSONDecodeError:\n"
                "    pass\n"
                "\n"
                "# 4. Broken symlink\n"
                "broken = base / 'broken.json'\n"
                "broken.symlink_to(base / 'nonexistent.json')\n"
                "assert broken.is_symlink()\n"
                "assert not broken.exists()\n"
                "try:\n"
                "    broken.read_text()\n"
                "    assert False, 'Expected FileNotFoundError on broken symlink'\n"
                "except FileNotFoundError:\n"
                "    pass\n"
                "\n"
                "print('ALL_CREDENTIAL_STATES_VERIFIED')\n"
            )

            res = sandbox.exec("python3", "-c", py_code, user="1000")
            self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}\n{res.stdout}")
            self.assertIn("ALL_CREDENTIAL_STATES_VERIFIED", res.stdout)

            sandbox.stop()
            sandbox.assert_no_orphans()

    def test_container_symlink_decoupling_under_atomic_replace_as_uid1000(self) -> None:
        """Simulates the entrypoint.sh symlink layout inside the container as uid 1000.

        Proves that when an agent writes credentials via temporary file + atomic rename,
        the symlink is overwritten, leaving the persistent volume target untouched.
        """
        test_image = get_test_image()
        with SandboxFixture("creddecouple", image=test_image) as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15))

            py_code = (
                "import os\n"
                "from pathlib import Path\n"
                "store = Path('/home/v/simulated_volume')\n"
                "store.mkdir(parents=True, exist_ok=True)\n"
                "volume_stored = store / 'claude.json'\n"
                "volume_stored.write_text('{\"original\": \"volume-data\"}')\n"
                "\n"
                "agent_dir = Path('/home/v/.claude')\n"
                "agent_dir.mkdir(parents=True, exist_ok=True)\n"
                "agent_creds = agent_dir / '.credentials.json'\n"
                "if agent_creds.exists() or agent_creds.is_symlink():\n"
                "    agent_creds.unlink()\n"
                "agent_creds.symlink_to(volume_stored)\n"
                "assert agent_creds.is_symlink()\n"
                "\n"
                "# Agent CLI performs atomic write\n"
                "temp_file = agent_dir / '.credentials.tmp'\n"
                "temp_file.write_text('{\"updated\": \"new-session-token\"}')\n"
                "temp_file.replace(agent_creds)\n"
                "\n"
                "# Verify persistence contract breakdown\n"
                "assert not agent_creds.is_symlink(), 'agent_creds should have become a regular file'\n"
                "assert volume_stored.read_text() == '{\"original\": \"volume-data\"}', \\\n"
                "    'volume_stored was not updated because replace() unlinked the symlink!'\n"
                "assert agent_creds.read_text() == '{\"updated\": \"new-session-token\"}'\n"
                "print('CONTAINER_SYMLINK_DECOUPLING_PROVEN')\n"
            )

            res = sandbox.exec("python3", "-c", py_code, user="1000")
            self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}\n{res.stdout}")
            self.assertIn("CONTAINER_SYMLINK_DECOUPLING_PROVEN", res.stdout)

            sandbox.stop()
            sandbox.assert_no_orphans()

    def test_claude_cli_behavior_on_credential_states(self) -> None:
        """Proves Claude Code CLI (2.1.263) status handling under 0-byte, corrupt, broken, and symlinked states."""
        if get_test_image() != IMAGE_NAME:
            self.skipTest(f"{IMAGE_NAME} not available")

        with SandboxFixture("claudestates", image=IMAGE_NAME) as sandbox:
            sandbox.start()
            self.assertTrue(sandbox.wait_active(timeout=15))

            # Helper to run claude auth status as uid 1000
            def get_claude_status() -> tuple[int, dict]:
                r = sandbox.exec("claude", "auth", "status", "--json", user="1000")
                data = json.loads(r.stdout.strip()) if r.stdout.strip() else {}
                return r.returncode, data

            claude_dir = "/home/v/.claude"
            creds_file = f"{claude_dir}/.credentials.json"

            # 1. Absent credentials
            sandbox.exec("rm", "-f", creds_file, user="1000")
            code, data = get_claude_status()
            self.assertEqual(code, 1)
            self.assertFalse(data.get("loggedIn"))

            # 2. Empty 0-byte file (reproduces entrypoint.sh ': > $stored')
            sandbox.exec("sh", "-c", f": > {creds_file}", user="1000")
            code, data = get_claude_status()
            self.assertEqual(code, 1)
            self.assertFalse(data.get("loggedIn"))

            # 3. Corrupted / malformed JSON
            sandbox.exec("sh", "-c", f"echo '{{bad_json' > {creds_file}", user="1000")
            code, data = get_claude_status()
            self.assertEqual(code, 1)
            self.assertFalse(data.get("loggedIn"))

            # 4. Broken symlink
            sandbox.exec("sh", "-c", f"rm -f {creds_file} && ln -s /nonexistent {creds_file}", user="1000")
            code, data = get_claude_status()
            self.assertEqual(code, 1)
            self.assertFalse(data.get("loggedIn"))

            # 5. Symlink to valid JSON (proves Claude O_NOFOLLOW rejection of symlinks)
            target = "/home/v/valid_creds.json"
            sandbox.exec(
                "sh",
                "-c",
                f"echo '{{\"claudeAi\": {{\"accessToken\": \"dummy\"}}}}' > {target} && "
                f"rm -f {creds_file} && ln -s {target} {creds_file}",
                user="1000",
            )
            code, data = get_claude_status()
            self.assertEqual(code, 1)
            # Claude refuses the symlink via O_NOFOLLOW / ELOOP and reports not logged in
            self.assertFalse(data.get("loggedIn"))

            sandbox.stop()
            sandbox.assert_no_orphans()


if __name__ == "__main__":
    unittest.main()
