# Enforcement

## The problem

Orca launches every supported agent with its full-autonomy flag pre-applied —
Claude with `--dangerously-skip-permissions`, Codex with
`--dangerously-bypass-approvals-and-sandbox`, Antigravity with
`--dangerously-skip-permissions`. It offers **no setting that requires** a
workspace to use an environment recipe. Building the sandbox therefore creates
an option, not an obligation, and an option nobody is forced to take does not
protect the host.

## The mechanism: `Command` override

Orca's **Settings → Agents** exposes a per-agent `Command` field, documented as
*"Override the binary path or name"*. That is the supported interception point,
and it is a persisted setting rather than a file that gets regenerated.

Set the field to the guard instead of the binary:

| Agent | Command | Arguments |
| :--- | :--- | :--- |
| Claude | `asb-claude` | unchanged |
| Codex | `asb-codex` | unchanged |
| Antigravity | `asb-agy` | unchanged |

Install the host side with `agent-sandbox install-guards`. The same guard is
baked into the image, because the `Command` setting is global and applies to the
SSH session inside the recipe container too.

## How the guard decides

`cli/asb-agent` is installed under three names and infers the agent from its
invocation name.

1. **Inside the sandbox** — marker `/etc/agent-sandbox-release` present: it
   `exec`s the real binary, transparently.
2. **Host, inside the `agent-sandbox` repository** — allowed. Maintaining the
   sandbox requires podman on the host; a blanket block makes this repository
   unmaintainable. The comparison uses the resolved real path, so an agent in
   another project cannot declare itself the exception.
3. **Host, anywhere else** — refused, exit 77, with instructions.

### The bypass hint is hidden from agents

The refusal message names the real binary path so a human can override
deliberately. That hint is suppressed when the launch is automatic, because the
usual reader of the message is the agent — and an agent in yolo mode treats
"call this path" as an instruction, which would make the block hand over its own
bypass.

TTY detection does **not** distinguish the two: Orca launches agents in a PTY.
What distinguishes them is the presence of an autonomy flag in the arguments
(Orca always applies one) and `orca-ide` in the process ancestry.

## This is not a security boundary

Anyone who knows the real binary path bypasses the guard in one command. It
addresses **accidental** execution outside the sandbox, which is the actual
failure mode: an agent in yolo mode reads "blocked" and stops rather than
hunting for a hidden binary. Do not describe it as containment.

## Prerequisite: the experimental flag

Recipes only appear as **Run on** targets when **Settings → Experimental →
"Cloud VM"** is enabled. Without it the picker is not rendered at all and a
perfectly valid recipe is invisible. A recipe that does not show up is far more
likely to be this flag than a problem with `orca.yaml`.
