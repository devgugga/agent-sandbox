// ErrorBanner — registry 503, stale tree still visible (spec §9.2, §7.6,
// amendment §D). This component only renders the message; keeping the
// stale tree on screen alongside it is `AppShell`'s job (it never stops
// rendering `ProjectTree` just because `useTree`'s `error` is set).
import { ServiceUnavailableError, UnauthorizedError, type TreeFetchError } from "../api/client";

export interface ErrorBannerProps {
  error: TreeFetchError | null;
}

function describe(error: TreeFetchError): string {
  if (error instanceof ServiceUnavailableError) {
    return `Registry unavailable: ${error.message}`;
  }
  if (error instanceof UnauthorizedError) {
    return `Session expired: ${error.message}`;
  }
  return `Failed to read the tree: ${error.message}`;
}

export function ErrorBanner({ error }: ErrorBannerProps) {
  if (!error) return null;
  return (
    <div role="alert" className="border-b border-danger bg-danger/10 px-4 py-2 text-sm text-danger">
      {describe(error)}
    </div>
  );
}
