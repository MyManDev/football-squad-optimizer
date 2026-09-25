import { afterEach, describe, expect, it } from "vitest";

import { forgetRetiredTheme, RETIRED_THEME_KEY } from "./retiredTheme";

describe("the retired theme choice", () => {
  afterEach(() => window.localStorage.clear());

  it("removes a dark choice an older visit stored", () => {
    window.localStorage.setItem(RETIRED_THEME_KEY, "dark");
    window.localStorage.setItem("squadopt.language", "en");

    forgetRetiredTheme();

    expect(window.localStorage.getItem(RETIRED_THEME_KEY)).toBeNull();
    // Only the retired key goes: the viewer's language stays theirs.
    expect(window.localStorage.getItem("squadopt.language")).toBe("en");
  });

  it("does nothing when no choice was stored", () => {
    forgetRetiredTheme();
    expect(window.localStorage.getItem(RETIRED_THEME_KEY)).toBeNull();
  });

  it("keeps the page loading when storage refuses", () => {
    const refusing = {
      removeItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
    };
    expect(() => forgetRetiredTheme(refusing)).not.toThrow();
  });
});
