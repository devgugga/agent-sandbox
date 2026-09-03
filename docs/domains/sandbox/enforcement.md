# Sandbox Enforcement & Boundary Limitations

## 1. Investigation Findings

An investigation of Orca CLI commands and schema (`orca agent-context --json`) reveals the current orchestration model:

- `environmentRecipes` declared in `orca.yaml` registers alternative runtime environments (such as `agent-sandbox`).
- When creating worktrees via the Orca UI, the recipe appears as an option in the environment selector dropdown (provided `orca.yaml` resides on the primary branch of the primary checkout).
- From the CLI, `--environment` can target specific environments.

## 2. Hard Enforcement Limitations

> [!WARNING]
> **Orca does not currently support mandatory repository-level recipe enforcement.**

- **Opt-In Model**: Launching workspaces inside `agent-sandbox` is currently **opt-in**.
- **No Local Disabling**: There is no native Orca setting to disable raw host agent execution for a specific repository. If an operator starts an agent directly on the host (e.g. without selecting the "Agent Sandbox" recipe), the agent runs directly with host privileges.
- **Operator Discipline**: Real-world containment depends entirely on the operator consistently selecting the `Agent Sandbox` recipe when creating workspaces.

## 3. Mitigation & Recommendations

1. **Keep `orca.yaml` on `main`**: Ensure `orca.yaml` is merged to the primary branch so the recipe is always presented prominently in the workspace creator UI.
2. **Setup Hooks Warning**: In repositories where sandbox execution is required, add a pre-execution check in repository setup scripts (`orca.yaml` setup hooks) that warns or aborts if executed directly on the host without `ASB_CONTAINER=1` or inside the sandbox namespace.
