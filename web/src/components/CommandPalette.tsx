// CommandPalette — Ctrl+K filtering: jump to a project, checkout or
// session, or run "refresh" (spec §9.3, §9.4). This is the
// one place every tree row and the refresh action are reachable from,
// regardless of fold state or scroll position — "everything is reachable
// through the palette; shortcuts are a complement" (spec §9.3).
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { buildRows, type Row } from "../lib/tree";
import type { ProjectNode } from "../types/tree";

export interface CommandPaletteProps {
  projects: readonly ProjectNode[];
  onJump: (row: Row) => void;
  onRunRefresh: () => void;
  onClose: () => void;
}

type JumpableRow = Extract<Row, { kind: "project" | "checkout" | "session" }>;

type Entry =
  | { kind: "row"; id: string; label: string; row: JumpableRow }
  | { kind: "command"; id: "refresh"; label: string };

function rowLabel(row: JumpableRow): string {
  switch (row.kind) {
    case "project":
      return row.project.name;
    case "checkout":
      return `${row.project.name} / ${row.checkout.workspace}`;
    case "session":
      return `${row.project.name} / ${row.checkout.workspace} / ${row.session.title}`;
  }
}

export function CommandPalette({ projects, onJump, onRunRefresh, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const entries = useMemo<Entry[]>(() => {
    const jumpable = buildRows(projects).filter(
      (row): row is JumpableRow =>
        row.kind === "project" || row.kind === "checkout" || row.kind === "session",
    );
    const rowEntries: Entry[] = jumpable.map((row) => ({
      kind: "row",
      id: row.key,
      label: rowLabel(row),
      row,
    }));
    return [...rowEntries, { kind: "command", id: "refresh", label: "Refresh" }];
  }, [projects]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) => entry.label.toLowerCase().includes(needle));
  }, [entries, query]);

  function activate(entry: Entry | undefined) {
    if (!entry) return;
    if (entry.kind === "row") {
      onJump(entry.row);
    } else {
      onRunRefresh();
    }
    onClose();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (filtered.length === 0) return;
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((prev) => (prev + delta + filtered.length) % filtered.length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      activate(filtered[highlight]);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-24"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="w-full max-w-md rounded border border-border bg-surface-raised shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setHighlight(0);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Jump to a project, checkout or session…"
          className="w-full border-b border-border bg-transparent px-3 py-2 text-sm text-fg outline-none"
        />
        <ul role="listbox" className="max-h-80 overflow-y-auto">
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-sm text-fg-muted">No matches.</li>
          ) : (
            filtered.map((entry, index) => (
              <li
                key={entry.id}
                role="option"
                aria-selected={index === highlight}
                className={`cursor-pointer px-3 py-2 text-sm ${index === highlight ? "bg-surface" : ""}`}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => activate(entry)}
              >
                {entry.label}
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
