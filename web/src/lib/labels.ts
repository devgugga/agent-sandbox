// Label rules mirroring `cli/asb/interfaces/tui_model.py` (spec §9.2).
// Every string this module can produce is copied verbatim
// from `_branch_label`, `_status_label`, `_checkout_text` and
// `_unregistered_text` there — this file is the front end's single source
// for the eight mandated labels, so no component builds label text inline.
import type { WorkspaceStatus } from "../types/tree";

// `tui_model.MERGED_LABEL` / `PENDING_LABEL` — literal constants there.
export const MERGED_LABEL = "merged / cleanup available";
export const PENDING_LABEL = "merged / cleanup pending";
export const UNREGISTERED_LABEL = "unregistered";
export const PRUNABLE_LABEL = "prunable";
export const MISSING_LABEL = "missing";

/** `_branch_label` (tui_model.py). Unknown branch, detached and host-read
 * status are folded into one string; `(host)` is appended, never combined
 * differently. */
export function branchLabel(
  branch: string | null,
  detached: boolean,
  hostBranch: boolean,
): string {
  let label: string;
  if (branch === null) {
    label = "(branch ?)";
  } else if (detached) {
    label = `(detached ${branch})`;
  } else {
    label = branch;
  }
  return hostBranch ? `${label} (host)` : label;
}

/** `_status_label` (tui_model.py). `str(status)` for a `StrEnum` is the
 * enum's own value, which is exactly the wire string this function
 * receives, so the "else" branch is a no-op pass-through, not a guess. */
export function statusLabel(status: WorkspaceStatus, reason: string | null): string {
  if (status === "unavailable" && reason) {
    return `unavailable: ${reason}`;
  }
  return status;
}

/** `_checkout_text` (tui_model.py): `missing` and the merged label are
 * independent flags on the same row, not alternatives — a checkout can be
 * both `missing` and `merged / cleanup pending` at once (the fixture's
 * `c-merged-pending` is exactly that case). This function returns only the
 * merged half; the caller renders `missing` separately whenever
 * `checkout.missing` is true, regardless of `merged`. */
export function mergedLabel(missing: boolean, merged: boolean): string | null {
  if (!merged) return null;
  return missing ? PENDING_LABEL : MERGED_LABEL;
}

/** `!! <error>` suffix shared by checkout and project rows. */
export function errorLabel(error: string | null): string | null {
  return error ? `!! ${error}` : null;
}
