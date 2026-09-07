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

## Cross-Platform Tier Equivalence

Equivalent tiers across the three supported platforms. Route by **tier**, then
translate to the platform's identifier — never guess an identifier from another
platform's naming.

| Tier | Claude Code | OpenAI Codex | Antigravity |
| :--- | :--- | :--- | :--- |
| Frontier | `fable` (Fable 5.1) | `gpt-6-astra` | `pro` |
| High capability | `opus` (Opus 5) | `gpt-5.6-sol` | `pro` |
| Balanced | `sonnet` (Sonnet 5) | `gpt-5.6-terra` | `flash` / `inherit` |
| Lightweight | `haiku` (Haiku 4.5) | `gpt-5.6-luna` | `flash_lite` |

Codex additionally takes `model_reasoning_effort`; raise the effort before
raising the tier, since effort is the cheaper lever.

Reserve the Frontier and High capability rows for the workloads §Workload
Classification calls Complex / High Risk. A reviewer role reading a bounded
document against a diff is Balanced work, not high-capability work.
