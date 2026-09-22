"""server/tests/test_openapi.py — Task 6: `asb-server openapi` byte-stability.

Amendment Section E: this property has been maintained by hand and
verified ad hoc since Task 3 (`main.py`'s `sort_keys=True`); this file
makes it a test. Spec Section 5's `pnpm check:api` regenerates the schema
into a temporary file and fails on any difference — a flaky schema here
would make that check fail randomly and nobody would trust it.

Both runs go through the REAL entry point, in a subprocess with a fresh
`ASB_CONFIG_ROOT`: `asb_server.settings.CONFIG_ROOT` and `Settings`'
default `token_path`/`session_key_path` are module-level constants
resolved at import time (see `settings.py`), so only a fresh process
picks up a fresh `ASB_CONFIG_ROOT` — patching the already-imported module
in-process would not exercise the same code path `asb-server openapi`
actually runs. This also verifies amendment Section F's "no secrets at
import or `create_app` time" property directly: the fresh config root is
still empty after both runs.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _run_openapi(config_root: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "asb_server.main", "openapi"],
        capture_output=True, check=True,
        env={"PATH": "/usr/bin:/bin", "ASB_CONFIG_ROOT": str(config_root)},
    )


class TestOpenapiByteStability(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_output_is_valid_json(self):
        result = _run_openapi(self.tmp)
        schema = json.loads(result.stdout)
        self.assertIn("openapi", schema)
        self.assertIn("paths", schema)

    def test_two_runs_are_byte_identical(self):
        first = _run_openapi(self.tmp)
        second = _run_openapi(self.tmp)
        self.assertEqual(first.stdout, second.stdout)

    def test_writes_nothing_to_disk(self):
        # A fresh, otherwise-untouched config root: if `openapi` created
        # or read the token/session-key files, this directory would no
        # longer be empty after the run.
        _run_openapi(self.tmp)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_documents_401_403_and_503_on_the_relevant_routes(self):
        # Task 5's documentation must not regress (amendment Section E).
        schema = json.loads(_run_openapi(self.tmp).stdout)
        tree_get = schema["paths"]["/api/tree"]["get"]["responses"]
        self.assertIn("401", tree_get)
        self.assertIn("503", tree_get)
        session_post = schema["paths"]["/api/auth/session"]["post"]["responses"]
        self.assertIn("401", session_post)
        self.assertIn("403", session_post)

    def test_static_catch_all_route_is_not_in_the_schema(self):
        # `static.py`'s SPA fallback is not part of the daemon's API
        # contract (spec Section 7.2 lists only the four `/api` routes);
        # `include_in_schema=False` keeps the generated client scoped to
        # the actual API surface.
        schema = json.loads(_run_openapi(self.tmp).stdout)
        for path in schema["paths"]:
            self.assertTrue(path.startswith("/api/"), path)


if __name__ == "__main__":
    unittest.main()
