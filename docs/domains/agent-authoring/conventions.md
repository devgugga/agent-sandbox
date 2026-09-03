# Agent Authoring Conventions

## 1. Architecture Boundaries

* **Domain Pack (`docs/domains/<domain>/`):** Canonical, tool-agnostic domain knowledge and policies in neutral Markdown. Single Source of Truth (SSoT).
* **Skill:** Repeatable workflow running inside the main agent context; drives interactive, multi-step procedures.
* **Subagent:** Isolated role with recurring responsibility, focused context, and minimal tool permissions. Never create a subagent simply to run a single skill when isolated context is unnecessary.

## 2. Single Source of Truth (SSoT)

1. Create or update domain knowledge under `docs/domains/<domain>/` before authoring tool-specific wrappers.
2. Instruct the agent or skill prompt to read the canonical markdown documents; **never duplicate domain rules or conventions inside prompts**.
3. Keep inside the wrapper strictly tool-specific configurations: identifier, trigger description, model routing, tools, and permissions.
4. When correcting a rule, edit the canonical markdown file once; all agents inherit the fix immediately.

## 3. Scope and Authorization

Before creating or editing an agent, specify its role, triggers, required tools, and potential side effects. Creating or modifying an agent does not authorize product code changes, branch creation, or commits without explicit permission.
