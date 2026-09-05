# agent-sandbox v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the agent sandbox so that isolation is a property of network
topology rather than of rules that must be reapplied in order on every start,
collapsing four lifecycle paths into one.

**Architecture:** Each workspace gets a podman network created with
`--internal` (no default route, no external DNS). The agent container lives
only on that network and has no egress at all. A separate proxy container is
dual-homed (internal + external) and runs Squid with a domain allowlist;
optional sidecars — a filtered Docker socket reader and a TCP forwarder — are
each dual-homed only as far as their own job requires. Because the isolation is
the network definition, podman reconstructs it on every container start, so
`podman start` is a complete and safe resume, including after a reboot.

**Tech Stack:** Python 3.11+ (stdlib only, `tomllib`), Podman 6.x rootless,
Squid, nginx (broker only), systemd user units, bash for tests and Orca hooks.

**Spec:** `docs/superpowers/specs/2026-09-04-agent-sandbox-v2-design.md`
Read it before starting. This plan argues from it and cites its sections.

---

## Global Constraints

Every task's requirements implicitly include this section.

**Language and dependencies**
- Python **3.11 or newer**, **stdlib only**. No pip packages, no virtualenv, no
  build step. `tomllib` is why the profile format stays TOML (spec D6, D10).
- The CLI is a package of focused modules under `cli/asb/`, run straight from
  the checkout.
- Podman **4.0 or newer** (netavark + aardvark-dns are required for `--internal`
  and for container-name resolution). This host has 6.1.0.

**Portability (spec §16) — these are requirements, not aspirations**
- No absolute path of this checkout may be written into any system file. The
  v1 systemd unit baked `ExecStart=<checkout>/cli/agent-sandbox restore-all`,
  so moving the folder silently broke boot restore.
- Every installer is idempotent and re-runnable: `install-guards`,
  `install-broker`, and enabling `podman-restart.service`.
- The container user name and home come from **build args** `ASB_USER` and
  `ASB_HOME`, derived from `id -un` and `$HOME` at build time. Never hardcode
  `v` or `/home/v` anywhere (spec D4).

**Security invariants (spec §9.1) — a task that violates one is rejected**
1. The host `$HOME` is never mounted into any container.
2. No host SSH key, Git credential, PAT or `gh` token enters the sandbox.
3. `/var/run/docker.sock` is never mounted raw into the sandbox (spec D8).
4. The agent container never has external network, `CAP_NET_ADMIN`, or `sudo`.
5. `~/Data/Projects` is never mounted; only the workspace worktree.
6. Workspace state and the config staging tree live **outside** any writable
   mount (spec §5.2, §7.2). The allowlist inside the mount would let the agent
   edit its own allowlist.

**Must never be reintroduced (spec §15)**
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` anywhere in the image. It forces Claude's
  permission mode to `default`, cancelling the autonomy the sandbox exists to
  make safe.
- A comment between line-continued arguments in bash. `#` ends the logical line
  along with the backslash; the remaining arguments are orphaned. `bash -n`
  accepts it, so the suite stays green and it fails only at runtime.
- A non-deterministic workspace name (`$$`). `destroy` cannot reproduce it and
  resources leak while Orca reports success.
- Verifying a login by grepping for `logged in` — that string also matches
  "**not** logged in".
- A negative security assertion without a positive control (see Testing below).

**Testing**
- Python units: `python3 -m unittest discover -s tests/unit -v`
- Integration: `bash tests/<name>.sh` — each is standalone and cleans up after
  itself, including on failure.
- **Every assertion of the form "X is blocked" must be preceded by `require`
  from `tests/assert.sh`.** A blocked assertion passes for free when the
  container never came up: the command fails and the test concludes "blocked".
  `require` aborts the suite when the environment does not respond.
- When matching command output, match the **shape of a real answer**, never the
  presence of text. `dig +short` writes errors to stdout, so "any output"
  reports a DNS leak that does not exist.

**Commits (`docs/domains/git/commit-conventions.md`)**
- Literal gitmoji character in the title, never the `:shortcode:`.
- Title: `<gitmoji> <verb in imperative> <outcome>: <context>`
- Structured body is **mandatory**, wrapped at 76 columns, ending with
  `### 🚀 Outcome`.
- **Co-authorship trailers are strictly forbidden.**
- Never commit to `main` and never create a branch without explicit
  authorization from the operator in the active session. **Ask before Task 1.**

---

## File Structure

### Created

| File | Responsibility |
| :--- | :--- |
| `cli/asb-agent` | CLI entrypoint: argument parsing and dispatch only |
| `cli/asb/__init__.py` | package marker; holds nothing |
| `cli/asb/profile.py` | `.agent-sandbox.toml` → validated `Profile` |
| `cli/asb/squid.py` | allowlist + profile → `squid.conf` |
| `cli/asb/staging.py` | provision manifest → staging tree to bind-mount |
| `cli/asb/workspace.py` | workspace identity, on-disk layout, clone, state dir |
| `cli/asb/podman.py` | thin wrapper over the `podman` binary |
| `cli/asb/lifecycle.py` | `up`, `down`, `suspend`, `resume`, `purge`, `pull` |
| `cli/asb/doctor.py` | environment diagnosis, naming the exact fix command |
| `cli/asb/install.py` | guards, broker, `podman-restart.service` |
| `broker/nginx.conf.tmpl` | read-only Docker API filter |
| `broker/asb-docker-broker.service.tmpl` | systemd **system** unit for the broker |
| `tests/unit/` | Python unit tests (stdlib `unittest`) |
| `docs/domains/sandbox/README.md` | the system in one page |
| `docs/domains/sandbox/configuration.md` | `.agent-sandbox.toml` reference |
| `docs/domains/sandbox/security.md` | boundaries; what it does and does not protect |
| `docs/domains/sandbox/failure-modes.md` | the consolidated forensic record |

### Renamed

| From | To | Why |
| :--- | :--- | :--- |
| `cli/asb-agent` (the guard) | `cli/asb-guard` | The CLI takes the name `asb-agent` (spec §11). The guard is only ever *installed* as `asb-claude`, `asb-codex`, `asb-agy`, so its source filename is free. `image/asb-agent`, a second copy of the same guard, is deleted: the build context becomes the repository root so one file serves both host and image. |

### Deleted

`cli/agent-sandbox`, `cli/lib/pod.sh`, `cli/lib/auth.sh`, `cli/lib/attach.sh`,
`cli/lib/doctor.sh`, `cli/lib/profile.py`, `cli/lib/render_squid.py`,
`cli/lib/provision.py`, `image/Containerfile.net`, `image/firewall/apply.sh`,
`image/install-config.py`, `image/asb-agent`, `profiles/default.toml`, four
superseded test suites (`test-profile.sh`, `test-resume.sh`,
`test-readiness.sh`, `test-attached.sh` — Task 15 gives each a reason), and the
v1 documents `docs/domains/sandbox/{architecture,lifecycle,network,enforcement,authentication,credentials,troubleshooting,hexmed-notes}.md`.

Deletion happens in the task that replaces the file, never up front — a
half-deleted v1 with a half-built v2 is not testable.

### Preserved unchanged

`tests/assert.sh` (the `require` positive-control pattern), `image/squid/squid.conf.tmpl`,
`image/squid/allowlist-base.txt`, `image/start-keyring.sh`, `recipes/common.sh`
(logic, adapted paths).

---

## Task 0: Authorization and branch

**Files:** none

- [ ] **Step 1: Ask the operator where this work lands**

`AGENTS.md` §4.5 forbids committing to `main` and creating branches without
explicit authorization in the active session. Ask, in one message: "Trabalho na
`main` ou crio uma branch? (`AGENTS.md` exige sua autorização para as duas
coisas.)" Do not proceed until answered. If a branch is authorized, create it
before Task 1 and use it for every commit in this plan.

- [ ] **Step 2: Confirm the toolchain**

Run: `python3 --version && podman --version && git --version`
Expected: Python ≥ 3.11, Podman ≥ 4.0. If either is lower, stop and report —
`tomllib` and `--internal` name resolution are hard requirements.

---

## Task 1: Profile parsing

Reads `.agent-sandbox.toml` into a validated, fully-closed-by-default `Profile`.
Nothing else in the CLI reads TOML.

**Files:**
- Create: `cli/asb/__init__.py`
- Create: `cli/asb/profile.py`
- Test: `tests/unit/test_profile.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Profile` frozen dataclass with fields `allow: tuple[str, ...]`,
    `host_ports: tuple[int, ...]`, `container_mode: str`, `host_api: str`,
    `services: tuple[Service, ...]`
  - `Service` frozen dataclass with `name: str`, `image: str`,
    `env: dict[str, str]`
  - `load_profile(repo: Path) -> Profile`
  - `ProfileError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_profile.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'asb'`

- [ ] **Step 3: Write the implementation**

Create `cli/asb/__init__.py` as an empty file (the package holds no logic).

Create `cli/asb/profile.py`:

```python
"""cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado.

O padrao de TODO campo e o fechado: arquivo ausente equivale a arquivo vazio,
que equivale a sandbox isolado sem acesso algum ao Docker do host.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONTAINER_MODES = ("none", "nested")
HOST_API_LEVELS = ("none", "read")

# Nome de servico vira parte de nome de container (asb-<ws>-svc-<nome>), entao
# so aceita o que o podman aceita.
SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

# Chaves do esquema v1 que deixaram de existir. Recusar em vez de ignorar: um
# perfil antigo aceito em silencio produz um sandbox que nao faz o que o
# arquivo diz, e o operador so descobre quando algo nao alcanca o que deveria.
REMOVED_KEYS = {
    ("sandbox", "mode"):
        'o modo "attached" virou [docker] host_ports, que declara QUAIS portas',
    ("proxy", "java"):
        "removido: era um ajuste pontual que nunca foi exercitado",
    ("tools", "extra"):
        "declare ferramentas no mise.toml do projeto, ou em mise.local.toml "
        "para as que so voce quer",
}


class ProfileError(Exception):
    """Perfil invalido. A mensagem sempre nomeia o campo e o que fazer."""


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    allow: tuple[str, ...] = ()
    host_ports: tuple[int, ...] = ()
    container_mode: str = "none"
    host_api: str = "none"
    services: tuple[Service, ...] = ()


def _reject_removed(raw: dict) -> None:
    for (table, key), advice in REMOVED_KEYS.items():
        if key in raw.get(table, {}):
            raise ProfileError(
                f"[{table}] {key} nao existe mais neste esquema: {advice}")


def _strings(raw: dict, table: str, key: str) -> tuple[str, ...]:
    value = raw.get(table, {}).get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ProfileError(f"[{table}] {key} precisa ser uma lista de strings")
    return tuple(value)


def _ports(raw: dict) -> tuple[int, ...]:
    value = raw.get("docker", {}).get("host_ports", [])
    if not isinstance(value, list):
        raise ProfileError("[docker] host_ports precisa ser uma lista")
    ports = []
    for port in value:
        # bool e subclasse de int em Python; `true` numa lista de portas e
        # quase certamente engano do operador.
        if not isinstance(port, int) or isinstance(port, bool):
            raise ProfileError(
                f"[docker] host_ports: {port!r} nao e um numero de porta")
        if not 1 <= port <= 65535:
            raise ProfileError(f"[docker] host_ports: {port} fora de 1-65535")
        ports.append(port)
    return tuple(ports)


def _choice(raw: dict, key: str, allowed: tuple[str, ...], default: str) -> str:
    value = raw.get("docker", {}).get(key, default)
    if value not in allowed:
        raise ProfileError(
            f"[docker] {key} = {value!r}; valores aceitos: "
            + ", ".join(repr(a) for a in allowed))
    return value


def _services(raw: dict) -> tuple[Service, ...]:
    services = []
    for name, body in raw.get("services", {}).items():
        if not SERVICE_NAME.match(name):
            raise ProfileError(
                f"[services.{name}]: nome precisa casar {SERVICE_NAME.pattern} "
                "(vira parte do nome do container)")
        if not isinstance(body, dict) or not isinstance(body.get("image"), str):
            raise ProfileError(f"[services.{name}] exige image = \"...\"")
        env = body.get("env", {})
        if not isinstance(env, dict) or any(
                not isinstance(v, str) for v in env.values()):
            raise ProfileError(
                f"[services.{name}] env precisa mapear string para string")
        services.append(Service(name=name, image=body["image"], env=dict(env)))
    return tuple(services)


def load_profile(repo: Path) -> Profile:
    """Le o perfil do repositorio. Ausente equivale a vazio."""
    candidate = Path(repo) / ".agent-sandbox.toml"
    if not candidate.is_file():
        return Profile()
    try:
        raw = tomllib.loads(candidate.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(f"{candidate}: TOML invalido: {error}") from error

    _reject_removed(raw)
    return Profile(
        allow=_strings(raw, "network", "allow"),
        host_ports=_ports(raw),
        container_mode=_choice(raw, "mode", CONTAINER_MODES, "none"),
        host_api=_choice(raw, "host_api", HOST_API_LEVELS, "none"),
        services=_services(raw),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add cli/asb/__init__.py cli/asb/profile.py tests/unit/test_profile.py
git commit -F - <<'MSG'
✨ read the sandbox profile with a closed default: configuration

Introduces the v2 profile reader. Every field defaults to the closed
value, so a missing or empty .agent-sandbox.toml yields an isolated
sandbox with no Docker access of any kind.

### ✅ New features

Parses the three independent Docker axes (host_ports, mode, host_api),
the network allowlist and disposable service declarations into a frozen
Profile dataclass. Service names are constrained to what podman accepts,
since the name becomes part of a container name.

### 🧼 Best practices & validations

Keys from the v1 schema are rejected rather than ignored, and each
rejection names its replacement. A v1 profile accepted in silence would
produce a sandbox that does not do what the file says, and the operator
would only discover it when something failed to reach what it should.
Malformed TOML surfaces as ProfileError rather than leaking a
TOMLDecodeError to the caller.

### 🚀 Outcome

Profile parsing is covered by 16 unit tests and nothing else in the CLI
reads TOML. Next task builds workspace identity and layout on top of it.
MSG
```

---

## Task 2: Workspace identity, layout and state

Decides where everything lives on disk. This is the task that closes the
operator's problem #2 (worktrees unreachable from the host) and enforces spec
§5.2 (state outside the writable mount).

**Files:**
- Create: `cli/asb/workspace.py`
- Test: `tests/unit/test_workspace.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `workspace_id(repo: Path, env: Mapping[str, str]) -> str`
  - `Layout` frozen dataclass with `ws: str`, `project: str`, `mount: Path`,
    `project_root: Path`, `state: Path`
  - `layout_for(repo: Path, ws: str, home: Path) -> Layout`
  - `prepare_clone(origin: Path, layout: Layout) -> None`
  - `WorkspaceError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_workspace.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: FAIL — `ImportError: cannot import name 'layout_for'`

- [ ] **Step 3: Write the implementation**

Create `cli/asb/workspace.py`:

```python
"""cli/asb/workspace.py — identidade do workspace, layout em disco e clone.

Duas regras carregam este modulo inteiro:

1. O nome do workspace e DETERMINISTICO. Com um nome irreproduzivel o destroy
   nao encontra o que criar removeu, e recursos vazam em silencio enquanto o
   Orca reporta sucesso. No v1 isso aconteceu com um nome derivado de $$.
2. O estado do workspace fica FORA do mount gravavel. O squid.conf renderizado
   dentro do mount permitiria ao agente editar a propria allowlist.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

UNSAFE = re.compile(r"[^a-zA-Z0-9._-]")


class WorkspaceError(Exception):
    pass


@dataclass(frozen=True)
class Layout:
    ws: str
    project: str
    mount: Path
    project_root: Path
    state: Path


def _sanitize(value: str) -> str:
    # Colapsar repeticoes: sem isso "uuid::/a/b" vira "uuid---a-b" com um traco
    # por caractere trocado, e nomes como "hexmed-stack--f05b729e" aparecem.
    return re.sub(r"-{2,}", "-", UNSAFE.sub("-", value)).strip("-")


def workspace_id(repo: Path, env: Mapping[str, str]) -> str:
    """Identidade do workspace, sempre reproduzivel a partir das entradas.

    O Orca passa ORCA_VM_INSTANCE_ID, unico POR WORKSPACE. Sem ele a derivacao
    cai no caminho do repositorio — e como o Orca executa os hooks a partir do
    checkout primario, todo workspace do mesmo projeto receberia o mesmo nome e
    o segundo mataria o primeiro.
    """
    given = env.get("ORCA_VM_INSTANCE_ID") or env.get("ORCA_WORKSPACE_ID") or ""
    if given.strip():
        return _sanitize(given)
    # Normalizar ANTES de derivar: uma barra final muda o hash, e create e
    # destroy divergiriam se o caminho chegasse de formas diferentes.
    text = str(Path(repo)).rstrip("/")
    base = _sanitize(Path(text).name)
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"{base}-{digest}"


def layout_for(repo: Path, ws: str, home: Path) -> Layout:
    """Onde tudo mora. `home` e o mesmo caminho no host e no container (D4)."""
    project = _sanitize(Path(str(repo).rstrip("/")).name)
    mount = Path(home) / "asb-agent" / project / ws
    return Layout(
        ws=ws,
        project=project,
        mount=mount,
        project_root=mount / project,
        # XDG_STATE_HOME por padrao. Nunca dentro do mount (o agente editaria a
        # propria allowlist) e nunca em /tmp (tmpfs: some no reboot, e um bind
        # mount apontando para caminho inexistente matou o squid do v1).
        state=Path(home) / ".local" / "state" / "agent-sandbox" / ws,
    )


def _git(*args: str, cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise WorkspaceError(
            f"git {' '.join(args)} falhou em {cwd}: {result.stderr.strip()}")


def prepare_clone(origin: Path, layout: Layout) -> None:
    """Cria o checkout do workspace, se ainda nao existir.

    Clone e nao worktree: uma worktree guarda seus metadados no .git do
    repositorio de ORIGEM, que nao e montado no container, e `git` la dentro
    falharia. Para origem local o git usa hardlinks, entao o clone e rapido e
    barato em disco.

    Idempotente. Um `up` sobre um workspace existente NUNCA reclona: isso
    apagaria commits que o agente ja fez e que ainda nao voltaram para o host.
    """
    origin = Path(origin)
    if not (origin / ".git").exists():
        raise WorkspaceError(f"origem nao e um repositorio git: {origin}")

    layout.mount.mkdir(parents=True, exist_ok=True)
    layout.state.mkdir(parents=True, exist_ok=True)
    layout.state.chmod(0o700)

    if (layout.project_root / ".git").is_dir():
        return
    if layout.project_root.exists():
        raise WorkspaceError(
            f"{layout.project_root} existe e nao e um repositorio git; "
            "remova-o a mao ou use outro workspace")
    _git("clone", str(origin), str(layout.project_root), cwd=layout.mount)


def remove_state(layout: Layout) -> None:
    """Chamado por `down`. NAO toca no mount: la vive o trabalho do agente."""
    shutil.rmtree(layout.state, ignore_errors=True)


def remove_workspace(layout: Layout) -> None:
    """Chamado por `purge`, so apos confirmacao explicita do operador."""
    remove_state(layout)
    shutil.rmtree(layout.mount, ignore_errors=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: PASS — 16 profile tests plus 15 workspace tests.

- [ ] **Step 5: Commit**

```bash
git add cli/asb/workspace.py tests/unit/test_workspace.py
git commit -F - <<'MSG'
✨ place workspaces where host tools reach them: filesystem layout

Establishes workspace identity and on-disk layout. This is the change
that makes agent worktrees visible to host tooling.

### ✅ New features

Each workspace gets ~/asb-agent/<project>/<workspace>/, holding a
self-contained clone of the origin repository. Orca creates its worktree
as a sibling of projectRoot, verified against the runtime record it
wrote for the previous workspace, so the sibling lands inside the
mounted directory and stays reachable from the host. A clone rather than
a worktree, because worktree metadata lives in the origin repository's
.git, which is deliberately not mounted.

### 💡 Architecture improvements

Workspace state — rendered squid.conf, normalized profile, origin path —
lives under ~/.local/state/agent-sandbox/<ws>/, outside the writable
mount. A test asserts this: the allowlist inside the mount would let the
agent edit its own allowlist. It is also kept out of /tmp, which is
tmpfs and whose disappearance across reboot is what killed Squid in v1.

### 🧼 Best practices & validations

Workspace names are deterministic and reproducible from their inputs.
Tests cover trailing-slash normalization, sanitization of Orca's
`uuid::/path` form, and the absence of the doubled-dash artifact that
produced names like hexmed-stack--f05b729e. prepare_clone is idempotent
and never re-clones over an existing checkout, which would discard agent
commits that have not yet been pulled back to the host.

### 🚀 Outcome

Layout and identity are covered by 15 unit tests. Nothing yet talks to
podman; the next task renders the Squid allowlist.
MSG
```

---

## Task 3: Squid allowlist rendering

Turns the base allowlist plus the project's own entries into a `squid.conf`.
Ports `cli/lib/render_squid.py`, which is preserved because its normalization
is not optional: Squid treats a parent and child `dstdomain` in the same ACL as
a **fatal** configuration error.

**Files:**
- Create: `cli/asb/squid.py`
- Modify: `image/squid/allowlist-base.txt` (de-duplicate; add `mise.jdx.dev`)
- Test: `tests/unit/test_squid.py`
- Delete: `cli/lib/render_squid.py`

**Interfaces:**
- Consumes: `Profile` from Task 1 (`profile.allow`, `profile.container_mode`).
- Produces:
  - `normalize_domains(domains: Iterable[str]) -> list[str]`
  - `render(profile: Profile, base: Path, template: Path) -> str`
  - `SquidError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_squid.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'asb.squid'`

- [ ] **Step 3: Write the implementation**

Create `cli/asb/squid.py`:

```python
"""cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf.

A normalizacao NAO e cosmetica. Em ACL dstdomain do Squid, ".dominio.com" ja
casa "dominio.com" e todos os subdominios; declarar os dois no mesmo ACL e
erro FATAL de configuracao ("ERROR: '.github.com' is a subdomain of
'github.com'" seguido de "FATAL: Bungled"). O squid nao sobe, e o sintoma
observado e o sandbox sem egresso.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .profile import Profile

# Necessarios apenas quando o agente roda containers dentro do sandbox: os
# pulls saem pelo proxy. Ficam fora da base para nao abrir registries em
# workspaces que nao os usam.
NESTED_REGISTRIES = (
    "registry-1.docker.io",
    "auth.docker.io",
    "production.cloudflare.docker.com",
    "quay.io",
    "cdn.quay.io",
    "ghcr.io",
)


class SquidError(Exception):
    pass


def read_base(path: Path) -> list[str]:
    domains = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(line)
    return domains


def normalize_domains(domains: Iterable[str]) -> list[str]:
    clean = {d.strip() for d in domains if d.strip()}
    result = []
    for domain in clean:
        redundant = False
        for other in clean:
            if other == domain or not other.startswith("."):
                continue
            parent = other[1:]
            # Comparar por rotulo: "notgithub.com" termina em "github.com"
            # como texto, mas nao e subdominio dele.
            if domain == parent or domain.endswith("." + parent):
                redundant = True
                break
        if not redundant:
            result.append(domain)
    return sorted(result)


def render(profile: Profile, base: Path, template: Path) -> str:
    domains = read_base(base)
    domains.extend(profile.allow)
    if profile.container_mode == "nested":
        domains.extend(NESTED_REGISTRIES)

    ordered = normalize_domains(domains)
    if not ordered:
        raise SquidError(
            "allowlist vazia: o sandbox subiria sem egresso algum e o sintoma "
            "nao apontaria para a causa")
    return Path(template).read_text().replace("__ALLOWLIST__",
                                              " ".join(ordered))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: PASS — 42 tests total.

- [ ] **Step 5: Clean the base allowlist**

`image/squid/allowlist-base.txt` currently declares `antigravity-unleash.goog`
and its comment **twice**, and declares both `antigravity.google` and
`.antigravity.google` (the normalizer prunes the apex, so this is harmless but
misleading). Remove the duplicate block and the redundant apex, then add:

```
# O mise e o caminho declarado para ferramentas de projeto (spec §8); ele
# resolve versoes e baixa binarios daqui. Sem este dominio, um projeto com
# mise.toml falha no arranque do workspace.
mise.jdx.dev
```

Verify nothing was lost:

Run: `python3 -c "import sys; sys.path.insert(0,'cli'); from asb.squid import read_base, normalize_domains; from pathlib import Path; print('\n'.join(normalize_domains(read_base(Path('image/squid/allowlist-base.txt')))))"`
Expected: every domain from the previous list still present, plus `mise.jdx.dev`,
with `antigravity.google` absent (pruned by `.antigravity.google`).

- [ ] **Step 6: Delete the superseded module**

```bash
git rm cli/lib/render_squid.py
```

- [ ] **Step 7: Commit**

```bash
git add cli/asb/squid.py tests/unit/test_squid.py image/squid/allowlist-base.txt
git commit -F - <<'MSG'
♻️ render the Squid allowlist from the typed profile: egress policy

Ports the v1 allowlist renderer onto the Profile dataclass and drops the
JSON intermediate it used to read.

### 💡 Architecture improvements

Domain normalization is preserved and now covered by tests, because it
is not cosmetic: in a Squid dstdomain ACL, ".domain.com" already matches
the apex and every subdomain, and declaring both in one ACL is a fatal
configuration error. Squid then refuses to start and the observed
symptom is a sandbox with no egress at all, which does not point at the
cause. A test also pins that a similar suffix is not mistaken for a
child, so notgithub.com survives alongside .github.com.

Container registries are added to the allowlist only when the profile
sets mode = "nested", since that is the only case where the agent pulls
images through the proxy. Keeping them out of the base avoids opening
registries for workspaces that never use them.

### 🧼 Best practices & validations

An empty allowlist is refused rather than rendered, since the resulting
sandbox would start with no egress and report nothing useful. The base
allowlist loses a duplicated antigravity-unleash.goog block and the
redundant antigravity.google apex, and gains mise.jdx.dev, without which
any project carrying a mise.toml fails to start its workspace.

### 🚀 Outcome

42 unit tests pass. cli/lib/render_squid.py is removed. The three pure
modules are done; the next task builds the container image.
MSG
```

---

## Task 4: CLI entrypoint, podman wrapper and base image

First runnable command. `asb-agent build` produces the base image with the
container user mirroring the host user, which is what makes identical paths
possible (spec D4) without hardcoding this machine into the image (spec §16).

Podman-inside-the-image is deliberately **not** added here — Task 10 owns
nested mode together with its image dependency, so its risk is isolated.

**Files:**
- Create: `cli/asb-agent` (executable)
- Create: `cli/asb/podman.py`
- Modify: `image/Containerfile` (rewrite)
- Modify: `image/entrypoint.sh` (rewrite, much smaller)
- Rename: `cli/asb-agent` (v1 guard) → `cli/asb-guard`
- Test: `tests/test-image.sh`
- Delete: `cli/agent-sandbox`, `cli/lib/profile.py`, `image/Containerfile.net`,
  `image/firewall/apply.sh`, `image/install-config.py`, `profiles/default.toml`,
  `image/asb-agent` (duplicate of the guard)

**Interfaces:**
- Consumes: `load_profile` (Task 1), `workspace_id`/`layout_for` (Task 2),
  `render` (Task 3).
- Produces:
  - `podman.run(*args, check=True, capture=False) -> subprocess.CompletedProcess`
  - `podman.json(*args) -> Any` — runs with `--format json` and parses
  - `podman.exists(kind: str, name: str) -> bool` — `kind` in
    `{"container", "network", "image", "volume"}`
  - image `agent-sandbox:latest` with build args `ASB_USER`, `ASB_HOME`
  - marker file `/etc/agent-sandbox-release`

- [ ] **Step 1: Write the failing test**

Create `tests/test-image.sh`:

```bash
#!/usr/bin/env bash
# tests/test-image.sh — propriedades da imagem base.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

IMG=agent-sandbox:latest
HOST_USER=$(id -un)
HOST_HOME=$HOME

echo "== imagem base =="

# CONTROLE POSITIVO: sem isto, todo assert_fails abaixo passaria de graca
# porque o `podman run` falharia por imagem ausente, nao por politica.
require "a imagem responde" podman run --rm "$IMG" true

in_image() { podman run --rm --entrypoint "" "$IMG" "$@"; }

assert_eq "$HOST_USER" "$(in_image id -un -- 2>/dev/null || in_image sh -c 'id -un')" \
  "o usuario do container espelha o do host"
assert_eq "1000" "$(in_image sh -c 'id -u')" "uid do usuario e 1000"
assert_eq "$HOST_HOME" "$(in_image sh -c 'echo $HOME')" \
  "o home do container e identico ao do host"

for bin in claude codex agy gh git rg jq socat ssh-keygen; do
  assert_eq "0" "$(in_image sh -lc "command -v $bin >/dev/null; echo \$?")" \
    "$bin esta no PATH de um shell de login"
done

# O sandbox E a fronteira; sudo dentro dele so serviria para escapar dela.
assert_eq "1" "$(in_image sh -c 'command -v sudo >/dev/null; echo $?')" \
  "sudo nao existe na imagem"

# Ela protegia subprocessos NO HOST. Aqui nao protege nada, e o Claude Code
# responde a ela forcando o permission mode para default — anulando o
# --dangerously-skip-permissions que o Orca aplica, que e a capacidade que o
# sandbox existe para viabilizar com seguranca.
assert_eq "" "$(in_image sh -lc 'echo ${CLAUDE_CODE_SUBPROCESS_ENV_SCRUB:-}')" \
  "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB nao esta definida"
assert_eq "" "$(podman image inspect "$IMG" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep CLAUDE_CODE_SUBPROCESS_ENV_SCRUB || true)" \
  "e tambem nao esta no Config.Env da imagem"

assert_eq "agent-sandbox" "$(in_image cat /etc/agent-sandbox-release)" \
  "o marcador que o guarda procura esta presente"

# Chaves de host ASSADAS NO BUILD. Geradas em runtime, cada workspace teria a
# sua, e como todos atendem em 127.0.0.1 o ssh do Orca acusaria
# host-key-changed a cada workspace novo.
assert_eq "0" "$(in_image sh -c 'test -f /etc/ssh/ssh_host_ed25519_key; echo $?')" \
  "as host keys vieram do build"

for guard in asb-claude asb-codex asb-agy; do
  assert_eq "0" "$(in_image sh -c "test -x /usr/local/bin/$guard; echo \$?")" \
    "$guard existe na imagem"
done

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-image.sh`
Expected: ABORT at the positive control — the image `agent-sandbox:latest` does
not exist yet. This is the `require` guard doing its job.

- [ ] **Step 3: Write the podman wrapper**

Create `cli/asb/podman.py`:

```python
"""cli/asb/podman.py — invólucro fino sobre o binário podman.

Fino de proposito: sem cache, sem estado, sem reintentos escondidos. Todo o
raciocinio de ciclo de vida vive em lifecycle.py, onde da para ler.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class PodmanError(Exception):
    pass


def require_binary() -> str:
    found = shutil.which("podman")
    if not found:
        raise PodmanError("podman nao encontrado no PATH")
    return found


def run(*args: str, check: bool = True,
        capture: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [require_binary(), *args],
        capture_output=capture, text=True,
        stdout=None if capture else subprocess.DEVNULL)
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise PodmanError(f"podman {' '.join(args)} falhou: {detail}")
    return result


def out(*args: str) -> str:
    result = subprocess.run([require_binary(), *args], capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise PodmanError(
            f"podman {' '.join(args)} falhou: {result.stderr.strip()}")
    return result.stdout.strip()


def json_out(*args: str) -> Any:
    return json.loads(out(*args, "--format", "json"))


_KINDS = {"container": "container", "network": "network",
          "image": "image", "volume": "volume"}


def exists(kind: str, name: str) -> bool:
    if kind not in _KINDS:
        raise PodmanError(f"tipo desconhecido: {kind}")
    return subprocess.run(
        [require_binary(), kind, "exists", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def running(name: str) -> bool:
    return bool(out("ps", "--filter", f"name=^{name}$", "--filter",
                    "status=running", "--quiet"))
```

- [ ] **Step 4: Write the CLI entrypoint**

Create `cli/asb-agent`, mode `0755`:

```python
#!/usr/bin/env python3
"""cli/asb-agent — ponto de entrada do host.

Roda direto do checkout: sem instalacao, sem dependencias, sem passo de build.
Este arquivo faz APENAS parsing e despacho; toda a logica vive em cli/asb/.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asb import install, lifecycle  # noqa: E402
from asb.doctor import doctor  # noqa: E402
from asb.podman import PodmanError  # noqa: E402
from asb.profile import ProfileError  # noqa: E402
from asb.workspace import WorkspaceError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asb-agent",
        description="Sandbox de execucao isolado para agentes de IA.")
    sub = parser.add_subparsers(dest="command", required=True)

    def workspace_command(name: str, help_text: str):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--workspace", required=True)
        return cmd

    up = workspace_command("up", "cria e sobe um workspace")
    up.add_argument("--repo", required=True)

    workspace_command("down", "remove containers e rede; preserva o trabalho")
    workspace_command("suspend", "para os containers do workspace")
    workspace_command("resume", "religa os containers do workspace")
    workspace_command("pull", "traz o branch do workspace para o checkout")

    purge = workspace_command("purge", "remove tambem os arquivos do workspace")
    purge.add_argument("--yes", action="store_true",
                       help="confirma a remocao dos arquivos")

    sub.add_parser("build", help="constroi a imagem base")
    sub.add_parser("login", help="autentica os tres agentes (uma vez)")
    sub.add_parser("doctor", help="diagnostica o ambiente")
    sub.add_parser("list", help="lista os workspaces conhecidos")
    sub.add_parser("install-guards", help="instala asb-claude/codex/agy")
    sub.add_parser("install-broker", help="instala o broker do Docker (sudo)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build":
            return lifecycle.build(ROOT)
        if args.command == "up":
            return lifecycle.up(ROOT, args.workspace, Path(args.repo).resolve())
        if args.command == "down":
            return lifecycle.down(args.workspace)
        if args.command == "suspend":
            return lifecycle.suspend(args.workspace)
        if args.command == "resume":
            return lifecycle.resume(ROOT, args.workspace)
        if args.command == "pull":
            return lifecycle.pull(args.workspace)
        if args.command == "purge":
            return lifecycle.purge(args.workspace, confirmed=args.yes)
        if args.command == "login":
            return lifecycle.login(ROOT)
        if args.command == "list":
            return lifecycle.list_workspaces()
        if args.command == "doctor":
            return doctor(ROOT)
        if args.command == "install-guards":
            return install.guards(ROOT)
        if args.command == "install-broker":
            return install.broker(ROOT)
    except (PodmanError, ProfileError, WorkspaceError) as error:
        print(f"asb-agent: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 2


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
```

Note for the implementer: `lifecycle`, `doctor` and `install` do not exist yet.
In this task, create them as stubs that `raise NotImplementedError` for every
function except `lifecycle.build`, so the entrypoint imports cleanly. Later
tasks fill them in; do not leave a stub unimplemented past Task 14.

- [ ] **Step 5: Rewrite the Containerfile**

Replace `image/Containerfile` entirely:

```dockerfile
# image/Containerfile — imagem base do agente.
#
# ASB_USER e ASB_HOME espelham o usuario do HOST. Sao build args, nunca
# literais: um nome de usuario assado aqui quebraria a imagem no primeiro host
# diferente, e o sintoma seriam caminhos que nao batem (spec §16).
FROM debian:bookworm-slim

ARG ASB_USER
ARG ASB_HOME
ENV DEBIAN_FRONTEND=noninteractive

RUN test -n "$ASB_USER" && test -n "$ASB_HOME" \
    || (echo "ASB_USER e ASB_HOME sao obrigatorios" >&2; exit 1)

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git openssh-server ripgrep jq socat \
      netcat-openbsd python3 build-essential procps less nano bubblewrap \
      gnome-keyring libsecret-tools dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code @openai/codex \
    && npm cache clean --force

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# O usuario espelha o do host: mesmo nome, uid 1000, MESMO home. E o home
# identico que faz a worktree irma do Orca cair num caminho que existe dos
# dois lados.
RUN useradd -m -u 1000 -d "$ASB_HOME" -s /bin/bash "$ASB_USER"

USER $ASB_USER
ENV HOME=$ASB_HOME
RUN curl -fsSL https://mise.run | sh
ENV PATH="$ASB_HOME/.local/bin:$ASB_HOME/.local/share/mise/shims:${PATH}"
# O Antigravity CLI substituiu o Gemini CLI, descontinuado em 2026-06-18 para
# contas Pro/Ultra. E um binario Go unico; nao ha pacote npm.
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
USER root

# HOST KEYS ASSADAS NO BUILD. Geradas em runtime, cada workspace teria a sua, e
# como todos atendem em 127.0.0.1 o ssh do Orca acusaria host-key-changed a
# cada workspace novo.
RUN ssh-keygen -A && mkdir -p /run/sshd

RUN printf '%s\n' \
      'PermitRootLogin no' \
      'PasswordAuthentication no' \
      'PubkeyAuthentication yes' \
      "AuthorizedKeysFile $ASB_HOME/.ssh/authorized_keys" \
      'AcceptEnv HTTPS_PROXY HTTP_PROXY NO_PROXY' \
      > /etc/ssh/sshd_config.d/agent-sandbox.conf

# NAO definir CLAUDE_CODE_SUBPROCESS_ENV_SCRUB aqui, nem em lugar algum. Ela
# protegia subprocessos NO HOST; dentro do container nao protege nada e o
# Claude Code responde a ela forcando o permission mode para default, anulando
# o --dangerously-skip-permissions que o Orca aplica.

# Marcador que o guarda procura para saber que esta DENTRO do sandbox. A
# ausencia dele no host e o que faz o guarda recusar la.
RUN printf 'agent-sandbox\n' > /etc/agent-sandbox-release

# Contexto de build e a RAIZ do repositorio, para que exista uma unica copia
# do guarda. No v1 ele vivia em cli/ e em image/, e duas copias do mesmo
# programa divergem — de forma invisivel ate o agente se comportar diferente
# dentro e fora do sandbox.
COPY cli/asb-guard /usr/local/bin/asb-guard
RUN chmod 0755 /usr/local/bin/asb-guard \
    && for a in claude codex agy; do \
         ln -sf /usr/local/bin/asb-guard "/usr/local/bin/asb-$a"; \
       done

COPY image/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY image/start-keyring.sh /usr/local/bin/start-keyring.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/start-keyring.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

**The guard exists twice in v1** — `cli/asb-agent` (installed on the host) and
`image/asb-agent` (baked into the image) — and two copies of one program are a
maintenance hazard: they drift, and the drift is invisible until an agent
behaves differently inside the sandbox than outside it. Collapse them into one
file and let the build context reach it.

This step must run **before** Step 4 creates the new `cli/asb-agent`:

```bash
git mv cli/asb-agent cli/asb-guard
git rm image/asb-agent
```

The Containerfile below therefore uses the **repository root** as its build
context and copies `cli/asb-guard` directly. Task 12 adapts the guard's
behaviour; this step only moves it.

- [ ] **Step 6: Rewrite the entrypoint**

Replace `image/entrypoint.sh` entirely. It loses the firewall probe, the
provisioning token and the sshd gate — none of which have anything left to
guard, because isolation is now the network definition and configuration
arrives as a read-only mount:

```bash
#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd.
#
# Muito menor que o do v1 de proposito. Sumiram: a sonda de egresso direto (a
# topologia da rede e que isola agora, e ela nao pode "nao ter subido"), o
# token de provisionamento e o portao do sshd (a configuracao chega como mount
# read-only, entao nao ha janela de TOCTOU a fechar).
set -euo pipefail

ASB_USER=$(id -un 1000)
ASB_HOME=$(getent passwd 1000 | cut -d: -f6)

# O OpenSSH descarta o ambiente do processo pai ao criar a sessao do usuario.
# /etc/environment e lido pelo PAM (inclusive em `ssh host 'cmd'`, que NAO e
# shell de login); /etc/profile.d cobre os shells de login.
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|PATH)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<ENV_EOF
# Sem default fixo: o container de login roda FORA da rede interna e nao tem
# proxy algum. Um default apontando para um proxy inexistente quebraria os
# logins. Quem define o proxy e quem cria o container, via -e.
[ -n "\${HTTPS_PROXY:-}" ] && export HTTPS_PROXY="\$HTTPS_PROXY"
[ -n "\${HTTP_PROXY:-}" ] && export HTTP_PROXY="\$HTTP_PROXY"
[ -n "\${NO_PROXY:-}" ] && export NO_PROXY="\$NO_PROXY"
export PATH="$ASB_HOME/.local/bin:$ASB_HOME/.local/share/mise/shims:\${PATH}"
ENV_EOF

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o "$ASB_USER" -g "$ASB_USER" "$ASB_HOME/.ssh"
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > "$ASB_HOME/.ssh/authorized_keys"
  chown "$ASB_USER:$ASB_USER" "$ASB_HOME/.ssh/authorized_keys"
  chmod 0600 "$ASB_HOME/.ssh/authorized_keys"
fi

# O agy guarda credencial no Secret Service, nao em arquivo. A passphrase chega
# em RUNTIME e nunca e assada na imagem, entao o volume de credenciais sozinho
# carrega um keyring cifrado inutil.
if [ -n "${ASB_KEYRING_PASS:-}" ]; then
  printf '%s' "$ASB_KEYRING_PASS" > /run/asb-keyring-pass
  chown "$ASB_USER:$ASB_USER" /run/asb-keyring-pass
  chmod 0600 /run/asb-keyring-pass
  unset ASB_KEYRING_PASS
  su "$ASB_USER" -c /usr/local/bin/start-keyring.sh \
    > /etc/profile.d/agent-keyring.sh 2>/dev/null || true
  rm -f /run/asb-keyring-pass
  chmod 0644 /etc/profile.d/agent-keyring.sh
  # `ssh host 'cmd'` nao le /etc/profile.d. O formato de /etc/environment nao
  # aceita o prefixo `export`, entao ele e removido.
  sed 's/^export //' /etc/profile.d/agent-keyring.sh \
    | tr -d "'\"" >> /etc/environment || true
fi

[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
```

- [ ] **Step 7: Implement `lifecycle.build`**

Create `cli/asb/lifecycle.py` with the build function and stubs:

```python
"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from . import podman

IMAGE = "agent-sandbox:latest"


def build(root: Path) -> int:
    """Constroi a imagem base espelhando o usuario do host.

    id -un e $HOME entram como build args. Nunca literais: um nome assado
    quebraria a imagem no primeiro host diferente (spec §16).
    """
    user = getpass.getuser()
    home = os.path.expanduser("~")
    print(f"construindo {IMAGE} para {user} ({home})")
    # Contexto de build e a raiz do repo: o Containerfile copia cli/asb-guard
    # e image/*, e assim o guarda existe uma vez so.
    podman.run("build", "--build-arg", f"ASB_USER={user}",
               "--build-arg", f"ASB_HOME={home}",
               "-t", IMAGE, "-f", str(root / "image" / "Containerfile"),
               str(root))
    return 0
```

- [ ] **Step 8: Build and run the test**

Run: `./cli/asb-agent build && bash tests/test-image.sh`
Expected: PASS on every assertion. If a login shell cannot find `agy`, check
that the `ENV PATH` line survived the `USER root` switch — that exact omission
is what once sent Antigravity's credential to a plaintext file instead of the
keyring.

- [ ] **Step 9: Delete the superseded v1 entrypoint and helpers**

```bash
git rm cli/agent-sandbox cli/lib/profile.py image/Containerfile.net \
       image/firewall/apply.sh image/install-config.py profiles/default.toml
```

`cli/lib/pod.sh`, `auth.sh`, `attach.sh` and `doctor.sh` stay until the tasks
that replace them (Tasks 5, 8, 9, 13) — deleting them now would leave the tree
untestable.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✨ mirror the host user in the base image: sandbox runtime

Adds the CLI entrypoint, a thin podman wrapper and the rebuilt base
image. First runnable command: asb-agent build.

### ✅ New features

The container user mirrors the host user — same name, uid 1000, same
home — supplied as ASB_USER and ASB_HOME build arguments derived from
id -un and $HOME. Identical paths on both sides are what let Orca's
sibling worktree land somewhere that exists on the host, and passing
them as build arguments keeps the image from carrying this machine's
username, which would break on the first different host.

### 💡 Architecture improvements

The entrypoint loses the direct-egress probe, the provisioning token and
the sshd gate. None of them have anything left to guard: isolation is
now the network definition, which cannot fail to be applied, and
configuration arrives as a read-only mount, so there is no TOCTOU window
to close. What remains is key installation, keyring unlock and sshd.

### 🔐 Security & Access Control

The image ships no sudo, bakes SSH host keys at build time so ephemeral
workspaces on 127.0.0.1 do not trigger host-key-changed, and carries the
release marker the guard uses to recognise the inside of the sandbox.
Tests assert that CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is absent from both
the environment and the image config, since setting it silently forces
Claude's permission mode back to default.

### 🚀 Outcome

asb-agent build produces agent-sandbox:latest and tests/test-image.sh
passes. Podman-in-the-image is deliberately deferred to the nested-mode
task so its risk stays isolated. The v1 entrypoint, firewall image and
config installer are removed.
MSG
```

---

## Task 5: Network topology, `up` and `down`

The core of the rebuild. This task replaces the pod, the init container, the
nftables ruleset and every ordering rule that depended on them with two podman
networks.

**Files:**
- Create: `image/Containerfile.proxy`
- Modify: `cli/asb/lifecycle.py` (add `up`, `down`, `emit`, `build_proxy`)
- Test: `tests/test-network.sh`
- Delete: `cli/lib/pod.sh` (its ordering logic has no successor by design)

**Interfaces:**
- Consumes: `load_profile`, `layout_for`, `prepare_clone`, `render`, `podman.*`.
- Produces:
  - networks `asb-<ws>` (internal) and `asb-<ws>-out` (external)
  - containers `asb-<ws>-agent`, `asb-<ws>-proxy`
  - image `agent-sandbox-proxy:latest`
  - `up(root, ws, repo) -> int` printing one JSON line:
    `{"workspace": str, "port": int, "user": str, "project_root": str}`
  - `down(ws) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test-network.sh`:

```bash
#!/usr/bin/env bash
# tests/test-network.sh — a fronteira de rede do sandbox.
#
# Toda assercao de bloqueio aqui e precedida por um controle positivo. Sem
# isso, um container que nao subiu faria "esta bloqueado" passar de graca — e
# um falso verde numa assercao de seguranca e pior que uma falha.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-net-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

echo "== topologia de rede =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }

AGENT="asb-${WS}-agent"
PROXY="asb-${WS}-proxy"

# ---- CONTROLES POSITIVOS ----
require "o container do agente responde" podman exec "$AGENT" true
require "o container do proxy responde"  podman exec "$PROXY" true
require "o proxy tem egresso real" \
  podman exec "$PROXY" sh -c 'timeout 5 nc -z 1.1.1.1 443'

# ---- O AGENTE NAO SAI ----
assert_fails "o agente nao alcanca a internet por IP" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'

assert_eq "" "$(podman exec "$AGENT" sh -c 'ip -4 route show default' 2>/dev/null)" \
  "o agente nao tem rota default"

# Casar a FORMA de uma resposta real, nunca "qualquer saida": ferramentas de
# DNS escrevem erros em stdout, e "tem texto" reportaria um vazamento
# inexistente.
assert_eq "" "$(podman exec "$AGENT" sh -c \
  'getent ahostsv4 api.anthropic.com 2>/dev/null | awk "{print \$1}" | head -1')" \
  "o agente nao resolve DNS externo"

# ---- O AGENTE SAI PELO PROXY ----
assert_contains "200" "$(podman exec "$AGENT" sh -c '
  printf "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n" \
    | timeout 10 nc asb-'"$WS"'-proxy 3128 | head -n 1')" \
  "CONNECT para dominio permitido responde 200"

assert_fails "CONNECT para dominio NAO permitido e recusado" \
  podman exec "$AGENT" sh -c '
    printf "CONNECT exfil.example.net:443 HTTP/1.1\r\nHost: exfil.example.net:443\r\n\r\n" \
      | timeout 10 nc asb-'"$WS"'-proxy 3128 | head -n 1 | grep -q " 200 "'

# ---- SSH PUBLICADO E UTIL ----
PORT=$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
assert_eq "0" "$(timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT" 2>/dev/null; echo $?)" \
  "a porta SSH publicada aceita conexao no host"

# ---- O MOUNT E IDENTICO E GRAVAVEL ----
MOUNT="$HOME/asb-agent/$(basename "$REPO")/$WS"
assert_eq "0" "$(podman exec "$AGENT" sh -c "test -d '$MOUNT'; echo \$?")" \
  "o caminho do mount e identico dentro do container"
assert_eq "1000" "$(podman exec "$AGENT" sh -c "stat -c %u '$MOUNT'")" \
  "o mount pertence ao uid 1000 (sem keep-id o agente nao escreve nele)"
podman exec "$AGENT" sh -c "touch '$MOUNT/escrito-pelo-agente'" 2>/dev/null
assert_eq "0" "$(test -f "$MOUNT/escrito-pelo-agente"; echo $?)" \
  "o que o agente escreve aparece no host"

# ---- O AGENTE NAO ALCANCA O ESTADO NEM O RESTO DO DISCO ----
STATE="$HOME/.local/state/agent-sandbox/$WS"
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$STATE/squid.conf'; echo \$?")" \
  "o agente nao enxerga o squid.conf (nao pode editar a propria allowlist)"
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$HOME/Data'; echo \$?")" \
  "o agente nao enxerga os outros projetos do host"

# ---- SEM CAPACIDADE DE REDE ----
assert_fails "o agente nao tem CAP_NET_ADMIN" \
  podman exec "$AGENT" sh -c 'ip link add dummy0 type dummy'

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-network.sh`
Expected: ABORT — `up` does not exist yet.

- [ ] **Step 3: Write the proxy image**

Create `image/Containerfile.proxy`:

```dockerfile
# image/Containerfile.proxy — o unico container do workspace com egresso.
#
# Sem nftables: no v2 o isolamento e a topologia da rede, e nao um ruleset que
# precisa ser reaplicado a cada partida. socat fica para o encaminhador de
# portas do host (Task 9); ele roda em container proprio, nao aqui.
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates squid netcat-openbsd iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/*
# Config de partida so para o `podman build` ter algo valido; em uso real o
# CLI gera o arquivo por workspace e o monta read-only por cima.
COPY image/squid/squid.conf.tmpl /etc/squid/squid.conf.tmpl
RUN sed 's/__ALLOWLIST__/.example.com/' /etc/squid/squid.conf.tmpl \
      > /etc/squid/squid.conf \
    && chown -R 900:900 /var/spool/squid /var/log/squid 2>/dev/null || true
```

- [ ] **Step 4: Implement `up`, `down` and `emit`**

Add to `cli/asb/lifecycle.py`:

```python
IMAGE = "agent-sandbox:latest"
PROXY_IMAGE = "agent-sandbox-proxy:latest"
PROXY_PORT = 3128
CONFIG = Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
SSH_KEY = CONFIG / "id_ed25519"


def names(ws: str) -> dict[str, str]:
    """Nomes derivados do workspace. Um lugar so: no v1 a derivacao duplicada
    entre create e destroy divergiu e vazou um pod a cada divergencia."""
    return {
        "net": f"asb-{ws}",
        "out": f"asb-{ws}-out",
        "agent": f"asb-{ws}-agent",
        "proxy": f"asb-{ws}-proxy",
    }


def ensure_ssh_key() -> Path:
    if SSH_KEY.exists():
        return SSH_KEY
    CONFIG.mkdir(parents=True, exist_ok=True)
    CONFIG.chmod(0o700)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(SSH_KEY),
                    "-C", "agent-sandbox"], check=True,
                   stdout=subprocess.DEVNULL)
    return SSH_KEY


def build_proxy(root: Path) -> None:
    if podman.exists("image", PROXY_IMAGE):
        return
    podman.run("build", "-t", PROXY_IMAGE,
               "-f", str(root / "image" / "Containerfile.proxy"), str(root))


def up(root: Path, ws: str, repo: Path) -> int:
    """Cria o workspace. Ou completa, ou nao deixa nada para tras.

    O rollback nao e zelo: um `up` que falha no meio e depois e repetido bate
    em "workspace ja existe" por causa dos proprios restos, e o operador fica
    preso sem entender por que.
    """
    try:
        return _up(root, ws, repo)
    except BaseException:
        # NAO remove ~/asb-agent/<proj>/<ws>: um `up` repetido sobre um
        # workspace existente nao pode apagar commits do agente.
        _sweep_containers(ws)
        for network in (names(ws)["net"], names(ws)["out"]):
            if podman.exists("network", network):
                podman.run("network", "rm", "-f", network, check=False)
        raise


def _sweep_containers(ws: str) -> None:
    """Remove todo container do workspace pelo PREFIXO, nunca por lista: um
    tipo de container acrescentado depois seria esquecido e vazaria."""
    for container in podman.out(
            "ps", "-a", "--filter", f"name=^asb-{ws}-",
            "--format", "{{.Names}}").splitlines():
        if container.strip():
            podman.run("rm", "-f", container.strip(), check=False)


def _up(root: Path, ws: str, repo: Path) -> int:
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    n = names(ws)
    if podman.exists("container", n["agent"]):
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    build_proxy(root)
    home = Path(os.path.expanduser("~"))
    profile = load_profile(repo)
    layout = layout_for(repo, ws, home)
    prepare_clone(repo, layout)

    conf = layout.state / "squid.conf"
    conf.write_text(render(profile,
                           root / "image" / "squid" / "allowlist-base.txt",
                           root / "image" / "squid" / "squid.conf.tmpl"))
    # o squid roda como uid 900 e precisa LER o arquivo montado
    conf.chmod(0o644)
    (layout.state / "origin").write_text(str(repo))

    # A rede interna nao tem rota default nem DNS externo, e o podman a
    # reconstroi em TODA partida do container. E por isso que nao existe mais
    # ordem de subida a respeitar: nao ha regra que possa faltar.
    if not podman.exists("network", n["net"]):
        podman.run("network", "create", "--internal", n["net"])
    if not podman.exists("network", n["out"]):
        podman.run("network", "create", n["out"])

    # O proxy tem perna nas duas redes: e o unico caminho para fora.
    podman.run(
        "run", "-d", "--name", n["proxy"], "--restart", "unless-stopped",
        "--network", f"{n['net']},{n['out']}", "--user", "900",
        "-v", f"{conf}:/etc/squid/squid.conf:ro,Z",
        PROXY_IMAGE, "squid", "-N", "-f", "/etc/squid/squid.conf")

    key = ensure_ssh_key()
    agent_args = [
        "run", "-d", "--name", n["agent"], "--restart", "unless-stopped",
        "--network", n["net"],
        "-p", "127.0.0.1::22",
        # Sem keep-id o uid 1000 do host mapeia para 0 aqui dentro, o
        # repositorio montado aparece como root e o agente nao consegue
        # escrever no proprio workspace.
        "--userns", "keep-id:uid=1000,gid=1000",
        "-e", f"ORCA_SSH_PUBLIC_KEY={key.with_suffix('.pub').read_text().strip()}",
        "-e", f"HTTPS_PROXY=http://{n['proxy']}:{PROXY_PORT}",
        "-e", f"HTTP_PROXY=http://{n['proxy']}:{PROXY_PORT}",
        "-e", "NO_PROXY=127.0.0.1,localhost",
        "-v", f"{layout.mount}:{layout.mount}:Z",
        IMAGE,
    ]
    podman.run(*agent_args)
    return emit(ws, layout)


def emit(ws: str, layout: Layout) -> int:
    """A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca
    inventada: o Orca guarda a que o create devolveu e disca nela para sempre."""
    n = names(ws)
    mapping = podman.out("port", n["agent"], "22")
    port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
    if not port:
        raise podman.PodmanError("nao foi possivel determinar a porta SSH")
    print(json.dumps({"workspace": ws, "port": int(port), "user":
                      getpass.getuser(),
                      "project_root": str(layout.project_root)}))
    return 0


def down(ws: str) -> int:
    """Remove containers e redes. NAO remove ~/asb-agent/<proj>/<ws>: ali vive
    o trabalho do agente, e apagar isso por engano seria irreversivel."""
    n = names(ws)
    home = Path(os.path.expanduser("~"))
    for container in (n["agent"], n["proxy"]):
        if podman.exists("container", container):
            podman.run("rm", "-f", container, check=False)
    for network in (n["net"], n["out"]):
        if podman.exists("network", network):
            podman.run("network", "rm", "-f", network, check=False)
    origin = _origin_of(ws, home)
    if origin is not None:
        remove_state(layout_for(origin, ws, home))
    return 0


def _origin_of(ws: str, home: Path) -> Path | None:
    """Le o caminho de origem gravado no estado. `down` precisa dele para achar
    o layout, e um workspace sem estado nao e erro: nao ha o que limpar."""
    marker = home / ".local" / "state" / "agent-sandbox" / ws / "origin"
    return Path(marker.read_text().strip()) if marker.is_file() else None
```

Add the imports this needs at the top of `lifecycle.py`:

```python
import getpass
import json
import os
import subprocess
from pathlib import Path

from . import podman
from .profile import Profile, load_profile
from .squid import render
from .workspace import Layout, layout_for, prepare_clone, remove_state
```

> **Already verified on this host** (2026-09-04, podman 6.1.0). The exact
> combination this task depends on — `--userns keep-id:uid=1000,gid=1000` plus
> `--network <internal>` plus `-p 127.0.0.1::22` plus an identical-path bind
> mount — was run directly and produced: uid 1000 inside, mount owned by 1000
> and writable with the file appearing on the host, port published on
> 127.0.0.1, **no default route, egress blocked, no CAP_NET_ADMIN**. The v1
> restriction that `--userns` could only go on `podman pod create` disappears
> with the pod.

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tests/test-network.sh`
Expected: PASS on every assertion, with the three positive controls reported
first. If the CONNECT assertion fails while the positive controls pass, read
the Squid log: `podman logs asb-<ws>-proxy`.

- [ ] **Step 6: Delete the v1 lifecycle**

```bash
git rm cli/lib/pod.sh
```

Its ordered-resume logic has no successor **by design**: there is no longer an
order that must hold for the sandbox to be safe.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✨ isolate the agent with network topology: sandbox boundary

Replaces the pod, the CAP_NET_ADMIN init container and the nftables
ruleset with two podman networks per workspace.

### ✅ New features

up creates an internal network carrying the agent and an external
network carrying only the proxy, which is dual-homed and runs Squid
against the rendered allowlist. The agent reaches the proxy by container
name, publishes SSH on 127.0.0.1 with a kernel-assigned port, and mounts
its workspace at a path identical to the host's. down removes containers
and networks but deliberately leaves the workspace directory, since it
holds agent work that has not necessarily been pulled back yet.

### 💡 Architecture improvements

An internal network has no default route and no external DNS, and podman
reconstructs it on every container start. The v1 invariant — reapply and
prove the firewall before any user container, on every one of four
lifecycle paths — therefore has nothing left to protect and is deleted
along with cli/lib/pod.sh. There is no ordering left that the sandbox's
safety depends on.

### 🔐 Security & Access Control

Tests assert the boundary from both sides: the agent has no default
route, resolves no external DNS, cannot open a socket to an address
literal, and cannot create a network interface; while positive controls
prove the containers are actually up first, so none of those assertions
can pass by accident. A domain outside the allowlist is refused by the
proxy. The agent cannot see the rendered squid.conf, so it cannot edit
its own allowlist, and cannot see the rest of the host's projects.

### 🚀 Outcome

up and down work end to end and the network suite passes. Resume,
restart and boot behaviour are proven in the next task.
MSG
```

---

## Task 6: Suspend, resume, restart and boot

Proves the property the whole redesign rests on: the boundary survives a stop
and a reboot **without anything reapplying it**. Also closes the one failure
mode the new architecture could still produce (spec §14): the agent starting
before the proxy and caching a stale address.

**Files:**
- Modify: `cli/asb/lifecycle.py` (add `suspend`, `resume`, `list_workspaces`)
- Create: `cli/asb/install.py` (add `podman_restart`)
- Test: `tests/test-lifecycle.sh`

**Interfaces:**
- Consumes: `names`, `emit`, `_origin_of`, `layout_for` (Task 5).
- Produces:
  - `suspend(ws) -> int`, `resume(root, ws) -> int`,
    `list_workspaces() -> int`
  - `install.podman_restart() -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test-lifecycle.sh`:

```bash
#!/usr/bin/env bash
# tests/test-lifecycle.sh — a fronteira sobrevive a parada e a religada.
#
# Este e o teste que o v1 nao tinha. Nele o sandbox voltava do reboot com o
# ruleset vazio e egresso direto liberado, e o unico sintoma visivel era o
# squid morto.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-life-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
PROXY="asb-${WS}-proxy"

connect_ok() {
  podman exec "$AGENT" sh -c '
    printf "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n" \
      | timeout 10 nc '"$PROXY"' 3128 | head -n 1' 2>/dev/null | grep -q " 200 "
}

echo "== ciclo de vida =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }
PORT_ANTES=$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
IP_ANTES=$(podman inspect "$PROXY" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')

require "o agente responde antes do ciclo" podman exec "$AGENT" true
require "CONNECT funciona antes do ciclo" connect_ok

echo "-- suspend / resume --"
"$ROOT/cli/asb-agent" suspend --workspace "$WS" >/dev/null
assert_eq "" "$(podman ps --filter "name=^${AGENT}$" --filter status=running -q)" \
  "suspend realmente parou o agente"

OUT2=$("$ROOT/cli/asb-agent" resume --workspace "$WS") || {
  echo "  ABORTADO: resume falhou"; exit 1; }
PORT_DEPOIS=$(printf '%s' "$OUT2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')

require "o agente responde apos o resume" podman exec "$AGENT" true

# A porta e resolvida na CRIACAO e gravada no spec do container. O Orca guarda
# a que o create devolveu e disca nela para sempre — inclusive apos reboot.
assert_eq "$PORT_ANTES" "$PORT_DEPOIS" "a porta SSH sobrevive ao ciclo"

# ---- A FRONTEIRA CONTINUA DE PE, SEM NADA TER REAPLICADO ----
assert_fails "o agente continua sem alcancar a internet apos o resume" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'
assert_eq "" "$(podman exec "$AGENT" sh -c 'ip -4 route show default' 2>/dev/null)" \
  "o agente continua sem rota default apos o resume"

echo "-- o agente sobe ANTES do proxy (ordem do boot) --"
# podman-restart.service nao ordena nada, e o IP do proxy MUDA entre partidas.
# Se algo cachear o endereco antigo, o sintoma e "internet quebrada apos
# reboot" — identico ao bug do v1 que este redesenho elimina.
podman stop -t 2 "$AGENT" "$PROXY" >/dev/null 2>&1
podman start "$AGENT" >/dev/null
require "o agente sobe sozinho, sem o proxy" podman exec "$AGENT" true
assert_fails "sem o proxy no ar, nao ha egresso (fail-closed por topologia)" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'

podman start "$PROXY" >/dev/null
IP_DEPOIS=$(podman inspect "$PROXY" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
assert_eq "0" "$(wait_for 20 connect_ok; echo $?)" \
  "o agente reconecta ao proxy pelo NOME apos ele subir depois"
echo "  (ip do proxy antes=$IP_ANTES depois=$IP_DEPOIS)"

echo "-- list --"
assert_contains "$WS" "$("$ROOT/cli/asb-agent" list)" "list mostra o workspace"

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-lifecycle.sh`
Expected: FAIL — `asb-agent: invalid choice: 'suspend'` is not yet dispatched
to an implementation.

- [ ] **Step 3: Implement suspend, resume and list**

Add to `cli/asb/lifecycle.py`:

```python
def _require_workspace(ws: str) -> tuple[dict[str, str], Path, Path]:
    n = names(ws)
    if not podman.exists("container", n["agent"]):
        raise podman.PodmanError(f"workspace inexistente: {ws} (use 'up')")
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(
            f"estado ausente para {ws}; recrie o workspace com 'up'")
    return n, home, origin


def suspend(ws: str) -> int:
    n, _, _ = _require_workspace(ws)
    for container in (n["agent"], n["proxy"]):
        if podman.exists("container", container):
            podman.run("stop", "-t", "5", container, check=False)
    return 0


def resume(root: Path, ws: str) -> int:
    """Religa o workspace.

    E `podman start`, e so. Nao ha ordem a respeitar: a rede interna nao pode
    "nao ter subido", entao o agente nunca ganha egresso indevido por partir
    primeiro. O proxy sobe antes por educacao — para o agente nao passar alguns
    segundos sem saida — nao por seguranca.
    """
    n, home, origin = _require_workspace(ws)
    for container in (n["proxy"], n["agent"]):
        if podman.exists("container", container):
            podman.run("start", container, check=False)
    return emit(ws, layout_for(origin, ws, home))


def list_workspaces() -> int:
    home = Path(os.path.expanduser("~"))
    root = home / ".local" / "state" / "agent-sandbox"
    found = False
    for state in sorted(root.glob("*/origin")) if root.is_dir() else []:
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            status = "sem container"
        else:
            status = "rodando" if podman.running(agent) else "parado"
        print(f"{ws}\t{status}\t{state.read_text().strip()}")
        found = True
    if not found:
        print("nenhum workspace", file=sys.stderr)
    return 0
```

Add `import sys` to the imports at the top of `lifecycle.py`.

- [ ] **Step 4: Implement boot restore**

Create `cli/asb/install.py`:

```python
"""cli/asb/install.py — o que o sandbox instala no host.

Regra da §16: tudo aqui e idempotente, reexecutavel, e NAO grava o caminho
absoluto deste checkout em arquivo de sistema algum. No v1 o ExecStart da
unidade systemd tinha o caminho assado, e mover a pasta quebrava a restauracao
no boot em silencio.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def podman_restart() -> int:
    """Habilita a unidade que o proprio podman ja instala.

    `podman start --all --filter should-start-on-boot=true`, puxada por
    default.target e ordenada apos network-online.target. Substitui inteiros o
    restore-all do v1, a espera por rota/DNS do host, a unidade customizada e o
    codigo de saida 2 para pods legados — e, por nao ser nossa, nao carrega
    caminho nenhum deste checkout.

    Sem linger de proposito: o Orca so roda apos o login, entao uma unidade que
    parte no login e cedo o bastante.
    """
    unit = Path("/usr/lib/systemd/user/podman-restart.service")
    if not unit.is_file():
        print("podman-restart.service nao encontrado; sem restauracao "
              "automatica no boot. Use 'asb-agent resume' apos religar.",
              file=sys.stderr)
        return 1
    subprocess.run(["systemctl", "--user", "enable", "podman-restart.service"],
                   check=True)
    print("restauracao no boot habilitada (podman-restart.service)",
          file=sys.stderr)
    return 0
```

Call it from `up` after the containers are created, so the operator never has to
remember it:

```python
    # Idempotente e barato; chamar aqui evita que o operador precise lembrar.
    from . import install
    install.podman_restart()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tests/test-lifecycle.sh`
Expected: PASS. The proxy's IP printed before and after should **differ** while
the CONNECT assertion still passes — that is the proof that name resolution,
not a cached address, is what carries the agent to the proxy.

- [ ] **Step 6: Verify the real reboot path once, by hand**

This cannot be asserted in the suite. Do it once and record the result in the
commit body:

```bash
./cli/asb-agent up --workspace reboot-check --repo /path/to/a/repo
systemctl --user is-enabled podman-restart.service   # deve dizer: enabled
# reinicie a maquina
podman ps --filter name=asb-reboot-check    # os dois containers rodando
podman exec asb-reboot-check-agent sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"' \
  && echo "VAZOU" || echo "bloqueado"
podman port asb-reboot-check-agent 22       # mesma porta de antes
./cli/asb-agent down --workspace reboot-check
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✅ prove the boundary survives restart: lifecycle

Adds suspend, resume and list, and the test the v1 never had.

### ✅ New features

resume is podman start and nothing else. There is no order to respect,
because the internal network cannot fail to come up, so an agent that
starts first never gains egress it should not have. The proxy is started
first only so the agent does not spend a few seconds without a way out —
a courtesy, not a safety property. Boot restore is delegated to podman's
own podman-restart.service, which carries no path from this checkout and
replaces restore-all, the host route and DNS wait, the custom unit and
the legacy-pod exit code.

### 🧼 Best practices & validations

The suite stops the agent and the proxy, starts the agent alone, and
asserts it still has no egress; then starts the proxy and asserts the
agent reconnects. That case matters because podman-restart imposes no
ordering and the proxy's address changes between starts, so anything
caching the old address would present as "internet broken after reboot"
— indistinguishable from the v1 bug this rebuild removes. The test
prints both addresses to show they differ while CONNECT still works.

The published SSH port is asserted to survive the cycle, since Orca
dials the port the create returned and never asks again.

### 🚀 Outcome

Suspend, resume, restart and boot are covered. The real reboot path was
exercised once by hand and behaved as the test predicts.
MSG
```

---

## Task 7: Host configuration staging

Closes the operator's problem #8 — skills, hooks and MCPs took more than three
attempts to port. Ports `cli/lib/provision.py`, keeping its deny list and
symlink handling, and drops the root installer, the per-start token and the
sshd gate.

**Design note.** The staging tree is mounted **read-only** and the entrypoint
copies from it into the home at start. Not a direct mount onto
`~/.claude/settings.json`, because the agents write to some of those files
during a session and a read-only mount would break them. Not `podman cp` from
the host either, because that is what needed the root installer and the token.
The source is a mount the agent cannot write, so there is no TOCTOU window;
changes the agent makes during a session stay disposable, exactly as the spec
requires.

**Files:**
- Create: `cli/asb/staging.py`
- Modify: `profiles/provision.toml` (destinations become `$HOME`-relative)
- Modify: `image/entrypoint.sh` (materialize from the read-only mount)
- Modify: `cli/asb/lifecycle.py` (build staging in `up`, mount it)
- Test: `tests/unit/test_staging.py`, `tests/test-provision.sh`
- Delete: `cli/lib/provision.py`

**Interfaces:**
- Consumes: `Layout.state` (Task 2).
- Produces:
  - `build_staging(manifest: Path, stage: Path, home: Path) -> int` — writes
    the payload plus `manifest.tsv` (`relative-source<TAB>absolute-dest`) into
    `stage`, returning the number of entries staged
  - `StagingError(Exception)`
  - container mount `<state>/staging:/run/asb-config:ro`

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_staging.py`:

```python
"""Testes de cli/asb/staging.py — o que sai do host para o sandbox."""
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s tests/unit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'asb.staging'`

- [ ] **Step 3: Write the implementation**

Create `cli/asb/staging.py`. Start from `cli/lib/provision.py` and apply four
changes: destinations resolve against `$HOME` instead of the literal
`/home/agent`; the output is a staging tree plus `manifest.tsv` rather than a
copy plan; the `antigravity-hooks` filter is deleted; a `codex-config` filter
is added.

```python
"""cli/asb/staging.py — prepara a configuracao do host para o sandbox.

A allowlist e EXPLICITA de proposito. ~/.claude contem .credentials.json e
~/.codex contem auth.json: declarar o diretorio inteiro entregaria a credencial
do host ao sandbox, que e exatamente o que o volume de credenciais existe para
evitar.

Saida: uma arvore em `stage` mais um manifest.tsv com linhas
`origem-relativa<TAB>destino-absoluto`, que o entrypoint materializa a partir
de um mount read-only.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

# Nomes que nunca entram no sandbox, nem declarados nem escondidos dentro de um
# diretorio declarado.
DENY = {
    ".credentials.json", "auth.json", "history.jsonl", ".netrc",
    "sessions", "projects", "security", "ide", "conversations",
    "knowledge", "brain", ".ssh", "id_ed25519", "keyring.pass",
}


class StagingError(Exception):
    pass


def _allowed_symlink_roots(home: Path) -> tuple[Path, ...]:
    return (home / ".agents" / "skills",
            Path("/usr/share/omarchy/default/agents/skills"))


def _allowed_destination_roots(home: Path) -> tuple[Path, ...]:
    # Espelham o home do HOST (spec D4). Nunca /home/agent literal.
    return (home / ".claude", home / ".codex", home / ".gemini")


def denied(path: Path) -> str | None:
    for part in path.parts:
        if part in DENY:
            return part
    return None


def scan(root: Path, home: Path) -> str | None:
    """Procura caminho negado dentro de um diretorio declarado.

    Verifica o nome E o alvo resolvido de cada entrada. Sem resolver, um
    symlink chamado `inocente.json` apontando para ~/.claude/.credentials.json
    passaria: o nome nao e negado.
    """
    source_root = root.resolve()
    allowed = tuple(p.resolve() for p in _allowed_symlink_roots(home)
                    if p.exists())
    seen: set[Path] = set()

    def within(path: Path, parent: Path) -> bool:
        return path == parent or path.is_relative_to(parent)

    def trusted(target: Path) -> bool:
        return within(target, source_root) or any(
            within(target, a) for a in allowed)

    def visit(path: Path, *, declared_root: bool = False) -> str | None:
        if (bad := denied(Path(path.name))) is not None:
            return f"{path} ({bad})"
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError):
                return None
            if (bad := denied(target)) is not None:
                return f"{path} -> {target} ({bad})"
            ok = (any(within(target, a) for a in allowed) if declared_root
                  else trusted(target))
            if not ok:
                return f"{path} -> {target} (fora das raizes permitidas)"
            return visit(target)
        if path.is_file():
            return denied(path.resolve())
        if not path.is_dir():
            return None
        resolved = path.resolve()
        if resolved in seen:
            return None
        seen.add(resolved)
        try:
            for child in path.iterdir():
                if (bad := visit(child)) is not None:
                    return bad
        except OSError as error:
            return f"{path} nao pode ser inspecionado ({error})"
        return None

    return visit(root, declared_root=root.is_symlink())


def _key(src: Path, name: str) -> str:
    """Chave derivada da ORIGEM: ~/.claude/plugins e ~/.codex/plugins tem o
    mesmo basename e colidiriam, com o segundo sobrescrevendo o primeiro."""
    return f"{hashlib.sha256(str(src).encode()).hexdigest()[:12]}-{name}"


def materialize(src: Path, stage: Path) -> str:
    """Copia um diretorio para o staging com os symlinks RESOLVIDOS.

    As skills do host apontam para fora do home (/usr/share/omarchy/...,
    ~/.agents/skills/...); sem resolver elas chegam como links quebrados.
    Links quebrados na origem sao ignorados em vez de abortar.
    """
    name = _key(src, src.name)
    dest = stage / name
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(directory, names):
        return [n for n in names
                if (Path(directory) / n).is_symlink()
                and not (Path(directory) / n).exists()]

    shutil.copytree(src, dest, symlinks=False, ignore=ignore)
    return name


def copy_file(src: Path, stage: Path) -> str:
    name = _key(src, src.name)
    shutil.copy2(src, stage / name)
    return name


def filter_claude_settings(src: Path, stage: Path) -> str:
    data = json.loads(src.read_text())
    for key in ("hooks", "statusLine"):
        data.pop(key, None)
    name = _key(src, "settings.json")
    (stage / name).write_text(json.dumps(data, indent=2) + "\n")
    return name


def filter_codex_config(src: Path, stage: Path) -> str:
    """Remove as tabelas [projects."..."], indexadas por caminho do HOST."""
    kept, skipping = [], False
    project_table = re.compile(r'^\s*\[projects\b')
    any_table = re.compile(r"^\s*\[")
    for line in src.read_text().splitlines(keepends=True):
        if project_table.match(line):
            skipping = True
            continue
        if skipping and any_table.match(line):
            skipping = False
        if not skipping:
            kept.append(line)
    name = _key(src, "config.toml")
    (stage / name).write_text("".join(kept))
    return name


FILTERS = {
    "claude-settings": filter_claude_settings,
    "codex-config": filter_codex_config,
}


def build_staging(manifest: Path, stage: Path, home: Path) -> int:
    stage.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    entries = tomllib.loads(Path(manifest).read_text()).get("entry", [])

    for entry in entries:
        raw_src, raw_dst = entry["src"], entry["dst"]
        src = Path(raw_src.replace("~", str(home), 1))
        dst = Path(raw_dst.replace("~", str(home), 1))

        if (bad := denied(Path(raw_src))) is not None:
            raise StagingError(f"{raw_src} contem caminho negado ({bad})")
        if not src.exists():
            continue
        if (bad := scan(src, home)) is not None:
            raise StagingError(f"{src} contem caminho negado ({bad})")
        if ".." in dst.parts or not dst.is_absolute() or denied(dst) or not any(
                dst == root or dst.is_relative_to(root)
                for root in _allowed_destination_roots(home)):
            raise StagingError(f"destino fora das raizes permitidas: {dst}")

        if (name := entry.get("filter")):
            staged = FILTERS[name](src, stage)
        elif src.is_dir():
            staged = materialize(src, stage)
        else:
            staged = copy_file(src, stage)
        lines.append(f"{staged}\t{dst}")

    (stage / "manifest.tsv").write_text("".join(f"{l}\n" for l in lines))
    return len(lines)
```

- [ ] **Step 4: Update the provision manifest**

In `profiles/provision.toml`, change every `dst` from `/home/agent/...` to
`~/...` (the module expands `~` to the host home), delete the
`filter = "antigravity-hooks"` line, and add `filter = "codex-config"` to the
`~/.codex/config.toml` entry. Leave the explanatory comments; update the one
that mentions `/home/agent`.

- [ ] **Step 5: Materialize from the read-only mount in the entrypoint**

Insert into `image/entrypoint.sh`, before the `exec /usr/sbin/sshd` line:

```bash
# Configuracao do host: chega como mount READ-ONLY e e copiada para o home. Nao
# se monta direto sobre ~/.claude/settings.json porque os agentes escrevem
# nesses arquivos durante a sessao. Como a ORIGEM e um mount que o agente nao
# escreve, nao ha janela de TOCTOU — e por isso sumiram o instalador root, o
# token por partida e o portao do sshd que o v1 precisava.
if [ -f /run/asb-config/manifest.tsv ]; then
  while IFS=$'\t' read -r src dst; do
    [ -n "$src" ] || continue
    install -d -o "$ASB_USER" -g "$ASB_USER" "$(dirname "$dst")"
    rm -rf "$dst"
    cp -a "/run/asb-config/$src" "$dst"
    chown -R "$ASB_USER:$ASB_USER" "$dst"
  done < /run/asb-config/manifest.tsv
fi
```

- [ ] **Step 6: Mount the staging tree in `up`**

In `lifecycle.py`, before creating the agent container:

```python
    stage = layout.state / "staging"
    shutil.rmtree(stage, ignore_errors=True)
    staged = build_staging(root / "profiles" / "provision.toml", stage, home)
    print(f"configuracao: {staged} entrada(s)", file=sys.stderr)
```

and add to `agent_args`, immediately before the image name:

```python
        "-v", f"{stage}:/run/asb-config:ro,Z",
```

Add `import shutil` and `from .staging import build_staging` to the imports.

- [ ] **Step 7: Write the integration test**

Replace `tests/test-provision.sh`:

```bash
#!/usr/bin/env bash
# tests/test-provision.sh — a configuracao do host chega ao sandbox, e a
# credencial do host NAO chega.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-prov-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== provisionamento da configuracao =="
require "o agente responde" podman exec "$AGENT" true

# Skills so servem se estiverem materializadas: um symlink do host para
# /usr/share/omarchy/... chega quebrado se nao for resolvido.
if [ -d "$HOME/.claude/skills" ]; then
  assert_eq "0" "$(podman exec "$AGENT" sh -c "test -d '$HOME/.claude/skills'; echo \$?")" \
    "as skills do Claude chegaram"
  assert_eq "0" "$(podman exec "$AGENT" sh -c \
    "find '$HOME/.claude/skills' -xtype l | head -1 | wc -l | grep -q '^0$'; echo \$?")" \
    "nenhuma skill chegou como link quebrado"
fi

# A credencial do host NUNCA entra: ela mora no volume de credenciais, que e
# outro caminho e outro dono.
for leak in "$HOME/.claude/.credentials.json.host" "$HOME/.ssh/id_ed25519"; do
  assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$leak'; echo \$?")" \
    "nao vazou: $leak"
done

# O staging e read-only: o agente nao pode reescrever a propria origem de
# configuracao para a proxima partida.
assert_fails "o agente nao escreve no staging montado" \
  podman exec "$AGENT" sh -c 'touch /run/asb-config/x'

report
```

- [ ] **Step 8: Run both suites**

Run: `python3 -m unittest discover -s tests/unit -v && bash tests/test-provision.sh`
Expected: PASS.

- [ ] **Step 9: Delete the superseded module**

```bash
git rm cli/lib/provision.py
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -F - <<'MSG'
🔐 stage host configuration behind a read-only mount: provisioning

Replaces podman cp plus a root installer plus a per-start token with a
staging tree the agent cannot write.

### 💡 Architecture improvements

The CLI builds the staging tree on the host, mounts it read-only, and
the entrypoint copies from it into the home. Not a direct mount onto the
settings files, because the agents write to them during a session; not
podman cp, because that is what required the root installer and the
token. Since the source is a mount the agent cannot write, there is no
TOCTOU window, so install-config.py, the provisioning token and the sshd
gate are all deleted.

Destination roots now resolve against the host home rather than the
literal /home/agent, following the identical-path decision. The
antigravity-hooks filter is deleted with them: it existed only to
rewrite the host home out of hook commands, and the path is now the
same on both sides.

### 🔐 Security & Access Control

The deny list and the symlink scan are preserved and covered by tests,
including the case that motivated them: a symlink with an innocent name
whose target is a credential file. Names are not enough — the target is
what is checked. A symlink pointing outside the declared tree and the
allowed skill roots is refused rather than followed.

Two filters remain. claude-settings still strips hooks and statusLine,
because they point at host binaries absent from the container and the
identical path now resolves to a plausible empty location, turning a
visible error into a silent one. codex-config is new and strips the
projects tables, which are keyed by host path and would leave the
sandbox carrying other projects' names while not recognising its own.

### 🚀 Outcome

Skills, plugins, hooks and MCP configuration reach the sandbox in one
declared, auditable step. cli/lib/provision.py is removed.
MSG
```

---

## Task 8: Credentials in a volume, and `login`

Closes the operator's problem #1 at its root: one login, not one per workspace,
and one that survives rebuilding the image.

**Design note — why only the credential files, not the config directories.**
Inspection of this host shows Claude keeps `~/.claude/.credentials.json`,
Codex keeps `~/.codex/auth.json`, and Antigravity keeps
`~/.local/share/keyrings/`. Sharing the whole `~/.codex` across workspaces was
rejected: it holds live SQLite databases with WAL files
(`logs_2.sqlite-wal`, `goals_1.sqlite-shm`), and two concurrent workspaces
writing them risks corruption. Everything else stays container-local and
disposable, seeded from staging on every start, which is what the spec asks
for.

**Files:**
- Modify: `cli/asb/lifecycle.py` (add `login`, mount the credentials volume)
- Modify: `image/entrypoint.sh` (link the credential paths into the volume)
- Test: `tests/test-auth.sh`
- Delete: `cli/lib/auth.sh`

**Interfaces:**
- Consumes: `podman.*`, `IMAGE`.
- Produces:
  - volume `asb-credentials`, mounted at `/run/asb-credentials`
  - `login(root) -> int`
  - `ensure_keyring_pass() -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test-auth.sh`:

```bash
#!/usr/bin/env bash
# tests/test-auth.sh — a credencial sobrevive ao workspace e a imagem.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS_A="test-auth-a-$$"
WS_B="test-auth-b-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1
}
trap cleanup EXIT

echo "== credenciais =="
"$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }
A="asb-${WS_A}-agent"
require "o agente A responde" podman exec "$A" true

# O caminho real e um LINK para o volume: o refresh de token que o agente faz
# durante a sessao precisa aterrissar no volume, nao numa copia efemera.
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.claude/.credentials.json'; echo \$?")" \
  "a credencial do Claude e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'; echo \$?")" \
  "a credencial do Codex e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.local/share/keyrings'; echo \$?")" \
  "o keyring e um link para o volume"

# Escreve pelo CAMINHO REAL (como o agente faz) e confirma que aterrissou no
# volume. Se algum agente substituir o link por arquivo comum, este teste e o
# que acusa — e a correcao e trocar o link por bind mount do arquivo.
podman exec "$A" sh -c "printf 'marca-do-teste' > '$HOME/.codex/auth.json'"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'; echo \$?")" \
  "escrever pelo caminho real nao destruiu o link"

"$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null

echo "-- outro workspace ve a mesma credencial --"
"$ROOT/cli/asb-agent" up --workspace "$WS_B" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up de B falhou"; exit 1; }
B="asb-${WS_B}-agent"
require "o agente B responde" podman exec "$B" true
assert_eq "marca-do-teste" \
  "$(podman exec "$B" sh -c "cat '$HOME/.codex/auth.json'")" \
  "a credencial sobreviveu ao down e chegou ao workspace novo"

echo "-- o volume nao e removido por down nem por purge --"
"$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null
assert_eq "0" "$(podman volume exists asb-credentials; echo $?)" \
  "o volume de credenciais sobreviveu ao down"

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-auth.sh`
Expected: FAIL on the first `test -L` assertion — nothing links the credential
paths yet.

- [ ] **Step 3: Link the credential paths in the entrypoint**

Insert into `image/entrypoint.sh`, **after** the staging block (so staging
never overwrites a link) and before `exec /usr/sbin/sshd`:

```bash
# Credenciais: o volume e a fonte, e o caminho real e um LINK para dentro dele.
# Nao uma copia: os agentes renovam o token durante a sessao, e uma copia
# perderia a renovacao na proxima partida — que e exatamente o sintoma de
# "perdi a sessao" que este redesenho existe para eliminar.
if [ -d /run/asb-credentials ]; then
  link_credential() {
    real="$1"; stored="/run/asb-credentials/$2"
    install -d -o "$ASB_USER" -g "$ASB_USER" "$(dirname "$real")"
    [ -e "$stored" ] || [ -d "$stored" ] || {
      : > "$stored"; chmod 0600 "$stored"; }
    rm -rf "$real"
    ln -s "$stored" "$real"
    chown -h "$ASB_USER:$ASB_USER" "$real"
  }
  install -d -o "$ASB_USER" -g "$ASB_USER" -m 0700 /run/asb-credentials/keyrings
  link_credential "$ASB_HOME/.claude/.credentials.json" claude.json
  link_credential "$ASB_HOME/.codex/auth.json"          codex-auth.json
  link_credential "$ASB_HOME/.local/share/keyrings"     keyrings
  chown -R "$ASB_USER:$ASB_USER" /run/asb-credentials
fi
```

- [ ] **Step 4: Mount the volume and implement `login`**

Add to `cli/asb/lifecycle.py`:

```python
CREDENTIALS_VOLUME = "asb-credentials"
KEYRING_PASS = CONFIG / "keyring.pass"


def ensure_credentials_volume() -> str:
    if not podman.exists("volume", CREDENTIALS_VOLUME):
        podman.run("volume", "create", CREDENTIALS_VOLUME)
    return CREDENTIALS_VOLUME


def ensure_keyring_pass() -> Path:
    """A passphrase do keyring vive SO no host. Uma copia do volume levada para
    outra maquina carrega um keyring cifrado que nao abre — verificado no v1:
    com a passphrase errada o agy falha enquanto o claude continua respondendo,
    provando que a falha e do keyring e nao geral."""
    if KEYRING_PASS.exists():
        return KEYRING_PASS
    CONFIG.mkdir(parents=True, exist_ok=True)
    CONFIG.chmod(0o700)
    KEYRING_PASS.write_text(
        base64.b64encode(os.urandom(32)).decode().strip())
    KEYRING_PASS.chmod(0o600)
    return KEYRING_PASS


def login(root: Path) -> int:
    """Autentica os tres agentes UMA VEZ, num container fora da rede interna.

    Fora da rede interna de proposito: o login por device-auth precisa de
    egresso direto, e nao ha proxy algum neste caminho.
    """
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    ensure_credentials_volume()
    passphrase = ensure_keyring_pass().read_text().strip()
    name = "asb-login"
    if podman.exists("container", name):
        podman.run("rm", "-f", name, check=False)

    # Com o ENTRYPOINT REAL, nao --entrypoint sleep: e o entrypoint que sobe o
    # D-Bus, destrava o keyring e popula /etc/profile.d. Com sleep nada disso
    # acontece e o agy guarda a credencial em ARQUIVO TEXTO em silencio.
    podman.run(
        "run", "-d", "--name", name,
        "--userns", "keep-id:uid=1000,gid=1000",
        "-e", f"ASB_KEYRING_PASS={passphrase}",
        "-v", f"{CREDENTIALS_VOLUME}:/run/asb-credentials:Z",
        IMAGE)
    try:
        print("\nEntre em cada agente. Use SEMPRE fluxos de device-auth: o "
              "OAuth padrao abre um servidor de callback numa porta do "
              "container que o navegador do host nao alcanca, e trava.\n",
              file=sys.stderr)
        for label, command in (
                ("Claude Code", "claude /login"),
                ("Codex", "codex login --device-auth"),
                # `agy` nao tem subcomando `login`: o binario nu abre a TUI,
                # que autentica no primeiro uso. `agy login` falha com
                # "unexpected argument".
                ("Antigravity", "agy")):
            print(f"--- {label} ---", file=sys.stderr)
            # `bash -lc` nao e decoracao: sem shell de login o agy nao esta no
            # PATH e DBUS_SESSION_BUS_ADDRESS esta ausente, que e exatamente
            # como a credencial acaba em texto claro em vez do keyring.
            subprocess.run([podman.require_binary(), "exec", "-it",
                            "-u", "1000", name, "bash", "-lc", command])

        # Verificar por CODIGO DE SAIDA, nunca por grep de "logged in": essa
        # string casa tambem com "not logged in".
        checks = (("Codex", "codex login status"),
                  ("Claude Code", "claude -p ping < /dev/null"),
                  ("Antigravity", "asb-agy --version"))
        failed = []
        for label, command in checks:
            result = subprocess.run(
                [podman.require_binary(), "exec", "-u", "1000", name,
                 "timeout", "120", "bash", "-lc", command],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state = "ok" if result.returncode == 0 else "FALHOU"
            print(f"  {label}: {state}", file=sys.stderr)
            if result.returncode != 0:
                failed.append(label)
        if failed:
            raise podman.PodmanError(
                "nao autenticado: " + ", ".join(failed))
        print("credenciais gravadas no volume asb-credentials", file=sys.stderr)
        return 0
    finally:
        podman.run("rm", "-f", name, check=False)
```

Add `import base64` to the imports.

In `up`, add to `agent_args` before the image name:

```python
        "-e", f"ASB_KEYRING_PASS={ensure_keyring_pass().read_text().strip()}",
        "-v", f"{ensure_credentials_volume()}:/run/asb-credentials:Z",
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tests/test-auth.sh`
Expected: PASS.

**If the link is replaced by a regular file** after an agent writes, that agent
rewrites atomically (temp file plus rename), and the symlink approach loses its
refresh. The fallback is a single-file bind mount from a host path instead of a
link for that agent alone:
`-v ~/.config/agent-sandbox/credentials/codex-auth.json:$HOME/.codex/auth.json:Z`.
The test above is what detects this; do not assume either way.

- [ ] **Step 6: Do the login once, by hand**

Run: `./cli/asb-agent login`
Complete the three device-auth flows. Then confirm a fresh workspace comes up
authenticated, which is the whole point of the task:

```bash
./cli/asb-agent up --workspace login-check --repo /path/to/a/repo
podman exec -u 1000 asb-login-check-agent bash -lc 'codex login status'
./cli/asb-agent down --workspace login-check
```

- [ ] **Step 7: Delete the v1 auth path**

```bash
git rm cli/lib/auth.sh
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -F - <<'MSG'
🔐 keep agent credentials in a volume: one login per machine

Moves the three agents' credentials out of a derivative image and into a
named volume, so logging in is a per-machine event rather than a
per-workspace one.

### 💡 Architecture improvements

agent-sandbox-auth and its -prev copies are gone. Credentials living in
an image meant every rebuild cost three interactive logins and left
stale images holding old secrets. The volume survives image rebuilds,
workspace teardown and reboot, and down and purge never remove it.

Only the credential paths are shared, not the configuration
directories. Inspection of this host shows ~/.codex holds live SQLite
databases with WAL files, and two concurrent workspaces writing them
risks corruption. Everything else stays container-local and disposable,
reseeded from staging on each start.

### 🔐 Security & Access Control

The real credential paths are symlinks into the volume rather than
copies, because the agents refresh their tokens mid-session and a copy
would lose the refresh at the next start — which is precisely the lost
session this rebuild set out to eliminate. A test writes through the
real path and asserts the link survives, so an agent that rewrites
atomically is detected rather than assumed.

The keyring passphrase stays on the host and is injected at runtime, so
a copy of the volume carried to another machine holds an encrypted
keyring that does not open. Logins are verified by exit code, never by
grepping for "logged in", which also matches "not logged in".

### 🚀 Outcome

asb-agent login runs once. Fresh workspaces come up authenticated.
cli/lib/auth.sh is removed.
MSG
```

---

## Task 9: Disposable services and `host_ports`

Two of the three Docker axes (spec §6.1). Closes the database half of the
operator's hexmed case.

> **Verified on this host** (2026-09-04). The chain agent → forwarder container
> (reached by name) → `host.containers.internal` → host service works, and a
> `socat` inside the agent listening on `127.0.0.1` completes it so the project
> keeps using `localhost:5432`. **A host service bound only to `127.0.0.1` is
> not reachable** — measured. `docker compose` publishes on `0.0.0.0` by
> default, so the real case works; a port published as
> `127.0.0.1:5432:5432` does not, and `doctor` must say so by name.

**Files:**
- Modify: `cli/asb/lifecycle.py` (start services and the forwarder)
- Modify: `image/entrypoint.sh` (loopback socat per declared port)
- Test: `tests/test-services.sh`
- Delete: `cli/lib/attach.sh`

**Interfaces:**
- Consumes: `Profile.services`, `Profile.host_ports`.
- Produces: containers `asb-<ws>-svc-<name>`, `asb-<ws>-fwd`; env
  `ASB_HOST_PORTS` (comma-separated) read by the entrypoint.

- [ ] **Step 1: Write the failing test**

Create `tests/test-services.sh`:

```bash
#!/usr/bin/env bash
# tests/test-services.sh — servicos descartaveis e portas do host.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-svc-$$"
PORT=54321
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md
cat > .agent-sandbox.toml <<TOML
[docker]
host_ports = [$PORT]

[services.cache]
image = "docker.io/library/redis:7-alpine"
TOML
git add -A && git commit -qm inicial
cd "$ROOT"

# Servico do host em 0.0.0.0, como o docker compose publica. Ligado apenas a
# 127.0.0.1 ele NAO seria alcancavel — medido.
python3 - "$PORT" <<'PY' &
import socket, sys, threading, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", int(sys.argv[1]))); s.listen(5)
def serve():
    while True:
        c, _ = s.accept(); c.sendall(b"HOST-OK\n"); c.close()
threading.Thread(target=serve, daemon=True).start(); time.sleep(120)
PY
HOST_SVC=$!
cleanup() {
  kill "$HOST_SVC" 2>/dev/null
  "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1
}
trap cleanup EXIT
sleep 1

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== servicos e portas do host =="
require "o agente responde" podman exec "$AGENT" true
require "o servico do host responde no proprio host" \
  timeout 3 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT"

assert_eq "0" "$(podman exec "$AGENT" sh -c \
  'timeout 5 nc -z asb-'"$WS"'-svc-cache 6379; echo $?')" \
  "o servico descartavel e alcancavel por nome"

# O projeto continua apontando para localhost: e a razao do socat de loopback
# dentro do container do agente.
assert_contains "HOST-OK" "$(podman exec "$AGENT" sh -c \
  "timeout 5 nc 127.0.0.1 $PORT")" \
  "a porta declarada do host chega em localhost dentro do sandbox"

# Cirurgico: SO as portas declaradas. O host participa de uma rede Tailscale, e
# abrir faixas privadas entregaria a tailnet inteira ao agente.
assert_fails "uma porta NAO declarada do host nao e alcancavel" \
  podman exec "$AGENT" sh -c "timeout 3 nc -z 127.0.0.1 $((PORT+1))"

echo "-- servicos sao descartaveis --"
"$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null
assert_eq "1" "$(podman container exists asb-${WS}-svc-cache; echo $?)" \
  "o servico foi removido junto com o workspace"

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-services.sh`
Expected: FAIL — no service container and no forwarder exist.

- [ ] **Step 3: Implement services and the forwarder**

Add to `cli/asb/lifecycle.py`, called from `up` after the proxy and **before**
the agent:

```python
def start_services(ws: str, profile: Profile) -> None:
    n = names(ws)
    for service in profile.services:
        container = f"asb-{ws}-svc-{service.name}"
        env = []
        for key, value in service.env.items():
            env += ["-e", f"{key}={value}"]
        # --user 0: imagens sem diretiva USER (postgres, por exemplo) sao
        # resolvidas por keep-id para o uid mapeado do host, e o initdb falha
        # em ajustar permissoes dos diretorios da propria imagem.
        podman.run("run", "-d", "--name", container, "--restart",
                   "unless-stopped", "--network", n["net"], "--user", "0",
                   *env, service.image)


def start_forwarder(ws: str, profile: Profile) -> None:
    """Encaminha SO as portas declaradas para o host.

    Nunca faixas privadas: o host participa de uma rede Tailscale, e liberar
    RFC1918 ou CGNAT entregaria a tailnet inteira ao agente.

    O encaminhador tem perna na rede externa porque so assim alcanca o gateway
    do host. Ele nao e um proxy de uso geral: roda socat com destinos fixos, e
    o agente so alcanca as portas listadas.
    """
    if not profile.host_ports:
        return
    n = names(ws)
    forwarder = f"{n['net']}-fwd"
    script = "; ".join(
        f"socat TCP-LISTEN:{port},fork,reuseaddr "
        f"TCP:host.containers.internal:{port} &" for port in profile.host_ports)
    podman.run("run", "-d", "--name", forwarder, "--restart", "unless-stopped",
               "--network", f"{n['net']},{n['out']}", "--user", "900",
               "--entrypoint", "sh", PROXY_IMAGE, "-c", f"{script} wait")
```

`socat` must exist in the proxy image — add it to `image/Containerfile.proxy`'s
apt list.

In `up`, pass the port list to the agent so its entrypoint can bind loopback,
adding to `agent_args` before the image name:

```python
        "-e", "ASB_HOST_PORTS=" + ",".join(str(p) for p in profile.host_ports),
```

Extend `down` to remove the service and forwarder containers:

```python
    _sweep_containers(ws)
```

`_sweep_containers` arrived with `up`'s rollback in Task 5. Replace the
explicit agent/proxy removal loop in `down` with a call to it, so a container
type added later cannot be forgotten and leak.

- [ ] **Step 4: Bind loopback inside the agent**

Insert into `image/entrypoint.sh`, before `exec /usr/sbin/sshd`:

```bash
# O projeto continua apontando para localhost:5432. Sem pod, o agente e o
# encaminhador estao em namespaces separados, entao um socat local recria o
# endereco que o projeto espera. Dois saltos triviais; a alternativa seria
# reescrever a configuracao de cada projeto.
if [ -n "${ASB_HOST_PORTS:-}" ]; then
  fwd="asb-$(cat /etc/agent-sandbox-workspace)-fwd"
  echo "$ASB_HOST_PORTS" | tr ',' '\n' | while read -r port; do
    [ -n "$port" ] || continue
    setsid socat "TCP-LISTEN:${port},bind=127.0.0.1,fork,reuseaddr" \
      "TCP:${fwd}:${port}" >/dev/null 2>&1 &
  done
fi
```

The forwarder's name needs the workspace id inside the container. Write it in
`up` by adding to `agent_args`:

```python
        "-e", f"ASB_WORKSPACE={ws}",
```

and replace the `fwd=` line above with:

```bash
  fwd="asb-${ASB_WORKSPACE}-fwd"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tests/test-services.sh`
Expected: PASS. If the host-port assertion fails while its positive control
passes, check that the host service is bound to `0.0.0.0` and not `127.0.0.1`.

- [ ] **Step 6: Delete the v1 attached mode**

```bash
git rm cli/lib/attach.sh
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✨ reach declared host ports and disposable services: docker axes

Implements two of the three Docker axes: services running inside the
workspace network, and surgical forwarding to declared host ports.

### ✅ New features

Services declared in the profile start on the internal network and are
reachable by container name, then disappear with the workspace. Ports
listed in host_ports are forwarded through a dedicated container that
holds the only leg toward the host gateway, and a loopback socat inside
the agent reproduces the address the project already expects, so a
project pointing at localhost:5432 keeps working unchanged.

### 🔐 Security & Access Control

Only declared ports are forwarded, never ranges. The host participates
in a Tailscale network, so opening RFC1918 or CGNAT would hand the
agent the whole tailnet. A test asserts that an undeclared neighbouring
port is not reachable. The forwarder is not a general-purpose proxy: it
runs socat against fixed destinations, so its external leg buys the
agent nothing beyond the listed ports.

### 🧼 Best practices & validations

down now sweeps every container by workspace prefix rather than naming
them one by one, so a container type added later cannot be forgotten and
leak. Service containers run as uid 0 because images without a USER
directive are resolved by keep-id to a mapped host uid, and initdb then
fails to adjust permissions on the image's own directories.

### 🚀 Outcome

The hexmed database case works end to end. cli/lib/attach.sh is removed.
The remaining Docker axis, nested containers, is next.
MSG
```

---

## Task 10: Nested containers (`mode = "nested"`)

The third Docker axis, and the whole of the operator's BlackICE case: that
project's dependency is on having *a* container runtime, not on the host's. It
builds its own images (`infra/compose.apps.yml` uses `build:`), so a runtime
inside the sandbox serves it with zero host exposure.

> **Probed on this host** (2026-09-04, two measurements).
> `quay.io/podman/stable` under `--userns keep-id:uid=1000,gid=1000 --device
> /dev/fuse --security-opt label=disable` reports `rootless=true` and runs a
> nested container successfully — **the exact configuration this task needs**.
> A naive Debian attempt (`apt install podman`, then `su` to a user) failed
> with `newuidmap: write to uid_map failed: Operation not permitted`. The
> difference is configuration, not capability: the reference image sets
> `/etc/subuid`, a `fuse-overlayfs` storage driver and cgroupfs. Step 3 carries
> those settings; do not skip any of them.

**Files:**
- Modify: `image/Containerfile` (podman and its rootless configuration)
- Modify: `cli/asb/lifecycle.py` (nested flags when the profile asks)
- Test: `tests/test-nested.sh`

**Interfaces:**
- Consumes: `Profile.container_mode`.
- Produces: agent container flags `--device /dev/fuse --security-opt
  label=disable`, plus volume `asb-<ws>-containers` for nested image storage.

- [ ] **Step 1: Write the failing test**

Create `tests/test-nested.sh`:

```bash
#!/usr/bin/env bash
# tests/test-nested.sh — runtime de containers DENTRO do sandbox.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-nested-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md
printf '[docker]\nmode = "nested"\n' > .agent-sandbox.toml
git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== containers aninhados =="
require "o agente responde" podman exec "$AGENT" true
require "o podman aninhado responde" \
  podman exec -u 1000 "$AGENT" bash -lc 'podman --version'

assert_contains "true" \
  "$(podman exec -u 1000 "$AGENT" bash -lc \
     'podman info --format "{{.Host.Security.Rootless}}" 2>/dev/null | tail -1')" \
  "o podman aninhado roda rootless"

# O pull sai pelo Squid: sem os registries na allowlist a falha apareceria como
# "o build nao funciona", sem apontar a causa.
assert_contains "ANINHADO-OK" \
  "$(podman exec -u 1000 "$AGENT" bash -lc \
     'timeout 300 podman run --rm docker.io/library/alpine:latest echo ANINHADO-OK 2>&1 | tail -1')" \
  "o agente puxa e roda uma imagem atraves do proxy"

# A fronteira nao afrouxa por causa do modo aninhado.
assert_fails "o agente continua sem egresso direto" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e /var/run/docker.sock; echo \$?")" \
  "o socket do Docker do host nao esta montado"

report
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tests/test-nested.sh`
Expected: ABORT at the nested-podman positive control — podman is not in the
image yet.

- [ ] **Step 3: Add podman and its rootless configuration to the image**

Append to `image/Containerfile`, before the `COPY cli/asb-guard` line:

```dockerfile
# Runtime de containers DENTRO do sandbox (spec §6.2). As quatro linhas de
# configuracao abaixo nao sao opcionais: sem elas o podman aninhado falha com
# "newuidmap: write to uid_map failed: Operation not permitted" — medido.
RUN apt-get update && apt-get install -y --no-install-recommends \
      podman fuse-overlayfs uidmap passt slirp4netns \
    && rm -rf /var/lib/apt/lists/*

# 1) subuid/subgid para o usuario: sem eles nao ha namespace aninhado a criar.
RUN echo "$ASB_USER:100000:65536" > /etc/subuid \
    && echo "$ASB_USER:100000:65536" > /etc/subgid

# 2) overlay via fuse-overlayfs: o driver overlay do kernel nao esta disponivel
#    para um usuario sem privilegio dentro de outro container.
RUN mkdir -p /etc/containers && printf '%s\n' \
      '[storage]' \
      'driver = "overlay"' \
      '[storage.options.overlay]' \
      'mount_program = "/usr/bin/fuse-overlayfs"' \
      > /etc/containers/storage.conf

# 3) cgroupfs e log em arquivo: nao ha systemd nem sessao dbus de usuario aqui.
RUN printf '%s\n' \
      '[engine]' \
      'cgroup_manager = "cgroupfs"' \
      'events_logger = "file"' \
      > /etc/containers/containers.conf

# 4) registries explicitos: sem isso um `podman run alpine` fica ambiguo e o
#    podman recusa em vez de escolher.
RUN printf '%s\n' \
      'unqualified-search-registries = ["docker.io"]' \
      > /etc/containers/registries.conf
```

- [ ] **Step 4: Pass the nested flags when the profile asks**

In `lifecycle.up`, after `agent_args` is built:

```python
    if profile.container_mode == "nested":
        # /dev/fuse para o fuse-overlayfs; label=disable porque o SELinux do
        # host nao rotula o que o podman de dentro cria. NAO --privileged: a
        # nidificacao nao precisa e o custo seria a fronteira inteira.
        volume = f"{n['net']}-containers"
        if not podman.exists("volume", volume):
            podman.run("volume", "create", volume)
        agent_args[-1:-1] = [
            "--device", "/dev/fuse",
            "--security-opt", "label=disable",
            # Armazenamento das imagens aninhadas fora da camada gravavel: um
            # `down` seguido de `up` nao rebaixa tudo de novo.
            "-v", f"{volume}:{home}/.local/share/containers:Z",
        ]
```

`agent_args[-1:-1]` inserts before the image name, which must stay last. Add
the volume to `down`'s sweep by removing it explicitly there:

```python
    volume = f"asb-{ws}-containers"
    if podman.exists("volume", volume):
        podman.run("volume", "rm", "-f", volume, check=False)
```

- [ ] **Step 5: Rebuild and run the test**

Run: `./cli/asb-agent build && bash tests/test-nested.sh`
Expected: PASS.

**If `newuidmap` still fails**, compare against the reference image, which is
known to work in this exact configuration:
`podman run --rm quay.io/podman/stable cat /etc/containers/storage.conf
/etc/containers/containers.conf /etc/subuid`. Adopt whatever differs. If Debian
cannot be made to work, the fallback is a second image for nested mode based on
`quay.io/podman/stable` with the agent CLIs layered on; record that decision in
the commit body rather than leaving the axis broken.

- [ ] **Step 6: Verify the operator's real case once, by hand**

```bash
cd ~/Data/Projects/BlackICE
printf '[docker]\nmode = "nested"\n' >> .agent-sandbox.toml
# suba um workspace e, dentro dele:
#   podman compose -f infra/compose.yml up -d
# confirme que traefik, product-db e keycloak sobem SEM tocar no host
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✨ run containers inside the sandbox: nested mode

Adds the third Docker axis. A project whose dependency is on having a
container runtime, rather than on the host's, is now fully served with
no host exposure at all.

### ✅ New features

With mode = "nested" the agent container gains /dev/fuse and a relaxed
label, and carries a rootless podman configured with its own subuid
range, fuse-overlayfs storage, cgroupfs and an explicit registry list.
Nested image storage lives in a named volume, so tearing a workspace
down and bringing it back does not re-pull everything.

### 💡 Architecture improvements

Nesting is deliberately not --privileged. It does not need to be, and
the cost would be the entire boundary. Image pulls go through Squid like
every other request, which is why the registry domains are added to the
allowlist exactly when this mode is on.

### 🔐 Security & Access Control

Tests assert the boundary does not loosen for nested mode: the agent
still has no direct egress, and the host Docker socket is still absent.
This axis exists so that full container capability never requires
handing over the host's daemon.

### 🚀 Outcome

The BlackICE case is served without the host broker. The remaining axis,
read-only access to the host's Docker API, is next.
MSG
```

---

## Task 11: Read-only Docker broker (`host_api = "read"`)

The last Docker axis, and the operator's hexmed debugging case: reading logs
from containers that run **on the host, with real data** — which nested mode
cannot offer.

**Why a broker at all (spec §6.3).** `/var/run/docker.sock` is `root:docker
0660` and the operator is not in the `docker` group; they run `sudo docker`.
So the socket is unreachable from a rootless container, and mounting it raw
would be host root anyway. A root-owned filter is the only honest crossing.

**Why not nginx.** The v1-adjacent reference (BlackICE's own
`infra/traefik/docker-api-proxy/nginx.conf`) runs under rootful Docker where
`user root` is really uid 0. Reproducing it here would add nginx or an image
pull as root. A stdlib Python relay is smaller, has no dependencies, matches
D6, and is easier for the operator to read — which is the point of §16.

**Files:**
- Create: `broker/asb-docker-broker.py`
- Create: `broker/asb-docker-broker.service.tmpl`
- Modify: `cli/asb/install.py` (add `broker`)
- Modify: `cli/asb/lifecycle.py` (start `asb-<ws>-docker` when asked)
- Test: `tests/test-broker.sh`

**Interfaces:**
- Consumes: `Profile.host_api`.
- Produces: unix socket `/run/asb-docker/docker.sock` (uid 1000, 0600);
  container `asb-<ws>-docker`; env `DOCKER_HOST` in the agent.

- [ ] **Step 1: Write the failing test**

Create `tests/test-broker.sh`:

```bash
#!/usr/bin/env bash
# tests/test-broker.sh — o filtro do socket do Docker.
#
# Nao exige o broker instalado: sem ele, o teste PULA em vez de falhar, porque
# a instalacao pede sudo e nao pode ser um pre-requisito silencioso da suite.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

SOCK=/run/asb-docker/docker.sock
if [ ! -S "$SOCK" ]; then
  echo "PULADO: broker nao instalado (use 'asb-agent install-broker')"
  exit 0
fi

echo "== filtro do broker =="
ask() {
  printf 'GET %s HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n' "$1" \
    | timeout 5 socat - "UNIX-CONNECT:$SOCK" 2>/dev/null | head -n 1
}
post() {
  printf 'POST %s HTTP/1.1\r\nHost: docker\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' "$1" \
    | timeout 5 socat - "UNIX-CONNECT:$SOCK" 2>/dev/null | head -n 1
}

require "o broker responde" sh -c '[ -n "$(printf "GET /v1.43/version HTTP/1.1\r\nHost: d\r\nConnection: close\r\n\r\n" | timeout 5 socat - UNIX-CONNECT:'"$SOCK"' | head -n 1)" ]'

assert_contains "200" "$(ask /v1.43/version)"          "version e permitido"
assert_contains "200" "$(ask /v1.43/containers/json)"  "ps e permitido"

# Leitura so. Qualquer mutacao e 403, e isso NAO e configuravel: exec num
# container root com bind mount do host e root do host.
assert_contains "403" "$(post /v1.43/containers/create)"     "create e recusado"
assert_contains "403" "$(post /v1.43/containers/x/start)"    "start e recusado"
assert_contains "403" "$(post /v1.43/containers/x/exec)"     "exec e recusado"
assert_contains "403" "$(post /v1.43/build)"                 "build e recusado"
assert_contains "403" "$(ask /v1.43/images/json)"            "endpoint nao listado e recusado"
assert_contains "403" "$(ask '/v1.43/containers/../../secret')" "travessia de caminho e recusada"

assert_eq "1000" "$(stat -c %u "$SOCK")" "o socket pertence ao uid 1000"
assert_eq "600"  "$(stat -c %a "$SOCK")" "o socket e 0600"

report
```

- [ ] **Step 2: Run the test to verify it skips, then fails once installed**

Run: `bash tests/test-broker.sh`
Expected: `PULADO` — the broker socket does not exist yet.

- [ ] **Step 3: Write the broker**

Create `broker/asb-docker-broker.py`:

```python
#!/usr/bin/env python3
"""broker/asb-docker-broker.py — socket do Docker, filtrado e so-leitura.

Roda como root (unidade de sistema) e expoe um socket pertencente ao operador
com apenas os endpoints de LEITURA que o debug exige. Mutacao recebe 403 e nao
e configuravel: `exec` num container root com bind mount do host E root do
host, e chamar isso de contencao seria mentira.

Valida a linha de requisicao e os cabecalhos, depois relaciona bytes sem
reinterpretar a resposta — assim `logs --follow`, que e um fluxo, funciona sem
que este programa precise entender chunked encoding.
"""
from __future__ import annotations

import os
import re
import socket
import socketserver
import sys
import threading

DOCKER_SOCK = os.environ.get("ASB_DOCKER_SOCK", "/var/run/docker.sock")
LISTEN = os.environ.get("ASB_BROKER_SOCK", "/run/asb-docker/docker.sock")
OWNER_UID = int(os.environ.get("ASB_BROKER_UID", "1000"))

# Prefixo de versao opcional; o caminho e comparado ja normalizado.
VERSION = re.compile(r"^/v[0-9]+\.[0-9]+")
ALLOWED = (
    re.compile(r"^/version$"),
    re.compile(r"^/info$"),
    re.compile(r"^/events$"),
    re.compile(r"^/containers/json$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/json$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/logs$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/stats$"),
    re.compile(r"^/containers/[A-Za-z0-9_.-]+/top$"),
)

DENY = (b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n"
        b"Connection: close\r\n\r\n")


def permitted(method: str, target: str) -> bool:
    if method != "GET":
        return False
    path = target.split("?", 1)[0]
    # Comparar depois de normalizar: "/containers/../../x" nao pode virar um
    # caminho permitido por acidente.
    path = os.path.normpath(path)
    if not path.startswith("/"):
        return False
    path = VERSION.sub("", path, count=1) or "/"
    return any(rule.match(path) for rule in ALLOWED)


def relay(source: socket.socket, sink: socket.socket) -> None:
    try:
        while chunk := source.recv(65536):
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        client.settimeout(30)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 32768:
                client.sendall(DENY)
                return

        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split()
        if len(parts) != 3 or not permitted(parts[0], parts[1]):
            client.sendall(DENY)
            return

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.connect(DOCKER_SOCK)
            # Uma requisicao por conexao: com keep-alive, uma segunda
            # requisicao no mesmo socket passaria sem validacao.
            head = re.sub(rb"\r\nConnection:[^\r\n]*", b"", head,
                          flags=re.IGNORECASE)
            head = head.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n",
                                1)
            upstream.sendall(head)
            downward = threading.Thread(target=relay, args=(upstream, client))
            downward.start()
            relay(client, upstream)
            downward.join()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if not os.path.exists(DOCKER_SOCK):
        print(f"socket do Docker ausente: {DOCKER_SOCK}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(LISTEN), exist_ok=True)
    # Um socket antigo faz bind() falhar com EADDRINUSE, e o sintoma seria "o
    # broker nao sobe" sem dizer por que.
    if os.path.exists(LISTEN):
        os.unlink(LISTEN)
    os.umask(0o177)
    with Server(LISTEN, Handler) as server:
        os.chown(LISTEN, OWNER_UID, OWNER_UID)
        os.chmod(LISTEN, 0o600)
        print(f"broker ouvindo em {LISTEN} -> {DOCKER_SOCK}", file=sys.stderr)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the unit template and the installer**

Create `broker/asb-docker-broker.service.tmpl`:

```ini
[Unit]
Description=Socket do Docker filtrado e so-leitura para o agent-sandbox
After=docker.service
Wants=docker.service

[Service]
Type=simple
ExecStart=__PYTHON__ __SCRIPT__
Environment=ASB_DOCKER_SOCK=__DOCKER_SOCK__
Environment=ASB_BROKER_SOCK=/run/asb-docker/docker.sock
Environment=ASB_BROKER_UID=__UID__
Restart=on-failure
RestartSec=2s
RuntimeDirectory=asb-docker
NoNewPrivileges=yes
ProtectHome=yes
ProtectSystem=strict
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

Add to `cli/asb/install.py`:

```python
BROKER_SCRIPT = Path("/usr/local/lib/asb-docker-broker.py")
BROKER_UNIT = Path("/etc/systemd/system/asb-docker-broker.service")
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")


def broker(root: Path) -> int:
    """Instala o broker so-leitura. Requer sudo, uma vez.

    O script e COPIADO para /usr/local/lib: a unidade nao pode apontar para
    este checkout, senao mover a pasta quebraria o servico em silencio — o
    mesmo erro que o v1 cometeu com o ExecStart do restore (spec §16.1).
    """
    source = root / "broker" / "asb-docker-broker.py"
    docker_sock = next((s for s in DOCKER_SOCKETS if Path(s).exists()), None)
    if docker_sock is None:
        print("socket do Docker nao encontrado; nada a instalar. O eixo "
              "host_api fica indisponivel; os outros dois seguem normais.",
              file=sys.stderr)
        return 1

    unit = (root / "broker" / "asb-docker-broker.service.tmpl").read_text()
    unit = (unit.replace("__PYTHON__", sys.executable)
                .replace("__SCRIPT__", str(BROKER_SCRIPT))
                .replace("__DOCKER_SOCK__", docker_sock)
                .replace("__UID__", str(os.getuid())))

    print(f"instalando o broker (socket real: {docker_sock}).", file=sys.stderr)
    print("Isso concede LEITURA de Docker sem senha ao seu usuario: ps, logs, "
          "inspect. Mutacao recebe 403 e nao e configuravel.", file=sys.stderr)
    subprocess.run(["sudo", "install", "-m", "0755", str(source),
                    str(BROKER_SCRIPT)], check=True)
    subprocess.run(["sudo", "tee", str(BROKER_UNIT)], input=unit, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now",
                    "asb-docker-broker.service"], check=True)
    print("broker instalado. Habilite por projeto com [docker] host_api = "
          '"read" no .agent-sandbox.toml.', file=sys.stderr)
    return 0
```

Add `import os` and `import subprocess` to `install.py`.

- [ ] **Step 5: Wire the axis into `up`**

In `lifecycle.up`, after the proxy and before the agent:

```python
    if profile.host_api == "read":
        broker_sock = Path("/run/asb-docker/docker.sock")
        if not broker_sock.exists():
            raise podman.PodmanError(
                'host_api = "read" pede o broker; execute '
                "'asb-agent install-broker' (usa sudo, uma vez)")
        # Container proprio, SEM rede externa: quem fala com o socket do
        # Docker nao ganha egresso de tabela junto.
        podman.run(
            "run", "-d", "--name", f"{n['net']}-docker", "--restart",
            "unless-stopped", "--network", n["net"], "--user", "900",
            "-v", f"{broker_sock}:/var/run/docker.sock:Z",
            "--entrypoint", "sh", PROXY_IMAGE, "-c",
            "socat TCP-LISTEN:2375,fork,reuseaddr "
            "UNIX-CONNECT:/var/run/docker.sock")
```

and add to `agent_args` before the image name:

```python
        *(["-e", f"DOCKER_HOST=tcp://{n['net']}-docker:2375"]
          if profile.host_api == "read" else []),
```

- [ ] **Step 6: Install, then run the test**

Run: `./cli/asb-agent install-broker && bash tests/test-broker.sh`
Expected: PASS, with every mutating verb refused.

- [ ] **Step 7: Verify the hexmed case once, by hand**

```bash
cd ~/Data/Projects/hexmed-stack
printf '[docker]\nhost_api = "read"\n' >> .agent-sandbox.toml
# suba um workspace e, dentro dele:
#   docker ps           -> lista os containers do host
#   docker logs <nome>  -> mostra os logs
#   docker exec ...     -> deve ser recusado
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -F - <<'MSG'
🔐 expose a read-only Docker socket through a root broker: host api

Completes the third Docker axis, so an agent can read logs from
containers running on the host with real data.

### ✅ New features

A systemd system unit runs a small stdlib relay as root against the real
Docker socket and exposes a socket owned by the operator. Only version,
info, events, container listing, inspect, logs, stats and top are
allowed; every other endpoint and every non-GET verb is refused with
403, and that is not configurable. Projects opt in per repository with
host_api = "read", and the sandbox refuses to start that mode when the
broker is absent rather than proceeding half-configured.

### 💡 Architecture improvements

The relay validates the request line and headers, then splices bytes
without reinterpreting the response, so log following works without this
program needing to understand chunked encoding. Connections are
downgraded to one request each, since a second request on a kept-alive
connection would otherwise pass unvalidated. The script is copied to
/usr/local/lib rather than referenced in the checkout, because a unit
pointing at a working copy breaks silently when the folder moves — the
exact mistake v1 made with its restore unit.

### 🔐 Security & Access Control

Stated plainly in the docs and in the installer's own output: this
grants passwordless read access to Docker for uid 1000. It is a real
privilege increase, small and read-only. The container holding the
socket has no external network, so enabling Docker reading does not also
buy the agent general egress. Mounting the raw socket is not offered at
any setting, since it is host root.

### 🚀 Outcome

All three Docker axes are implemented and independently testable. The
hexmed debugging case works without granting anything that can mutate.
MSG
```

---

## Task 12: The guard

The guard is preserved, not rewritten. Only the hook-path rewriting is removed,
because with identical paths (spec D4) there is nothing left to rewrite.

**Files:**
- Modify: `cli/asb-guard` (drop the rewriting; keep every other behaviour)
- Modify: `cli/asb/install.py` (add `guards`)
- Test: `tests/test-guard.sh` (adapt the existing suite)

**Interfaces:**
- Produces: `install.guards(root) -> int`, creating `~/.local/bin/asb-claude`,
  `asb-codex`, `asb-agy` as symlinks to `cli/asb-guard`.

- [ ] **Step 1: Adapt the existing test**

`tests/test-guard.sh` already covers the three behaviours worth keeping. Keep
its cases and add one:

```bash
# Com caminho identico, o comando de hook do Orca ja e valido dentro do
# container: nao ha home do host a reescrever. Se a reescrita voltasse, ela
# corromperia um caminho que estava correto.
out=$(ASB_SANDBOX_MARKER=/dev/null HOME=/home/qualquer \
  "$ROOT/cli/asb-guard" --help 2>&1 || true)
assert_eq "" "$(printf '%s' "$out" | grep -o 'agent-hooks' || true)" \
  "o guarda nao reescreve mais caminhos de hook"
```

Rename every reference from `cli/asb-agent` to `cli/asb-guard` in that file.

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/test-guard.sh`
Expected: FAIL — the rewriting is still present.

- [ ] **Step 3: Remove the rewriting**

In `cli/asb-guard`, delete the block around the former line 66 that builds
`pattern = re.compile(r"/(?:[^/\s'\"]+/)*\.orca/agent-hooks/")` and its
substitution, plus the call site. Leave untouched:

- the `unset SSH_CONNECTION SSH_CLIENT SSH_TTY` for `agy` alone. Antigravity
  treats an SSH session as a **new remote login**, ignores its cached
  credential and demands device-auth every time; Orca reaches the sandbox over
  SSH, so without this the agent is unusable there. Claude and Codex are fine
  over SSH, which is why the unset is scoped.
- the suppression of the bypass hint when the launch is automatic. The usual
  reader of the refusal is the agent, and an agent in autonomous mode treats
  "call this path" as an instruction — the block would hand over its own
  bypass. TTY detection does not distinguish the cases (Orca uses a PTY); the
  autonomy flag in the arguments and `orca-ide` in the process ancestry do.
- the resolved-real-path comparison for the repository exception, so an agent
  in another project cannot declare itself the exception.

- [ ] **Step 4: Implement `install.guards`**

```python
def guards(root: Path) -> int:
    """Instala os nomes que vao no campo Command do Orca.

    Symlinks para o checkout, nunca copias: uma copia envelhece em silencio e
    o agente passa a se comportar diferente do que este repositorio diz.
    """
    target = Path.home() / ".local" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for agent in ("claude", "codex", "agy"):
        link = target / f"asb-{agent}"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(root / "cli" / "asb-guard")
        print(f"instalado: {link}", file=sys.stderr)
    print("Em Orca -> Settings -> Agents, troque o campo Command:\n"
          "  claude -> asb-claude | codex -> asb-codex | agy -> asb-agy",
          file=sys.stderr)
    return 0
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tests/test-guard.sh && ./cli/asb-agent install-guards`
Expected: PASS, and three symlinks reported.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'MSG'
♻️ drop hook path rewriting from the guard: identical paths

Keeps the guard as it was and removes the one part that identical paths
made unnecessary.

### 💡 Architecture improvements

The guard used to rewrite Orca hook commands from the host home to the
container's, because the two differed. With the container home mirroring
the host's, the injected command is already valid inside the sandbox,
and keeping the rewriting would corrupt a path that was correct.

### 🔐 Security & Access Control

Everything else is preserved deliberately: the SSH variables are still
unset for agy alone, since Antigravity treats an SSH session as a new
remote login and would demand device-auth on every launch, while Claude
and Codex work over SSH unchanged. The bypass hint is still suppressed
for automatic launches, because the usual reader of the refusal is an
agent in autonomous mode, which would treat the real binary path as an
instruction and defeat the block. The repository exception still
compares resolved real paths, so an agent in another project cannot
declare itself the exception.

The guard remains what it always was: protection against accidental
execution outside the sandbox, not containment.

### 🚀 Outcome

install-guards creates the three names Orca's Command field expects, as
symlinks into the checkout so they cannot age out of step with it.
MSG
```

---

## Task 13: `doctor`, `pull` and `purge`

`doctor` is the portability requirement made executable (spec §16.1): it must
name the exact command to run, never "something is wrong".

**Files:**
- Create: `cli/asb/doctor.py`
- Modify: `cli/asb/lifecycle.py` (add `pull`, `purge`)
- Test: `tests/test-doctor.sh`
- Delete: `cli/lib/doctor.sh`

**Interfaces:**
- Produces: `doctor(root) -> int`, `pull(ws) -> int`,
  `purge(ws, confirmed: bool) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test-doctor.sh`:

```bash
#!/usr/bin/env bash
# tests/test-doctor.sh — diagnostico do ambiente.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

echo "== doctor =="
OUT=$("$ROOT/cli/asb-agent" doctor 2>&1); RC=$?

require "doctor produz saida" sh -c '[ -n "'"$(printf %s "$OUT" | head -c 1)"'" ]'

assert_contains "podman" "$OUT" "verifica o podman"
assert_contains "python" "$OUT" "verifica a versao do python"
assert_contains "agent-sandbox:latest" "$OUT" "verifica a imagem base"
assert_contains "asb-credentials" "$OUT" "verifica o volume de credenciais"
assert_contains "podman-restart" "$OUT" "verifica a restauracao no boot"

# Toda falha precisa nomear o comando exato. "algo esta errado" e inutil as 2h
# da manha, e e o requisito da §16.1.
if [ "$RC" -ne 0 ]; then
  assert_contains "asb-agent" "$OUT" "toda falha nomeia um comando a executar"
fi

echo "-- purge exige confirmacao --"
assert_fails "purge sem --yes e recusado" \
  "$ROOT/cli/asb-agent" purge --workspace inexistente

report
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/test-doctor.sh`
Expected: FAIL — `doctor` raises `NotImplementedError`.

- [ ] **Step 3: Implement `doctor`**

Create `cli/asb/doctor.py`:

```python
"""cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao.

Regra: toda linha de falha diz o COMANDO exato a executar. "Algo esta errado"
nao ajuda ninguem as 2h da manha, e a §16.1 exige que uma maquina nova seja
recuperavel sem adivinhacao.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import podman
from .lifecycle import CREDENTIALS_VOLUME, IMAGE, names


def _line(ok: bool, label: str, fix: str = "") -> bool:
    mark = "ok  " if ok else "FALTA"
    print(f"  {mark} {label}" + ("" if ok else f"  ->  {fix}"))
    return ok


def doctor(root: Path) -> int:
    print("agent-sandbox doctor")
    healthy = True

    healthy &= _line(shutil.which("podman") is not None, "podman instalado",
                     "instale o podman (>= 4.0)")
    if shutil.which("podman"):
        version = podman.out("--version").split()[-1]
        major = int(version.split(".")[0])
        healthy &= _line(major >= 4, f"podman {version} (>= 4.0)",
                         "atualize: --internal e resolucao por nome exigem 4+")

    healthy &= _line(sys.version_info >= (3, 11),
                     f"python {sys.version.split()[0]} (>= 3.11)",
                     "tomllib e stdlib so a partir do 3.11")
    healthy &= _line(shutil.which("git") is not None, "git instalado",
                     "instale o git")

    healthy &= _line(podman.exists("image", IMAGE), f"imagem {IMAGE}",
                     "asb-agent build")
    healthy &= _line(podman.exists("volume", CREDENTIALS_VOLUME),
                     f"volume {CREDENTIALS_VOLUME}", "asb-agent login")

    enabled = subprocess.run(
        ["systemctl", "--user", "is-enabled", "podman-restart.service"],
        capture_output=True, text=True).stdout.strip()
    healthy &= _line(enabled == "enabled",
                     "podman-restart.service habilitado (restauracao no boot)",
                     "systemctl --user enable podman-restart.service")

    guards = Path.home() / ".local" / "bin"
    for agent in ("claude", "codex", "agy"):
        link = guards / f"asb-{agent}"
        expected = root / "cli" / "asb-guard"
        # Checkout movido: o link aponta para um caminho que nao existe mais.
        # E o modo de falha da §16.1, e aqui ele e visivel em vez de silencioso.
        healthy &= _line(link.is_symlink() and link.resolve() == expected,
                         f"guarda asb-{agent} aponta para este checkout",
                         "asb-agent install-guards")

    broker = Path("/run/asb-docker/docker.sock")
    _line(broker.is_socket(),
          'broker do Docker (opcional; so para host_api = "read")',
          "asb-agent install-broker")

    print("\nworkspaces:")
    for state in sorted((Path.home() / ".local" / "state" /
                         "agent-sandbox").glob("*/origin")):
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            status = "SEM CONTAINER  ->  asb-agent up"
        elif podman.running(agent):
            status = "rodando"
        else:
            status = f"parado  ->  asb-agent resume --workspace {ws}"
        print(f"  {ws}: {status}")

    return 0 if healthy else 1
```

- [ ] **Step 4: Implement `pull` and `purge`**

Add to `cli/asb/lifecycle.py`:

```python
def pull(ws: str) -> int:
    """Traz o trabalho do workspace para o checkout primario, SEM merge.

    O operador testa e faz o push. Se precisar de ajuste, o workspace continua
    vivo, o agente commita mais, e um novo pull traz a diferenca — e por isso
    que o merge nao acontece aqui.
    """
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    layout = layout_for(origin, ws, home)
    branch = subprocess.run(
        ["git", "-C", str(layout.project_root), "rev-parse",
         "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-C", str(origin), "fetch",
                    str(layout.project_root), f"{branch}:refs/asb/{ws}/{branch}"],
                   check=True)
    print(f"buscado em {origin}: refs/asb/{ws}/{branch}\n"
          f"  revise:  git -C {origin} log refs/asb/{ws}/{branch}\n"
          f"  integre: git -C {origin} merge refs/asb/{ws}/{branch}",
          file=sys.stderr)
    return 0


def purge(ws: str, confirmed: bool) -> int:
    """Remove tambem os ARQUIVOS do workspace. Irreversivel, logo explicito."""
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    layout = layout_for(origin, ws, home)
    if not confirmed:
        raise podman.PodmanError(
            f"purge apaga {layout.mount}, incluindo commits que ainda nao "
            f"voltaram para o host. Rode 'asb-agent pull --workspace {ws}' "
            "antes, e repita com --yes se for isso mesmo.")
    down(ws)
    remove_workspace(layout)
    print(f"removido: {layout.mount}", file=sys.stderr)
    return 0
```

Add `from .workspace import remove_workspace` to the imports.

- [ ] **Step 5: Run the test**

Run: `bash tests/test-doctor.sh`
Expected: PASS.

- [ ] **Step 6: Delete the v1 doctor**

```bash
git rm cli/lib/doctor.sh
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -F - <<'MSG'
✨ diagnose the environment and name the fix: doctor, pull and purge

### ✅ New features

doctor checks podman, its version floor, python, git, the base image,
the credentials volume, boot restore, the guard symlinks and the
optional broker, then lists every workspace with its state. Every
failing line names the exact command that repairs it, because a machine
rebuilt from scratch has to be recoverable without guesswork.

pull fetches the workspace branch into the primary checkout under a
namespaced ref and stops there. No automatic merge: the operator tests
and pushes, and when an adjustment is needed the workspace is still
alive, so the agent commits more and a second pull brings the
difference. That is the flow that used to break halfway through.

### 🧼 Best practices & validations

purge refuses without --yes and says what it would delete, naming pull
as the step to run first. It is the only irreversible command in the
CLI. doctor also verifies that each guard symlink still resolves into
this checkout, which is how a moved folder becomes visible instead of
silently breaking, as it did in v1.

### 🚀 Outcome

A new machine is diagnosable and recoverable from the CLI alone.
cli/lib/doctor.sh is removed.
MSG
```

---

## Task 14: Orca lifecycle hooks

The four hooks Orca's recipe contract requires. `common.sh` keeps deriving the
workspace id in **one** place: in v1 the derivation was duplicated between
`create` and `destroy`, and every divergence leaked a pod.

**Files:**
- Modify: `recipes/common.sh`, `create.sh`, `destroy.sh`, `suspend.sh`,
  `resume.sh`
- Test: `tests/test-recipe.sh`

**Interfaces:**
- Consumes: the CLI's JSON output from `up` and `resume`.
- Produces: the Orca recipe JSON (`schemaVersion`, `connection.target`,
  `projectRoot`).

- [ ] **Step 1: Adapt the test**

Keep `tests/test-recipe.sh`'s existing assertions — including the one that
fails if any hook redefines the workspace-id derivation — and add:

```bash
# O projectRoot vem do CLI, nao e montado no shell: e ele que decide onde a
# worktree irma do Orca vai cair, e um valor divergente coloca o trabalho do
# agente fora do que o host enxerga.
json=$(ORCA_VM_INSTANCE_ID="recipe-check-$$" "$ROOT/recipes/create.sh" "$REPO")
root=$(printf '%s' "$json" | jq -r .connection.projectRoot)
assert_contains "$HOME/asb-agent" "$root" \
  "o projectRoot esta sob ~/asb-agent, visivel no host"
assert_eq "1" "$(printf '%s' "$json" | jq -r '.schemaVersion')" \
  "schemaVersion e 1"
ORCA_VM_INSTANCE_ID="recipe-check-$$" "$ROOT/recipes/destroy.sh" "$REPO"
assert_eq "1" "$(podman container exists asb-recipe-check-$$-agent; echo $?)" \
  "destroy nao deixa container para tras"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/test-recipe.sh`
Expected: FAIL — the hooks still call the removed `cli/agent-sandbox`.

- [ ] **Step 3: Update the hooks**

`recipes/common.sh` keeps `asb_workspace_id` exactly as it is (it already
matches `workspace.workspace_id`; a test in Task 2 pins the Python side, and
this one pins the shell side). Change only `asb_recipe_json` to take the
project root from the CLI rather than hardcoding it:

```bash
# Resultado que o Orca consome. create e resume emitem a MESMA forma: o resume
# tambem devolve a conexao, porque a porta pode ter mudado.
asb_recipe_json() {
  local ws="$1" port="$2" project_root="$3"
  local key="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519"
  jq -nc \
    --arg label "agent-sandbox-$ws" \
    --arg ws "$ws" \
    --arg key "$key" \
    --arg root "$project_root" \
    --arg user "$(id -un)" \
    --argjson port "$port" '
  {
    schemaVersion: 1,
    userData: { workspace: $ws },
    connection: {
      type: "ssh",
      projectRoot: $root,
      target: {
        label: $label,
        host: "127.0.0.1",
        port: $port,
        username: $user,
        identityFile: $key,
        identitiesOnly: true
      }
    }
  }'
}
```

`recipes/create.sh`:

```bash
#!/usr/bin/env bash
# recipes/create.sh — contrato de ciclo de vida do Orca (modo SSH).
# Roda NO HOST, a partir da raiz do repo do projeto.
# Imprime UMA linha JSON no stdout. Todo o resto vai para stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/recipes/common.sh"
repo="${1:-$PWD}"

ws=$(asb_workspace_id "$repo")
out=$("$ROOT/cli/asb-agent" up --workspace "$ws" --repo "$repo")
asb_recipe_json "$ws" \
  "$(printf '%s' "$out" | jq -r .port)" \
  "$(printf '%s' "$out" | jq -r .project_root)"
```

`recipes/resume.sh` is identical with `resume` in place of `up` and no
`--repo`. `recipes/suspend.sh` calls `suspend`. `recipes/destroy.sh` calls
`down` — **never `purge`**: Orca destroys a workspace when the operator closes
it, and the agent's commits may not have been pulled yet.

- [ ] **Step 4: Run the test**

Run: `bash tests/test-recipe.sh`
Expected: PASS.

- [ ] **Step 5: Verify against Orca once, by hand**

```bash
orca vm recipe doctor --provision      # a partir de um projeto consumidor
podman ps --filter name=asb-           # nao pode sobrar nada depois
```

Remember the two reasons a recipe does not appear in the picker, in order of
likelihood: **Settings → Experimental → "Cloud VM"** is off, and `orca.yaml` is
not committed on the project's **primary branch** (an untracked file does not
count, even though `doctor` validates it fine from the working copy).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -F - <<'MSG'
🔧 point the Orca hooks at the new CLI: recipe contract

### 💡 Architecture improvements

The four hooks now call asb-agent, and projectRoot comes from the CLI's
own output rather than being hardcoded in the shell. It is the value
that decides where Orca puts its sibling worktree, so a divergent copy
would place the agent's work outside what the host can see — the problem
this rebuild set out to fix.

The workspace-id derivation stays in common.sh alone, and the suite
still fails if any hook redefines it. In v1 that derivation was
duplicated between create and destroy, and every divergence leaked a
pod while Orca reported success.

### 🧼 Best practices & validations

destroy calls down, never purge. Orca destroys a workspace when the
operator closes it, and the agent's commits may not have been pulled
back yet; deleting them on a routine close would be irreversible.

### 🚀 Outcome

The recipe contract works end to end and destroy leaves nothing behind.
MSG
```

---

## Task 15: Documentation and final sweep

Closes the operator's problem #4. The v1 has eight documents written as an
excavation record: each explains why one bug happened, none explains the
system. What cannot be read cannot be maintained.

**Files:**
- Create: `docs/domains/sandbox/README.md`, `configuration.md`, `security.md`,
  `failure-modes.md`
- Modify: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` (if they reference removed
  paths)
- Delete: the eight v1 sandbox documents

- [ ] **Step 1: Write `README.md` — the system in one page**

It must answer, without depending on the other three: what each container does,
what each command does, where files live, and what to do when something does
not come up. Include the topology diagram from spec §4.1 and this table:

| Comando | O que faz |
| :--- | :--- |
| `build` | constroi a imagem base espelhando seu usuario |
| `login` | autentica os tres agentes; **uma vez por maquina** |
| `up` | cria rede, clone e containers; imprime a conexao |
| `resume` | religa (`podman start`); depois de reboot e automatico |
| `pull` | traz o branch do workspace para o checkout primario |
| `down` | remove containers e rede; **preserva seus arquivos** |
| `purge` | remove tambem os arquivos; exige `--yes` |
| `doctor` | diz o que falta e o comando exato para corrigir |

- [ ] **Step 2: Write `configuration.md`**

The complete `.agent-sandbox.toml` reference. Copy spec §17 verbatim as the
skeleton, then add a worked example for each of the operator's two real cases:
hexmed (`host_ports` plus `host_api = "read"`) and BlackICE (`mode =
"nested"`).

- [ ] **Step 3: Write `security.md`**

Spec §9 restated for a reader who is deciding what to switch on. It must state
plainly, not in a footnote: exfiltration to an allowed domain is possible;
`host_api = "read"` grants passwordless Docker reading to uid 1000; `mode =
"nested"` gives the agent a full container runtime inside the boundary; the
guard is not containment.

- [ ] **Step 4: Write `failure-modes.md`**

Consolidate the forensic content of the eight v1 documents into one file, and
keep every entry in spec §15. Each entry: symptom, cause, fix. Drop anything
that describes v1 machinery which no longer exists (the nftables ruleset, the
init container, the ordered resume, the provisioning token), since a fix for a
component that is gone is noise that costs the next reader time.

- [ ] **Step 5: Dispose of the v1 test suites**

Six suites from v1 are not referenced by any task. Each gets an explicit
decision rather than being left to rot:

| Suite v1 | Decisao |
| :--- | :--- |
| `test-profile.sh` | **delete** — replaced by `tests/unit/test_profile.py` (Task 1), which covers strictly more |
| `test-resume.sh` | **delete** — replaced by `tests/test-lifecycle.sh` (Task 6) |
| `test-readiness.sh` | **delete** — it asserted the v1 proxy-readiness gating, and the ordering it guarded no longer exists |
| `test-attached.sh` | **delete** — replaced by `tests/test-services.sh` (Task 9). It never ran end to end in v1: it skipped whenever nothing was listening on the host port, which was every run |
| `test-transaction.sh` | **adapt and keep** — it asserts that a failed `up` leaves nothing behind, which is exactly what `_sweep_containers` now guarantees. Point it at the new CLI and assert no `asb-<ws>-*` container and no `asb-<ws>` network survive a forced failure |
| `test-agents-behind-proxy.sh` | **adapt and keep** — the only end-to-end proof that the three agents actually work through the proxy while authenticated. Point it at the new container names and run it after `login` |

```bash
git rm tests/test-profile.sh tests/test-resume.sh \
       tests/test-readiness.sh tests/test-attached.sh
```

- [ ] **Step 6: Delete the v1 documents**

```bash
git rm docs/domains/sandbox/architecture.md \
       docs/domains/sandbox/lifecycle.md \
       docs/domains/sandbox/network.md \
       docs/domains/sandbox/enforcement.md \
       docs/domains/sandbox/authentication.md \
       docs/domains/sandbox/credentials.md \
       docs/domains/sandbox/troubleshooting.md \
       docs/domains/sandbox/hexmed-notes.md
```

- [ ] **Step 7: Verify no reference points at a deleted path**

Run: `grep -rn "agent-sandbox up\|cli/lib/\|agent-sandbox-auth\|install-autostart\|restore-all\|/home/agent" --include="*.md" --include="*.sh" --include="*.py" --include="*.toml" . | grep -v docs/superpowers/`
Expected: no output. Every hit is a document or script still describing the
system that no longer exists.

- [ ] **Step 8: Run everything**

```bash
python3 -m unittest discover -s tests/unit -v
for t in tests/test-*.sh; do echo "== $t"; bash "$t" || echo "FALHOU: $t"; done
./cli/asb-agent doctor
```

Expected: every suite green, `doctor` exiting 0. Record the actual output in
the commit body — evidence precedes assertions of completion.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -F - <<'MSG'
📝 document the system instead of its excavation: sandbox domain pack

Replaces eight documents written as a record of individual bugs with
four written for someone maintaining the system.

### 💡 Architecture improvements

README.md answers, without depending on the others, what each container
does, what each command does, where files live and what to do when
something does not come up. configuration.md is the complete profile
reference with a worked example for each of the two real projects.
security.md states the boundaries and, plainly rather than in a
footnote, what they do not protect. failure-modes.md keeps the forensic
record in one place.

Entries describing v1 machinery that no longer exists were dropped
rather than carried forward. A fix for a component that is gone is noise
that costs the next reader time.

### 🚀 Outcome

Full suite green and doctor exits 0. The v2 sandbox is complete: one
lifecycle path, isolation that cannot fail to be applied, one login per
machine, workspaces visible to host tooling, and three independent
Docker axes that are closed by default.
MSG
```

---

## Self-Review

Run after the plan is written, before execution starts.

**Spec coverage.** Every numbered section maps to a task: §4 → Tasks 5–6;
§5 → Task 2; §6.1–6.2 → Tasks 9–10; §6.3 → Task 11; §7.1 → Task 8;
§7.2 → Task 7; §7.3 → Tasks 8, 12; §8 → Task 10 (mise cache volume) and Task 15
(documented); §9 → asserted across Tasks 5, 7, 10, 11; §10 → Task 15;
§11 → Tasks 4, 13; §12 → every task; §13 → deletions distributed across the
tasks that replace each file; §15 → Global Constraints plus Task 15;
§16 → Tasks 4, 11, 13; §17 → Tasks 1, 15.

**Verified before writing.** Code in Tasks 1, 2, 3, 7 was extracted from this
plan and executed: 52 unit tests pass. The broker filter in Task 11 was
executed against 13 cases including path traversal: all correct. The podman
behaviour in Tasks 5, 6, 9, 10 was measured directly on this host and the
measurements are quoted in the tasks that depend on them.

**Found during this review, and fixed in the plan.** `up` had no rollback, so
a failure partway through would leave containers and networks behind and the
retry would then fail with "workspace already exists" for no visible reason —
v1 had a cleanup trap and the first draft lost it. Task 5 now wraps `up` and
sweeps by container prefix. Six v1 test suites were unreferenced; Task 15 gives
each an explicit decision, keeping the two that still earn their place
(`test-transaction.sh`, which asserts a failed `up` leaves nothing, and
`test-agents-behind-proxy.sh`, the only end-to-end proof that the three agents
work through the proxy).

**Known open risk.** Task 10 carries the only unresolved one: nested podman
worked under the reference image with the exact flags this design uses, but a
naive Debian build failed on `newuidmap`. Step 3 carries the configuration that
closes the gap and Step 5 names the fallback. Do not mark Task 10 complete on a
passing build alone — the test must run a nested container.
