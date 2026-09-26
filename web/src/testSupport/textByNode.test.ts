import { describe, expect, it } from "vitest";

import { textByNode } from "./textByNode";

describe("text by node", () => {
  it("puts a word boundary at every element edge, where textContent puts none", () => {
    const root = document.createElement("div");
    root.innerHTML =
      "26 <span>live</span><div>Adı konan ilk 11</div><span>GW</span><span>Karar</span>";
    // The failure this helper exists for: glued to the next element, the badge and the
    // header are invisible to a whole-word check on textContent.
    expect(root.textContent).toBe("26 liveAdı konan ilk 11GWKarar");
    expect(root.textContent).not.toMatch(/\b(live|GW)\b/);
    expect(textByNode(root)).toBe("26  live Adı konan ilk 11 GW Karar");
    expect(textByNode(root).match(/\b(live|GW)\b/g)).toEqual(["live", "GW"]);
  });
});
