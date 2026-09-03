# Model Selection & Routing

## Core Principle

For every created or modified agent, select the **lowest-cost eligible model or tier** capable of executing the task reliably. Higher tiers require objective technical justification.

## Workload Classification

1. **Simple / Mechanical:** Repetitive transformations, documentation formatting, structured lookups, commit curation.
   * *Recommendation:* Lightweight tiers (`flash` in Antigravity, `haiku` in Claude, `luna` in Codex).
2. **Routine / Standard:** Standard feature implementation, isolated bugfixes with explicit test coverage.
   * *Recommendation:* Balanced intermediate models (`flash` or `inherit` / `sonnet`).
3. **Complex / High Risk:** Multi-step refactors, architectural changes, security, or domain-critical invariants.
   * *Recommendation:* Higher tiers (`pro`, reasoning models), always subject to human gates.

## Escalation Governance

Never alter an existing agent's model tier without explicit authorization or demonstrated evidence of task failure on the lighter tier.
