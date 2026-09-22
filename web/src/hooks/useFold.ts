// Fold state for the project tree, persisted in `localStorage` (spec
// §9.2). Nothing else belongs there — the session lives in the cookie.
// This is the only thing this app puts in browser storage.
import { useCallback, useState } from "react";

const STORAGE_KEY = "asb.tree.collapsed";

function readStored(): Set<string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((entry): entry is string => typeof entry === "string"));
  } catch {
    // Private browsing, quota, or corrupt JSON: start expanded.
    return new Set();
  }
}

function writeStored(collapsed: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsed]));
  } catch {
    // Fold state just doesn't survive a reload; nothing else depends on it.
  }
}

export interface UseFoldResult {
  collapsed: ReadonlySet<string>;
  /** Fold a node if unfolded, unfold it if folded. */
  toggle: (key: string) => void;
  /** Unfold every key in `keys` that is currently folded (no-op if none are). */
  expand: (keys: readonly string[]) => void;
}

export function useFold(): UseFoldResult {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => readStored());

  const toggle = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      writeStored(next);
      return next;
    });
  }, []);

  const expand = useCallback((keys: readonly string[]) => {
    setCollapsed((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const key of keys) {
        if (next.delete(key)) changed = true;
      }
      if (!changed) return prev;
      writeStored(next);
      return next;
    });
  }, []);

  return { collapsed, toggle, expand };
}
