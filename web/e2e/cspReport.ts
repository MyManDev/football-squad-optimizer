import { existsSync, readFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Where the preview writes each Content-Security-Policy refusal a browser reports during the
 * run (vite/sitePolicy.ts). A refused script or request usually fails its own spec; a refusal
 * no spec looks at, such as a style, fails the run here instead, so nothing the site loads is
 * refused unseen. The `.log` name keeps it out of git.
 */
export const CSP_REPORT_FILE = fileURLToPath(new URL("../csp-violations.log", import.meta.url));

/** The reports written so far, one per line, each as the browser sent it. */
export function cspReports(): string[] {
  if (!existsSync(CSP_REPORT_FILE)) return [];
  return readFileSync(CSP_REPORT_FILE, "utf-8")
    .split("\n")
    .filter((line) => line.trim() !== "");
}

/** Starts the run with no reports. */
export function clearCspReports(): void {
  rmSync(CSP_REPORT_FILE, { force: true });
}
