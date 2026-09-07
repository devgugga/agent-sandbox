# Known Regressions — Sandbox Domain

Catalogue of defects this repository has already diagnosed and fixed. Each
entry records the **shape** of the bug, not just its instance: the same shape
has been reintroduced in a different file after the original fix landed.

Use this document as a checklist against a diff. A diff that reproduces one of
these shapes is a regression finding, regardless of how the new code is
written or how well it is tested — the shape itself is the defect.

Add an entry whenever a defect is fixed AND its shape could plausibly recur in
another file. Do not add one-off typos.

---

## R1 — Prefix matching without a delimiter

**Shape:** matching resources by `"<prefix>"` when names are
`<prefix>-<suffix>`, so `asb-demo-` also matches `asb-demo-2-`.

**Consequence:** operations on one workspace destroy a sibling workspace.

**History:** originally fixed in `_sweep_containers`, which carries the
comment "casar prefixo sem delimitador casava workspaces irmaos (ex: asb-demo-
casava asb-demo-2-)". **Reintroduced two tasks later** in
`supervisor.remove_workspace_units`, which globbed `asb-{ws}-*.service` and
would unlink `asb-demo-2-agent.service` on `down --workspace demo`.

**Correct form:** enumerate exact resource names from the workspace's own
`runtime.json` manifest, which already carries `unit` per container. Where a
manifest is unavailable, match against a known suffix set — never a bare
prefix glob.

**Prisoner test:** `test_remove_workspace_units_does_not_touch_sibling_with_shared_prefix`
(creates real sibling unit files); sibling-isolation block in
`tests/test-transaction.sh`. Note the shell block only exercises the legacy
path, so it cannot catch a systemd-path recurrence on its own.

---

## R2 — Credential storage behind a symlink or a single-file bind mount

**Shape:** persisting a provider credential by symlinking the provider's own
path to a shared volume, or by bind-mounting a single file.

**Consequence:** silent, total credential loss. Any writer using atomic
replacement (`rename`/`os.replace`) replaces the *symlink itself* with a
regular file, severing the link to the volume. A single-file bind mount fails
that same `rename` with `EBUSY`.

**Provider specifics:** Claude Code 2.1.x opens credentials with
`O_RDONLY | O_NOFOLLOW`; on a symlink Linux returns `ELOOP`, which Claude
catches and reports as `kind: "refused-symlink"` — it treats the credential as
**absent**, not as an error. The entrypoint additionally created the target
with `: > "$stored"`, leaving a 0-byte file that could never parse.

**Correct form:** mount the credential **directory**, never a single file and
never a symlink. Directory mounts survive atomic replacement.

**Prisoner tests:** `tests/integration/test_credential_writers.py`.

---

## R3 — Treating a provider CLI's exit 0 as proof the action happened

**Shape:** invoking a provider CLI and inferring success from its return code.

**Consequence:** `claude /login` on 2.1.x prints "/login isn't available in
this environment" and **exits 0 without logging in**. The lifecycle code
treated that as a successful login for months. The real command is
`claude auth login`.

**Correct form:** verify the post-condition independently — for credentials,
in a *fresh client* — and pin the CLI version the contract was validated
against. A negative explicit output always outranks a positive substring.

---

## R4 — Substring matching a status code

**Shape:** `"403" in output` where `output` also contains ports, hostnames or
byte counts. A probe against port `40300` classified the proxy as denied.

**Correct form:** match delimited (`" 403 "`), or parse the status line
positionally. Applies to any numeric token scanned out of tool output.

**Prisoner test:** `test_probe_proxy_403_substring_in_port_number_does_not_false_positive`.

---

## R5 — Hardcoded identity default in a probe

**Shape:** a probe defaulting to a developer's own username
(`probe_ssh(..., user="v")`) while the code that reports the value uses
`getpass.getuser()`.

**Consequence:** the probe becomes a hard gate that fails a healthy workspace
on any machine whose user is not `v`.

**Correct form:** resolve identity from the environment at the call site.
Known remaining instance: `readiness.probe_workspace` still defaults to `"v"`
on the `resume` path.

---

## R6 — Collapsing "absent" and "unreadable" into a default branch

**Shape:** `try: ... except Exception: return <default>` where the default is
also a legitimate state.

**Consequence:** `_runtime_of` returned `"legacy"` for a corrupt
`runtime.json`, so `resume` skipped supervision entirely, started containers
created with `--restart=no`, and **returned 0 with a success JSON line** while
the workspace was unsupervised.

**Correct form:** distinguish the states. Absent manifest is legacy and fine;
present-but-unparseable must raise. Never let a diagnostic path report success
because it failed to read its own input.

---

## R7 — Dead mocks hiding a deleted call site

**Shape:** tests keep patching a function after production stopped calling it.
Nothing fails, so the removal is invisible in review.

**Consequence:** `install.podman_restart()` was dropped from the default
legacy `up` path with no production call site left; three tests still mocked
it and all passed.

**Correct form:** a mock that is not asserted on is not a mock, it is
decoration. Give every patch an `assert_called*`, or delete it.

---

## R8 — Integration tests that create resources without proving teardown

**Shape:** an integration test creating podman resources without asserting
they are gone afterwards.

**Consequence:** a run leaked 8 `asb-test-fwdcoll-*` volumes onto the
operator's machine. `SandboxFixture` already provided `assert_no_orphans()`;
the test simply did not use it.

**Correct form:** every integration test uses `SandboxFixture` and its
teardown assertions. Containers, networks AND volumes — the leak was volumes
only, because the container assertions passed.

---

## R9 — `podman start --attach` against an already-running container

**Shape:** a systemd unit whose `ExecStart` is literally
`podman start --attach <name>`.

**Consequence:** on Podman 6.1 rootless this exits **125**
("cannot start an already running container"). Systemd then runs
`ExecStopPost`, which stops the container; `Restart=always` retries after
`RestartSec`, and the second attempt succeeds — self-healing at the cost of a
5-second bounce on every reconnect.

**Correct form:** a launcher helper that runs `podman attach` when the
container is running and `podman start --attach` when it is stopped.
Reconnection is then instantaneous.

**Note:** `ExecStopPost` is load-bearing and must not be removed — when
`ExecStartPost` fails, systemd does **not** run `ExecStop`, only
`ExecStopPost`. Without it, failed startups leak running containers.

**Prisoner tests:** `tests/integration/test_supervisor_pilot.py`.
