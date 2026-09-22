import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

// Placeholder mount point. AuthGate, TopBar, ProjectTree and the rest of
// the screen (spec section 9.4) arrive in later tasks; item 1 only proves
// the scaffold builds, lints, typechecks and runs an (empty) test suite.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div>agent-sandbox</div>
  </StrictMode>,
);
