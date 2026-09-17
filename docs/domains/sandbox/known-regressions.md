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
`tests/test-transaction.sh`.

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

**Correct form:** distinguish the states. Present-but-unparseable must raise,
never fall into the branch a legitimate state also takes. Never let a
diagnostic path report success because it failed to read its own input. (The
`legacy` runtime was later removed by Emenda A; the shape applies to any
manifest or state file.)

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

---

## R10 — Initializing the rootless network namespace before real connectivity

**Shape:** anything that creates Podman's shared rootless network namespace
early in the session: `podman unshare --rootless-netns` in an `ExecStartPre`,
in `up`/`resume`, or as recovery advice; a container with a restart policy
that `podman-restart.service` brings up at login.

**Consequence:** the namespace is born before the host has working egress and
stays without egress for as long as anything holds it open. Squid answers the
agent locally with 500/503, which looks like a provider or login failure. The
project's own drop-in did this on every boot (pilot boots 1 and 3); a leaked
test container with `--restart=always` on `pasta` would have done the same.
Running the `unshare` again does not repair it.

**Correct form:** only systemd starts ASB containers, every container is
`--restart=no`, and every workspace unit `Requires=`/`After=`
`asb-network.service`, which exits only after a real probe to
`github.com:443` succeeds. The namespace is then born by the first proxy
start, after connectivity. Recovery is to suspend and resume every workspace
with the host network up.

**Prisoner tests:** `test_up_never_initializes_the_rootless_namespace`,
`test_resume_never_initializes_the_rootless_namespace`,
`TestNoRootlessNetnsAdvice` (static guard over the diagnostic modules),
`test_egress_uplink_unreachable`; `asb-agent doctor` also lists third-party
producers of the namespace at boot.

---

## R11 — Driving a systemd-supervised container with Podman directly

**Shape:** `podman restart`, `podman start` or `podman stop` on a container
whose lifecycle belongs to a systemd unit — in code or in remediation text.

**Consequence:** units run `podman start --attach`; restarting the container
kills that attached process, so systemd runs `ExecStopPost=podman stop` and
stops the container it just saw restarted. `reload-allowlist` used
`podman restart` on the proxy and left it stopping right after reporting
success. A container started with `podman start` outside its unit leaves the
unit inactive and without `Restart=`; the keyring remediation advised exactly
that.

**Correct form:** go through the unit: `systemctl --user try-restart`
(restart only if running) or `restart`/`start` of the `asb-*.service`. A
suspended workspace stays suspended; the next `resume` reads new
configuration.

**Prisoner tests:** `test_reload_allowlist_renders_squid_and_restarts_proxy`,
`tests/test-reload-allowlist.sh`,
`test_check_keyring_service_container_stopped`.

---

## R12 — PID-derived names for temporary paths on a shared volume

**Shape:** naming a temporary file or directory with `$$` (or `os.getpid()`)
when the path lives on a volume shared between containers.

**Consequence:** the entrypoint is PID 1 in **every** container, so `$$` is
the same everywhere. Two agents starting together (every boot, after the
network wait) used the same `plugins.asb-staging.1` inside the shared
`~/.claude`; one deleted the copy the other was writing and died with
`Directory not empty`, surviving only through `Restart=always` and spending
one of the three starts in `StartLimitBurst`.

**Correct form:** serialize the swap across containers with a kernel lock on
the shared inode (`flock` on the destination's parent directory), and never
assume a PID is unique outside one PID namespace.

**Prisoner test:** `tests/integration/test_entrypoint_concurrency.py`.

---

## R13 — A test that pins the defect's own output

**Shape:** a unit test asserting the literal remediation or command a
diagnostic emits, written when that remediation was believed correct.

**Consequence:** when the advice is proven wrong, the suite stays green and
actively defends it. Two doctor tests required
`podman unshare --rootless-netns true` (R10) and the shell test
`tests/test-doctor.sh` required it again; the keyring test required
`podman start asb-keyring` (R11). All three were found by real execution, not
by the suite.

**Correct form:** when a real run disproves a behavior, search the tests for
the literal string before changing the code, and pair the new expectation with
an `assertNotIn` of the old one so the wrong advice cannot return silently.
