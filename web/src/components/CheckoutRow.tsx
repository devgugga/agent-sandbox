// CheckoutRow — a checkout or an unregistered worktree (spec §9.2, §9.4).
// Renders the label vocabulary from `lib/labels.ts`, which mirrors
// `cli/asb/interfaces/tui_model.py` verbatim (amendment §B): every string
// a viewer can read off this row for a checkout's branch, status, merge
// state and error, and for an unregistered worktree's branch, "unregistered"
// and "prunable", is exactly what the curses TUI would show for the same
// node.
import type { ReactNode } from "react";
import {
  MISSING_LABEL,
  PRUNABLE_LABEL,
  UNREGISTERED_LABEL,
  branchLabel,
  errorLabel,
  mergedLabel,
  statusLabel,
} from "../lib/labels";
import type { CheckoutNode, UnregisteredNode } from "../types/tree";

export type CheckoutRowNode =
  | { kind: "checkout"; checkout: CheckoutNode }
  | { kind: "unregistered"; unregistered: UnregisteredNode };

export interface CheckoutRowProps {
  node: CheckoutRowNode;
  depth: number;
  /** Ignored for `unregistered` — those rows never fold. */
  expanded: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggleFold: () => void;
}

function Badge({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "danger";
}) {
  const toneClass = tone === "danger" ? "text-danger" : "text-fg-muted";
  return <span className={`text-xs ${toneClass}`}>{children}</span>;
}

export function CheckoutRow({
  node,
  depth,
  expanded,
  selected,
  onSelect,
  onToggleFold,
}: CheckoutRowProps) {
  const foldable = node.kind === "checkout";

  return (
    <li
      role="treeitem"
      aria-selected={selected}
      aria-expanded={foldable ? expanded : undefined}
      data-depth={depth}
      style={{ paddingLeft: depth * 16 }}
      className={`flex cursor-pointer flex-wrap items-center gap-2 px-2 py-1 text-sm ${
        selected ? "bg-surface-raised" : "hover:bg-surface-raised/60"
      }`}
      onClick={onSelect}
    >
      {foldable ? (
        <button
          type="button"
          aria-label={expanded ? "Collapse" : "Expand"}
          onClick={(event) => {
            event.stopPropagation();
            onToggleFold();
          }}
          className="w-4 text-fg-muted"
        >
          {expanded ? "-" : "+"}
        </button>
      ) : (
        <span className="w-4" />
      )}

      {node.kind === "checkout" ? (
        <CheckoutFields checkout={node.checkout} />
      ) : (
        <UnregisteredFields unregistered={node.unregistered} />
      )}
    </li>
  );
}

function CheckoutFields({ checkout }: { checkout: CheckoutNode }) {
  const merged = mergedLabel(checkout.missing, checkout.merged);
  const error = errorLabel(checkout.error);
  return (
    <>
      <Badge>[{checkout.kind}]</Badge>
      <span className="text-fg">
        {branchLabel(checkout.branch, checkout.detached, checkout.host_branch)}
      </span>
      <Badge>{statusLabel(checkout.status, checkout.reason)}</Badge>
      {checkout.kind === "worktree" && <Badge>{checkout.path}</Badge>}
      {checkout.missing && <Badge>{MISSING_LABEL}</Badge>}
      {merged && <Badge>{merged}</Badge>}
      {error && <Badge tone="danger">{error}</Badge>}
    </>
  );
}

function UnregisteredFields({ unregistered }: { unregistered: UnregisteredNode }) {
  return (
    <>
      <Badge>[worktree]</Badge>
      <span className="text-fg">
        {branchLabel(unregistered.branch, unregistered.detached, false)}
      </span>
      <Badge>{UNREGISTERED_LABEL}</Badge>
      <Badge>{unregistered.path}</Badge>
      {unregistered.missing && <Badge>{MISSING_LABEL}</Badge>}
      {unregistered.prunable && <Badge>{PRUNABLE_LABEL}</Badge>}
    </>
  );
}
