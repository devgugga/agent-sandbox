// ProjectTree — project → checkouts → sessions, plus unregistered
// worktrees (spec §9.2, §9.3, §9.4). Owns the tree's own keyboard
// navigation: arrows move the selection among the currently visible rows,
// Enter folds/unfolds a project or checkout, or selects a session (spec
// §9.3). `Ctrl+K` and `Alt+R` are handled above this component (`App`),
// since they are not tree-scoped.
import { useEffect, useMemo, useRef, type KeyboardEvent } from "react";
import { CheckoutRow } from "./CheckoutRow";
import { SessionRow } from "./SessionRow";
import { errorLabel } from "../lib/labels";
import { buildRows, isFoldable, visibleRows, type Row } from "../lib/tree";
import type { ProjectNode } from "../types/tree";

export interface ProjectTreeProps {
  projects: readonly ProjectNode[];
  collapsed: ReadonlySet<string>;
  selectedKey: string | null;
  onSelectRow: (key: string) => void;
  onToggleFold: (key: string) => void;
}

export function ProjectTree({
  projects,
  collapsed,
  selectedKey,
  onSelectRow,
  onToggleFold,
}: ProjectTreeProps) {
  const rows = useMemo(() => buildRows(projects), [projects]);
  const visible = useMemo(() => visibleRows(rows, collapsed), [rows, collapsed]);
  const containerRef = useRef<HTMLUListElement>(null);

  // Focus the tree on first mount so arrow keys work without a prior click
  // — a keyboard-only operator should not need the mouse just to start.
  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (visible.length === 0) return;
      const idx = visible.findIndex((row) => row.key === selectedKey);
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const nextIdx =
        idx === -1
          ? event.key === "ArrowDown"
            ? 0
            : visible.length - 1
          : Math.min(Math.max(idx + delta, 0), visible.length - 1);
      onSelectRow(visible[nextIdx].key);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const current = visible.find((row) => row.key === selectedKey);
      if (!current) return;
      if (isFoldable(current)) {
        onToggleFold(current.key);
      } else {
        // Session or unregistered worktree: Enter confirms the cursor row
        // as the selection (spec §9.3 — "select a session").
        onSelectRow(current.key);
      }
    }
  }

  if (visible.length === 0) {
    return <p className="px-4 py-2 text-sm text-fg-muted">No projects.</p>;
  }

  return (
    <ul
      ref={containerRef}
      role="tree"
      aria-label="Projects"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className="h-full overflow-y-auto outline-none"
    >
      {visible.map((row) => renderRow(row, collapsed, selectedKey, onSelectRow, onToggleFold))}
    </ul>
  );
}

function renderRow(
  row: Row,
  collapsed: ReadonlySet<string>,
  selectedKey: string | null,
  onSelectRow: (key: string) => void,
  onToggleFold: (key: string) => void,
) {
  const selected = row.key === selectedKey;

  switch (row.kind) {
    case "project":
      return (
        <ProjectRow
          key={row.key}
          project={row.project}
          expanded={!collapsed.has(row.key)}
          selected={selected}
          onSelect={() => onSelectRow(row.key)}
          onToggleFold={() => onToggleFold(row.key)}
        />
      );
    case "checkout":
      return (
        <CheckoutRow
          key={row.key}
          node={{ kind: "checkout", checkout: row.checkout }}
          depth={1}
          expanded={!collapsed.has(row.key)}
          selected={selected}
          onSelect={() => onSelectRow(row.key)}
          onToggleFold={() => onToggleFold(row.key)}
        />
      );
    case "unregistered":
      return (
        <CheckoutRow
          key={row.key}
          node={{ kind: "unregistered", unregistered: row.unregistered }}
          depth={1}
          expanded={false}
          selected={selected}
          onSelect={() => onSelectRow(row.key)}
          onToggleFold={() => {
            /* unregistered worktrees never fold */
          }}
        />
      );
    case "session":
      return (
        <SessionRow
          key={row.key}
          session={row.session}
          depth={2}
          selected={selected}
          onSelect={() => onSelectRow(row.key)}
        />
      );
  }
}

interface ProjectRowProps {
  project: ProjectNode;
  expanded: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggleFold: () => void;
}

function ProjectRow({ project, expanded, selected, onSelect, onToggleFold }: ProjectRowProps) {
  const error = errorLabel(project.error);
  return (
    <li
      role="treeitem"
      aria-selected={selected}
      aria-expanded={expanded}
      data-depth={0}
      className={`flex flex-wrap items-center gap-2 px-2 py-1 text-sm font-medium ${
        selected ? "bg-surface-raised" : "hover:bg-surface-raised/60"
      }`}
      onClick={onSelect}
    >
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
      <span className="text-fg">{project.name}</span>
      <span className="text-xs font-normal text-fg-muted">{project.primary_path}</span>
      {error && <span className="text-xs font-normal text-danger">{error}</span>}
    </li>
  );
}
