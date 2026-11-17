/**
 * The site's response headers, from public/_headers, at build and in the preview (ADR 0017
 * step 3).
 *
 * At build, the Content-Security-Policy's `{advice-api-origin}` takes the build's
 * VITE_ADVICE_API_ORIGIN, so the published policy lets the page reach the compute service it
 * was built for and no other. A build without one drops the word.
 *
 * In the preview, the `/*` block of the built _headers is sent on every response, as Pages
 * sends it, so the end-to-end suite runs under the policy the site ships with. The preview
 * alone adds `report-uri` and `'report-sample'`: each refusal the browser reports is appended to the file
 * SQUADOPT_CSP_REPORT_FILE names, which the suite reads at its end (e2e/cspReport.ts).
 */

import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Plugin } from "vite";

export const ORIGIN_WORD = "{advice-api-origin}";
export const REPORT_PATH = "/__csp-report";
const SITE_WIDE = "/*";
/** A report body larger than this is not a browser's report; it is dropped. */
const MAX_REPORT_BYTES = 16 * 1024;

/**
 * The compute service's origin as the policy names it: scheme and host, no path and no
 * trailing slash; "" when the build names none. Anything else would put a broken or wider
 * source in the policy, so the build stops.
 */
export function policyOrigin(value: string | undefined): string {
  const origin = (value ?? "").trim().replace(/\/+$/, "");
  if (origin === "") return "";
  if (!/^https?:\/\/[a-z0-9.-]+(:\d+)?$/i.test(origin)) {
    throw new Error(
      `VITE_ADVICE_API_ORIGIN must be a bare origin such as https://api.example.com, not "${value}".`,
    );
  }
  return origin;
}

/**
 * The headers file with the compute service's origin written in place of its word. Comment
 * lines may name the word; the rules must name it exactly once.
 */
export function resolveSiteHeaders(source: string, apiOrigin: string | undefined): string {
  const lines = source.split("\n");
  const rules = lines.filter((line) => !line.trim().startsWith("#"));
  const occurrences = rules.join("\n").split(ORIGIN_WORD).length - 1;
  if (occurrences !== 1) {
    throw new Error(`_headers must name ${ORIGIN_WORD} exactly once; it names it ${occurrences}.`);
  }
  const origin = policyOrigin(apiOrigin);
  return lines
    .map((line) =>
      line.trim().startsWith("#")
        ? line
        : origin === ""
          ? line.replace(` ${ORIGIN_WORD}`, "")
          : line.replace(ORIGIN_WORD, origin),
    )
    .join("\n");
}

/** The headers of one route block of a _headers file, in order, names as written. */
export function blockHeaders(source: string, route: string): [string, string][] {
  const headers: [string, string][] = [];
  let inside = false;
  for (const raw of source.replaceAll("\r\n", "\n").split("\n")) {
    const line = raw.trim();
    if (line === "") {
      inside = false;
      continue;
    }
    if (line.startsWith("#")) continue;
    if (!/^\s/.test(raw)) {
      inside = line === route;
      continue;
    }
    const separator = line.indexOf(":");
    if (inside && separator > 0 && !line.startsWith("!")) {
      headers.push([line.slice(0, separator).trim(), line.slice(separator + 1).trim()]);
    }
  }
  return headers;
}

/** The directives whose refusals carry the start of the refused text in a report. */
const SAMPLED = new Set(["script-src", "style-src"]);

/**
 * The preview's copy of a header. The policy allows exactly what the site's does; it also
 * reports each refusal to the preview, with the start of any refused inline text, so a report
 * says what was refused.
 */
export function previewHeader([name, value]: [string, string]): [string, string] {
  if (name.toLowerCase() !== "content-security-policy") return [name, value];
  const directives = value
    .split(";")
    .map((directive) => directive.trim())
    .filter((directive) => directive !== "")
    .map((directive) =>
      SAMPLED.has(directive.split(/\s+/)[0]!) ? `${directive} 'report-sample'` : directive,
    );
  return [name, [...directives, `report-uri ${REPORT_PATH}`].join("; ")];
}

export function sitePolicy(): Plugin {
  let apiOrigin: string | undefined;
  let publicDir = "";
  return {
    name: "squadopt:site-policy",
    configResolved(config) {
      apiOrigin = config.env.VITE_ADVICE_API_ORIGIN as string | undefined;
      publicDir = config.publicDir;
      // Checked before the bundle is built, so a bad origin costs no build time.
      policyOrigin(apiOrigin);
    },
    // Written from public/_headers, not from the copy in the output, so a second pass over
    // the same output writes the same file.
    writeBundle(options) {
      const source = resolve(publicDir, "_headers");
      if (publicDir === "" || !existsSync(source)) return;
      writeFileSync(
        resolve(options.dir ?? "dist", "_headers"),
        resolveSiteHeaders(readFileSync(source, "utf-8"), apiOrigin),
      );
    },
    configurePreviewServer(server) {
      const file = resolve(server.config.root, server.config.build.outDir, "_headers");
      const reportFile = process.env.SQUADOPT_CSP_REPORT_FILE;
      server.middlewares.use((request, response, next) => {
        if (request.method === "POST" && request.url === REPORT_PATH) {
          const chunks: Buffer[] = [];
          let size = 0;
          request.on("data", (chunk: Buffer) => {
            size += chunk.length;
            if (size <= MAX_REPORT_BYTES) chunks.push(chunk);
          });
          request.on("end", () => {
            const report = Buffer.concat(chunks).toString("utf-8").replace(/\s+/g, " ");
            if (reportFile) appendFileSync(reportFile, `${report}\n`);
            else server.config.logger.warn(`Content-Security-Policy refusal: ${report}`);
            response.statusCode = 204;
            response.end();
          });
          return;
        }
        // Read on each request, so a preview left running serves the latest build's policy.
        if (existsSync(file)) {
          for (const header of blockHeaders(readFileSync(file, "utf-8"), SITE_WIDE)) {
            response.setHeader(...previewHeader(header));
          }
        }
        next();
      });
    },
  };
}
