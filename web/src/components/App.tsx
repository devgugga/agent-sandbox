// App — top-level composition: AuthGate, TopBar, ProjectTree, DetailPanel,
// ErrorBanner, CommandPalette (spec §9.4). Owns the two shortcuts that are
// not scoped to a single component (`Ctrl+K`, `Alt+R`); `ProjectTree`
// owns arrow/Enter navigation itself.
//
// `AppShell` is exported separately from the default `App` so tests can
// mount it directly with a `QueryClientProvider` and a stubbed `fetch`,
// without also having to drive `AuthGate`'s token exchange — `AuthGate` has
// its own dedicated tests for that.
import { useEffect, useMemo, useState } from "react";
import { AuthGate } from "./AuthGate";
import { TopBar } from "./TopBar";
import { ProjectTree } from "./ProjectTree";
import { DetailPanel } from "./DetailPanel";
import { ErrorBanner } from "./ErrorBanner";
import { CommandPalette } from "./CommandPalette";
import { useTree } from "../hooks/useTree";
import { useFold } from "../hooks/useFold";
import { ancestorKeys, buildRows, findRow, type Row } from "../lib/tree";

export function AppShell() {
  const { data, error, isFetching, refetch } = useTree();
  const { collapsed, toggle, expand } = useFold();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const projects = useMemo(() => data?.projects ?? [], [data]);
  const rows = useMemo(() => buildRows(projects), [projects]);
  const selection = findRow(rows, selectedKey);
  // Amendment §D: a 503 keeps the last tree, marked stale — never a
  // spinner, an empty state, or a cleared tree. `data` and `error` are
  // independent here (`useTree` never intercepts errors), so both can be
  // true at once.
  const isStale = error !== null && data !== undefined;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const key = event.key.toLowerCase();
      // `Ctrl+R` is the browser's reload in app mode and is left alone:
      // no handler below matches it. `Alt+1..9`/`Alt+N` are reserved for
      // item 2 and are likewise never bound here.
      if (event.ctrlKey && !event.altKey && !event.metaKey && key === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      } else if (event.altKey && !event.ctrlKey && !event.metaKey && key === "r") {
        event.preventDefault();
        void refetch();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [refetch]);

  function jumpTo(row: Row) {
    setSelectedKey(row.key);
    expand(ancestorKeys(row));
  }

  return (
    <div className="flex h-dvh flex-col bg-surface text-fg">
      <TopBar
        onRefresh={() => void refetch()}
        readAt={data?.read_at ?? null}
        isFetching={isFetching}
        isStale={isStale}
      />
      <ErrorBanner error={error} />
      <div className="flex flex-1 overflow-hidden">
        <div className="w-80 shrink-0 overflow-y-auto border-r border-border">
          <ProjectTree
            projects={projects}
            collapsed={collapsed}
            selectedKey={selectedKey}
            onSelectRow={setSelectedKey}
            onToggleFold={toggle}
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          <DetailPanel selection={selection} />
        </div>
      </div>
      {paletteOpen && (
        <CommandPalette
          projects={projects}
          onJump={jumpTo}
          onRunRefresh={() => void refetch()}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <AuthGate>
      <AppShell />
    </AuthGate>
  );
}
