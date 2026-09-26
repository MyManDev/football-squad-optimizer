import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { forgetRetiredTheme } from "./design/retiredTheme";
import "./design/fonts.css";
import "./design/tokens.css";

forgetRetiredTheme();

// A tab left open across a deploy asks for route chunks the new build renamed. Reload once
// to fetch the current build; a second failure in the same tab is left to the page's own
// error boundary, so a broken deploy cannot loop.
window.addEventListener("vite:preloadError", (event) => {
  try {
    if (sessionStorage.getItem("squadopt.reloadedForChunk") !== null) return;
    sessionStorage.setItem("squadopt.reloadedForChunk", "1");
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
