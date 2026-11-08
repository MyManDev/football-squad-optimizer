// @vitest-environment node
import { describe, expect, it } from "vitest";

import { DIRECTORY_DOCUMENT, firstTurnTags } from "./firstTurn.ts";

function attrs(tag: { attrs?: Record<string, unknown> }) {
  return tag.attrs ?? {};
}

describe("firstTurnTags", () => {
  it("preloads the league directory at the address the gate reads it from", () => {
    const [preload] = firstTurnTags("/", "");
    expect(preload.tag).toBe("link");
    expect(preload.injectTo).toBe("head");
    expect(attrs(preload)).toEqual({
      rel: "preload",
      as: "fetch",
      href: `/${DIRECTORY_DOCUMENT}`,
      crossorigin: true,
    });
  });

  it("keeps the site base, with or without its trailing slash", () => {
    expect(attrs(firstTurnTags("/football-squad-optimizer/", "")[0]).href).toBe(
      "/football-squad-optimizer/data/leagues.json",
    );
    expect(attrs(firstTurnTags("/football-squad-optimizer", "")[0]).href).toBe(
      "/football-squad-optimizer/data/leagues.json",
    );
  });

  it("preconnects to the compute service only where the build names an origin", () => {
    expect(firstTurnTags("/", "")).toHaveLength(1);
    expect(firstTurnTags("/", undefined)).toHaveLength(1);
    const tags = firstTurnTags("/", "https://squadopt-api.example.test/");
    expect(tags).toHaveLength(2);
    expect(attrs(tags[1])).toEqual({
      rel: "preconnect",
      href: "https://squadopt-api.example.test",
      crossorigin: true,
    });
  });

  it("names no preconnect for an origin that is not a bare http(s) origin", () => {
    expect(firstTurnTags("/", "squadopt-api.example.test")).toHaveLength(1);
    expect(firstTurnTags("/", "https://squadopt-api.example.test/api/v1")).toHaveLength(1);
  });
});
