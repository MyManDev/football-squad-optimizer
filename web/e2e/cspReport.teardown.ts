import { CSP_REPORT_FILE, cspReports } from "./cspReport";

/**
 * content-security-policy.spec.ts makes its refusals on purpose, on pages whose address
 * carries `csp-probe`.
 */
const DELIBERATE = "csp-probe";

/**
 * Playwright's own refusal, not the site's: before a screenshot in WebKit it appends
 * `<style>body {}</style>` to the page to settle animations (`inPagePrepareForScreenshots`),
 * which the policy refuses. WebKit sends its reports in this form and with no sample, so the
 * report cannot say more; Chromium and Firefox run the same pages and report any inline
 * style the site itself adds.
 */
function isWebKitScreenshotStyle(report: string): boolean {
  return (
    report.startsWith('{"type":"csp-violation"') &&
    report.includes('"effective-directive":"style-src-elem"') &&
    report.includes('"blocked-uri":"inline"')
  );
}

export default function globalTeardown(): void {
  const unexpected = cspReports().filter(
    (report) => !report.includes(DELIBERATE) && !isWebKitScreenshotStyle(report),
  );
  if (unexpected.length === 0) return;
  throw new Error(
    `The site broke its Content-Security-Policy ${unexpected.length} time(s) during the run ` +
      `(${CSP_REPORT_FILE}):\n${unexpected.slice(0, 10).join("\n")}`,
  );
}
