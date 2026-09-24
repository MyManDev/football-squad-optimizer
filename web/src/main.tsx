import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { forgetRetiredTheme } from "./design/retiredTheme";
import "./design/tokens.css";

forgetRetiredTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
