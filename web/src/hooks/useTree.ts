// TanStack Query hook over `GET /api/tree` (spec §9.1, §9.4).
//
// Item 1 has no cache and no background refresh (spec §7.4): refresh is
// the operator pressing a button, so window-focus and reconnect
// refetching are disabled here and nothing polls. `refetch` is exposed for
// that button. Retries are off too: a 401 or 503 is not transient the way a
// blip is, and Task 8 (§C) needs to see `isError` right away to decide
// between re-authenticating and showing the stale-tree banner, not three
// retries and a backoff delay later.
//
// `getTree` throws instead of swallowing errors into its return value, so
// TanStack Query's default behavior applies: on a failed fetch, `error` is
// set but `data` keeps the last successfully fetched tree. That is exactly
// what spec §9.2/§7.6 asks for — the consumer (Task 8) keeps the last tree
// and marks it stale, rather than losing it, by checking `error` against
// `ServiceUnavailableError` while `data` is still there.
import { useQuery } from "@tanstack/react-query";
import { getTree, type TreeFetchError, type TreeResponse } from "../api/client";

export function useTree() {
  return useQuery<TreeResponse, TreeFetchError>({
    queryKey: ["tree"],
    queryFn: getTree,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}
