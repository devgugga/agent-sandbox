# Test Shape

General review asks "are there tests?" and coverage tools ask "was this line
executed?". Both answered **yes** for defects that shipped anyway. This
document defines the question that catches them.

## The Question

> For every conditional branch the diff introduces or changes, name the test
> that **enters** that branch, and the input that takes it there.

A branch with no such test is a finding, even at 100% line coverage — the line
can be executed through the other side of the condition.

## Why: three defects that passed review

1. **`Profile(host_ports=[])` in every test.** The forwarder branch was only
   ever reached with an empty list, so an unassigned name inside
   `if profile.host_ports and fwd_cid:` raised `NameError` for every real
   profile. The forwarder *was* tested — in isolation, through a different
   entry point that never touched the broken code.
2. **`install_workspace` mocked to return `[]`.** The unit-rollback branch
   guarded by `if self.created_units:` could never execute, so a silently
   swallowed exception inside it was invisible in tests and in production.
3. **`--restart=no` and corrupt-manifest paths.** Both were new branches whose
   only tests took the other side of the condition.

## What to Report

For each new or changed conditional:

* **Covered** — name the test and the input that enters the branch.
* **Not covered** — state the branch, the input that would enter it, and what
  the branch does that nothing verifies. This is an Important finding when the
  branch has side effects (creates, deletes, or reports state), Minor when it
  only formats output.

## Adjacent Checks

* **Isolation-only testing.** A helper tested through its own entry point but
  never through the caller that uses it in production is a gap; the
  integration path is where the arguments are actually assembled.
* **Unasserted mocks.** A `patch` with no `assert_called*` verifies nothing and
  actively hides deleted call sites — see `known-regressions.md` R7.
* **Assertions on mocks instead of behavior.** A test that only asserts a mock
  was called with certain arguments verifies the test's own wiring.
