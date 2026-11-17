// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  blockHeaders,
  ORIGIN_WORD,
  policyOrigin,
  previewHeader,
  REPORT_PATH,
  resolveSiteHeaders,
} from "./sitePolicy.ts";

const SHIPPED = readFileSync(new URL("../public/_headers", import.meta.url), "utf-8");

function policyOf(source: string): string {
  const header = blockHeaders(source, "/*").find(
    ([name]) => name.toLowerCase() === "content-security-policy",
  );
  if (header === undefined) throw new Error("no policy");
  return header[1];
}

function directive(policy: string, name: string): string[] {
  const found = policy
    .split(";")
    .map((part) => part.trim().split(/\s+/))
    .find(([first]) => first === name);
  return found === undefined ? [] : found.slice(1);
}

describe("the compute service's origin in the policy", () => {
  it("is the bare origin, without a trailing slash", () => {
    expect(policyOrigin(" https://squadopt-api.mymandev.com/ ")).toBe(
      "https://squadopt-api.mymandev.com",
    );
    expect(policyOrigin("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
    expect(policyOrigin(undefined)).toBe("");
    expect(policyOrigin("")).toBe("");
  });

  it.each(["https://api.example/v1", "api.example", "https://a.example; script-src *", "*"])(
    "refuses %s",
    (value) => {
      expect(() => policyOrigin(value)).toThrow("bare origin");
    },
  );

  it("takes the word's place in the shipped file, and leaves no word in the rules", () => {
    const resolved = resolveSiteHeaders(SHIPPED, "https://squadopt-api.mymandev.com");
    const connect = directive(policyOf(resolved), "connect-src");
    expect(connect.slice(0, 2)).toEqual(["'self'", "https://squadopt-api.mymandev.com"]);
    expect(policyOf(resolved)).not.toContain(ORIGIN_WORD);
  });

  it("is dropped with its space when the build names none", () => {
    const connect = directive(policyOf(resolveSiteHeaders(SHIPPED, "")), "connect-src");
    expect(connect[0]).toBe("'self'");
    expect(connect[1]).toBe("https://api.openai.com");
    expect(connect).not.toContain("");
  });

  it("must stand in the rules exactly once", () => {
    expect(() => resolveSiteHeaders("/*\n  X: y\n", "")).toThrow("exactly once");
    expect(() =>
      resolveSiteHeaders(`/*\n  X: ${ORIGIN_WORD} ${ORIGIN_WORD}\n`, "https://a.example"),
    ).toThrow("exactly once");
    // A comment may name it.
    expect(resolveSiteHeaders(`# ${ORIGIN_WORD}\n/*\n  X: a ${ORIGIN_WORD}\n`, "")).toBe(
      `# ${ORIGIN_WORD}\n/*\n  X: a\n`,
    );
  });
});

describe("the shipped policy", () => {
  const policy = policyOf(resolveSiteHeaders(SHIPPED, "https://squadopt-api.mymandev.com"));

  it("runs the site's own scripts and Cloudflare's analytics beacon, and lets the solver compile its wasm", () => {
    expect(directive(policy, "script-src")).toEqual([
      "'self'",
      "'wasm-unsafe-eval'",
      "https://static.cloudflareinsights.com",
    ]);
    expect(directive(policy, "default-src")).toEqual(["'self'"]);
  });

  it("sends only to the site, the compute service, the model providers, loopback and the beacon's host", () => {
    expect(directive(policy, "connect-src")).toEqual([
      "'self'",
      "https://squadopt-api.mymandev.com",
      "https://api.openai.com",
      "https://api.anthropic.com",
      "https://generativelanguage.googleapis.com",
      "https://openrouter.ai",
      "https://api.mistral.ai",
      "https://api.groq.com",
      "https://api.deepseek.com",
      "http://localhost:*",
      "http://127.0.0.1:*",
      "https://cloudflareinsights.com",
    ]);
  });

  it("closes plugins, the base address, framing and foreign form targets", () => {
    expect(directive(policy, "object-src")).toEqual(["'none'"]);
    expect(directive(policy, "base-uri")).toEqual(["'none'"]);
    expect(directive(policy, "frame-ancestors")).toEqual(["'none'"]);
    expect(directive(policy, "form-action")).toEqual(["'self'"]);
  });

  it("is sent with the other site-wide headers, and with no cache rule", () => {
    const names = blockHeaders(SHIPPED, "/*").map(([name]) => name.toLowerCase());
    expect(names).toEqual([
      "content-security-policy",
      "referrer-policy",
      "x-content-type-options",
      "permissions-policy",
    ]);
  });
});

describe("the preview's headers", () => {
  it("reads one block, leaving out detached headers", () => {
    const source = "/*\n  A: 1\n\n/data/*\n  ! B\n  B: 2\n";
    expect(blockHeaders(source, "/*")).toEqual([["A", "1"]]);
    expect(blockHeaders(source, "/data/*")).toEqual([["B", "2"]]);
  });

  it("adds reporting to the policy alone, and allows nothing more", () => {
    expect(
      previewHeader([
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; ",
      ]),
    ).toEqual([
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'report-sample'; " +
        `style-src 'self' 'report-sample'; report-uri ${REPORT_PATH}`,
    ]);
    expect(previewHeader(["X-Content-Type-Options", "nosniff"])).toEqual([
      "X-Content-Type-Options",
      "nosniff",
    ]);
  });
});
