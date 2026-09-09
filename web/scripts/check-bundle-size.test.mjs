import { describe, expect, it } from "vitest";

import { initialAssets } from "./check-bundle-size.mjs";

describe("the initial JavaScript set", () => {
  it("is the module script plus the preloaded chunks, never a lazy route chunk", () => {
    const html = `
      <script type="module" crossorigin src="/assets/index-abc.js"></script>
      <link rel="modulepreload" crossorigin href="/assets/vendor-def.js">
      <link rel="modulepreload" crossorigin href="/assets/scores-ghi.js">
      <link rel="stylesheet" crossorigin href="/assets/index-jkl.css">
    `;
    expect(initialAssets(html)).toEqual([
      "assets/index-abc.js",
      "assets/vendor-def.js",
      "assets/scores-ghi.js",
    ]);
  });

  it("does not count the same file twice", () => {
    const html = `
      <script type="module" src="/assets/index-abc.js"></script>
      <link rel="modulepreload" href="/assets/index-abc.js">
    `;
    expect(initialAssets(html)).toEqual(["assets/index-abc.js"]);
  });
});
