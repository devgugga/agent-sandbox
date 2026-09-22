// Direct evidence for the eight labels spec §9.2 mandates
// verbatim, independent of any DOM rendering. Each case here is a rule
// from `cli/asb/interfaces/tui_model.py`'s `_branch_label`, `_status_label`,
// and the merged/error suffixes `_checkout_text` builds.
import { describe, expect, it } from "vitest";
import { branchLabel, errorLabel, mergedLabel, statusLabel } from "./labels";

describe("branchLabel", () => {
  it("renders a plain branch name", () => {
    expect(branchLabel("main", false, false)).toBe("main");
  });

  it("renders '(detached <branch>)' for a detached HEAD", () => {
    expect(branchLabel("main", true, false)).toBe("(detached main)");
  });

  it("renders '(branch ?)' when the branch is unknown", () => {
    expect(branchLabel(null, false, false)).toBe("(branch ?)");
  });

  it("appends '(host)' when read from the operator's checkout", () => {
    expect(branchLabel("main", false, true)).toBe("main (host)");
  });

  it("combines detached and host into one string, in that order", () => {
    // The fixture's docs-site primary checkout: detached=true, host_branch=true.
    expect(branchLabel("main", true, true)).toBe("(detached main) (host)");
  });
});

describe("statusLabel", () => {
  it("passes ready and absent through unchanged", () => {
    expect(statusLabel("ready", null)).toBe("ready");
    expect(statusLabel("absent", null)).toBe("absent");
  });

  it("prefixes an unavailable reason", () => {
    expect(statusLabel("unavailable", "podman down")).toBe("unavailable: podman down");
  });

  it("falls back to the bare status when unavailable has no reason", () => {
    expect(statusLabel("unavailable", null)).toBe("unavailable");
  });
});

describe("mergedLabel", () => {
  it("returns null when not merged", () => {
    expect(mergedLabel(false, false)).toBeNull();
    expect(mergedLabel(true, false)).toBeNull();
  });

  it("returns the 'available' label when merged and present", () => {
    expect(mergedLabel(false, true)).toBe("merged / cleanup available");
  });

  it("returns the 'pending' label when merged and missing", () => {
    expect(mergedLabel(true, true)).toBe("merged / cleanup pending");
  });
});

describe("errorLabel", () => {
  it("returns null for no error", () => {
    expect(errorLabel(null)).toBeNull();
  });

  it("prefixes with '!! '", () => {
    expect(errorLabel("reconcile failed")).toBe("!! reconcile failed");
  });
});
