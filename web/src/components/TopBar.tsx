// TopBar — refresh button, "read at" time, in-progress indicator, stale
// marker (spec §9.2, amendment §D).
export interface TopBarProps {
  onRefresh: () => void;
  /** `data.read_at` from the last successful `/api/tree` response, if any. */
  readAt: string | null;
  /** True while a read (initial or refetch) is in flight. */
  isFetching: boolean;
  /** True when the tree on screen is the last good one, but the most
   * recent read failed (amendment §D: a 503 marks it stale, never clears
   * it). */
  isStale: boolean;
}

export function TopBar({ onRefresh, readAt, isFetching, isStale }: TopBarProps) {
  return (
    <header className="flex items-center gap-3 border-b border-border bg-surface-raised px-4 py-2">
      <button
        type="button"
        onClick={onRefresh}
        disabled={isFetching}
        className="rounded border border-border px-3 py-1 text-sm hover:bg-surface disabled:opacity-50"
      >
        Refresh
      </button>
      <span className="text-sm text-fg-muted">
        {readAt ? `Read at ${new Date(readAt).toLocaleTimeString()}` : "Not loaded yet"}
      </span>
      {isFetching && (
        <span role="status" className="text-sm text-fg-muted">
          Refreshing…
        </span>
      )}
      {isStale && (
        <span className="rounded border border-danger px-2 py-0.5 text-xs text-danger">
          stale
        </span>
      )}
    </header>
  );
}
