// `ErrorBanner` on 503 (spec §9.2, §7.6). This file covers the banner's
// own rendering in isolation; the "stale tree still visible" half (the
// banner never hides the last good tree) is covered by `App.test.tsx`,
// where the banner sits alongside a real `ProjectTree`.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorBanner } from "./ErrorBanner";
import { ServiceUnavailableError, UnauthorizedError } from "../api/client";

describe("ErrorBanner", () => {
  it("renders nothing when there is no error", () => {
    render(<ErrorBanner error={null} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the registry-unavailable message for a 503", () => {
    render(<ErrorBanner error={new ServiceUnavailableError("registry read failed")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Registry unavailable: registry read failed",
    );
  });

  it("shows a session-expired message for a 401", () => {
    render(<ErrorBanner error={new UnauthorizedError("Missing or invalid session cookie.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/session expired/i);
  });

  it("shows a generic message for a network failure", () => {
    render(<ErrorBanner error={new TypeError("Failed to fetch")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to fetch");
  });
});
