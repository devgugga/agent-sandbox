// AuthGate — token exchange and URL cleanup (spec §7.5, §9.4, amendment §E).
//
// `asb-agent ui` opens `http://127.0.0.1:<port>/#token=<token>` exactly
// once. This component reads that token from the URL fragment (never a
// query string), posts it to `/api/auth/session` via `createSession`
// (which puts it in the POST body), and on any outcome — success or
// failure — replaces the fragment so the token never lingers in the
// address bar or in browser history. If no token is present, it falls
// back to `getMe` to check whether an existing session cookie (from a
// previous exchange, surviving a page reload) is still valid.
import { useEffect, useState, type ReactNode } from "react";
import { createSession, getMe } from "../api/client";

type Status = "checking" | "authenticated" | "error";

interface AuthGateProps {
  children: ReactNode;
}

const TOKEN_FRAGMENT = /^#token=(.+)$/;

/** Removes the fragment in place, keeping path and query untouched. */
function clearFragment(): void {
  const { pathname, search } = window.location;
  window.history.replaceState(null, "", pathname + search);
}

export function AuthGate({ children }: AuthGateProps): ReactNode {
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function run(): Promise<void> {
      const match = TOKEN_FRAGMENT.exec(window.location.hash);
      if (match) {
        const token = decodeURIComponent(match[1]);
        // Cleared immediately, before the exchange settles: on failure the
        // operator has to re-open `asb-agent ui` for a fresh URL anyway, so
        // there is no reason to let a one-time token sit in the address bar
        // while a request is in flight.
        clearFragment();
        try {
          await createSession(token);
          if (!cancelled) setStatus("authenticated");
        } catch (err) {
          if (!cancelled) {
            setStatus("error");
            setMessage(err instanceof Error ? err.message : "Could not start a session.");
          }
        }
        return;
      }

      // No token in the URL: this is a reload after a prior successful
      // exchange (or a tab reused across app restarts). Trust the cookie
      // if the daemon still does.
      try {
        await getMe();
        if (!cancelled) setStatus("authenticated");
      } catch (err) {
        if (!cancelled) {
          setStatus("error");
          setMessage(err instanceof Error ? err.message : "No active session.");
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "checking") {
    return (
      <div className="flex h-dvh items-center justify-center text-fg-muted" role="status">
        Checking session…
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-2 text-center" role="alert">
        <p className="text-fg">Not signed in.</p>
        <p className="text-fg-muted text-sm">{message}</p>
        <p className="text-fg-muted text-sm">
          Run <code>asb-agent ui</code> again to open a fresh link.
        </p>
      </div>
    );
  }

  return children;
}
