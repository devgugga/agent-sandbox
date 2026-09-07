# Review Domain Pack

Canonical rules for the read-only review roles that inspect a diff before it
is accepted. These roles are **narrow by design**: each answers one question
that general code review reliably misses.

| Document | Role that consumes it | Question it answers |
| :--- | :--- | :--- |
| [`test-shape.md`](./test-shape.md) | `test-shape-auditor` | Does a test actually enter each new branch? |
| [`claim-verification.md`](./claim-verification.md) | `claim-verifier` | Is every factual claim in the report true of the code? |
| [`../sandbox/known-regressions.md`](../sandbox/known-regressions.md) | `regression-sentinel` | Does this diff reintroduce a defect we already fixed? |

These roles never replace the task review or the whole-branch review. They add
a specific check that a general reviewer, reading for correctness and quality,
does not systematically perform.

All three are **read-only**. They never modify the working tree, the index,
HEAD, or branch state, and they never dispatch subagents.
