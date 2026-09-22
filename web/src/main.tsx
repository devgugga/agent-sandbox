import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./components/App";
import "./index.css";

// One QueryClient for the app's lifetime (spec §9.1: TanStack Query owns
// server state). No default options override `useTree`'s own retry/refetch
// settings — those are set per-hook, not globally.
const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
