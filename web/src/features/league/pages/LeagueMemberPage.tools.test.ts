/**
 * The member page's closed tools open and close in the card time (#1136), in CSS alone: the
 * content box grows to its own height and back, and is drawn until it has shut. jsdom has no
 * `::details-content`, so the stylesheet is read: the motion sits behind a support check, so
 * a browser that cannot size to `auto` opens the section at once, and takes its time from
 * the token, which is zero under reduced motion.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "LeagueMemberPage.module.css"), "utf-8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/** The `@supports (interpolate-size: allow-keywords)` block, or "". */
const supported =
  css.match(/@supports \(interpolate-size: allow-keywords\) \{[\s\S]*?\n\}/)?.[0] ?? "";

describe("the member page's tools", () => {
  it("grow from nothing to their height and back in the card time, where the browser can", () => {
    expect(supported).toMatch(/\.tool\s*\{\s*interpolate-size: allow-keywords;\s*\}/);
    expect(supported).toMatch(
      /\.tool::details-content\s*\{[^}]*block-size: 0;[^}]*overflow-y: clip;/,
    );
    expect(supported).toMatch(/block-size var\(--motion-ui\) var\(--motion-ease\)/);
    expect(supported).toMatch(
      /content-visibility var\(--motion-ui\) var\(--motion-ease\) allow-discrete/,
    );
    expect(supported).toMatch(/\.tool\[open\]::details-content\s*\{\s*block-size: auto;\s*\}/);
  });

  it("are styled at their content box nowhere outside that support check", () => {
    expect(supported).not.toBe("");
    expect(css.replace(supported, "")).not.toMatch(/::details-content|interpolate-size/);
  });
});
