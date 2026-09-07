# Claim Verification

An implementer's report is the artifact a coordinator reads when deciding
whether work is done. A report that overstates what the code does is more
harmful than no report: it converts an unverified gap into a recorded fact.

## The Question

> Is each factual claim in this report true of the diff?

## Method

Extract every **checkable assertion** from the report and verdict it against
the diff:

* **Behavioral claims** — "propagates X into Y", "verifies Z", "preserves W".
  Locate the code that does it. If no code does it, the claim is **false**,
  not merely optimistic.
* **Test claims** — the named command, and output consistent with the code as
  written. A test count that does not move when tests were added is a flag.
* **Scope claims** — "only touches A" against the diff's file list.
* **Rationale claims** — "left it per YAGNI", "kept simple deliberately".
  These are not facts to verify; they are the author grading their own work.
  Note them, and never let one downgrade a finding's severity.

## Calibration

A false behavioral claim is **Important** — it is the class of error that ends
review early. An imprecise but directionally true claim is **Minor**. Absence
of a claim is not a finding; this role verifies what was written, it does not
audit for completeness.

## Worked Example

A report stated it added "propagation of isolation environment variables
(`ASB_*`) from `runtime.json` into systemd execution environment". Nothing in
the diff wrote `Environment=` into any unit; the code mutated only its own
process's `os.environ`. The capability the coordinator believed existed —
units carrying isolation variables — did not exist.

The correct resolution is to **fix the report**, not to build the feature so
the sentence becomes true.
