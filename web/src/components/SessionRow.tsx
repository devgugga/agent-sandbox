// SessionRow — a leaf row for one agent session (spec §9.2, §9.4). Mirrors
// the fields `tui_model.build_tree` puts on a session line (agent, state,
// title); the exact "agent  state  title" concatenation is a curses
// rendering detail, not one of the mandated labels, so this
// renders the same three fields as separate, styled pieces instead.
import type { SessionNode } from "../types/tree";

export interface SessionRowProps {
  session: SessionNode;
  depth: number;
  selected: boolean;
  onSelect: () => void;
}

export function SessionRow({ session, depth, selected, onSelect }: SessionRowProps) {
  return (
    <li
      role="treeitem"
      aria-selected={selected}
      data-depth={depth}
      style={{ paddingLeft: depth * 16 }}
      className={`flex cursor-pointer items-center gap-2 px-2 py-1 text-sm ${
        selected ? "bg-surface-raised" : "hover:bg-surface-raised/60"
      }`}
      onClick={onSelect}
    >
      <span className="text-fg-muted">{session.agent}</span>
      <span className="text-fg-muted">{session.state}</span>
      <span className="truncate text-fg">{session.title}</span>
    </li>
  );
}
