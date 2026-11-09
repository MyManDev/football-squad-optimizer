/**
 * The day and night palettes: the system's preference decides until the viewer chooses, a
 * choice is stored and written to <html data-theme>, an unknown or unreadable stored value
 * is no choice, and the switch beside the language shows the palette on screen.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../i18n/LanguageProvider";
import {
  applyStoredColourScheme,
  COLOUR_SCHEME_KEY,
  currentColourScheme,
  DARK_SCHEME_QUERY,
  THEME_COLOURS,
} from "./colourScheme";
import { ThemeToggle } from "./components/ThemeToggle";

const root = () => document.documentElement;
let changeListeners: (() => void)[];
let systemDark: boolean;

function systemPrefers(dark: boolean) {
  systemDark = dark;
  for (const listener of changeListeners) listener();
}

beforeEach(() => {
  changeListeners = [];
  systemDark = false;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      get matches() {
        return query === DARK_SCHEME_QUERY && systemDark;
      },
      addEventListener: (_: string, listener: () => void) => changeListeners.push(listener),
      removeEventListener: (_: string, listener: () => void) => {
        changeListeners = changeListeners.filter((other) => other !== listener);
      },
    }),
  });
  window.localStorage.clear();
  applyStoredColourScheme();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete root().dataset.theme;
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const toggle = () =>
  render(
    <LanguageProvider initialLanguage="tr">
      <ThemeToggle />
    </LanguageProvider>,
  );
const pressed = () =>
  screen
    .getAllByRole("button")
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.getAttribute("aria-label"));

describe("the colour scheme", () => {
  it("names each palette's background as tokens.css paints it", () => {
    const css = readFileSync(resolve("src/design/tokens.css"), "utf8");
    const light = css.match(/:root\s*\{[^}]*--color-bg:\s*(#[0-9a-f]{6})/i)?.[1];
    const dark = css
      .slice(css.indexOf(':root[data-theme="dark"]'))
      .match(/--color-bg:\s*(#[0-9a-f]{6})/i)?.[1];
    expect(THEME_COLOURS).toEqual({ light, dark });
  });

  it("paints the browser's own bars with the palette on screen", async () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
    try {
      applyStoredColourScheme();
      expect(meta.content).toBe(THEME_COLOURS.light);
      const user = userEvent.setup();
      toggle();
      act(() => systemPrefers(true));
      expect(meta.content).toBe(THEME_COLOURS.dark);
      await user.click(screen.getByRole("button", { name: "Gündüz" }));
      expect(meta.content).toBe(THEME_COLOURS.light);
      // The viewer's choice holds against the system here too.
      act(() => systemPrefers(false));
      act(() => systemPrefers(true));
      expect(meta.content).toBe(THEME_COLOURS.light);
    } finally {
      meta.remove();
    }
  });

  it("follows the system until the viewer chooses, storing nothing", () => {
    expect(currentColourScheme()).toBe("light");
    systemPrefers(true);
    expect(currentColourScheme()).toBe("dark");
    expect(root().dataset.theme).toBeUndefined();
    expect(window.localStorage.getItem(COLOUR_SCHEME_KEY)).toBeNull();
  });

  it("opens in a stored choice, against the system", () => {
    window.localStorage.setItem(COLOUR_SCHEME_KEY, "light");
    systemPrefers(true);
    applyStoredColourScheme();
    expect(root().dataset.theme).toBe("light");
    expect(currentColourScheme()).toBe("light");
  });

  it.each(["dim", ""])("takes a stored %j as no choice", (value) => {
    window.localStorage.setItem(COLOUR_SCHEME_KEY, value);
    applyStoredColourScheme();
    expect(root().dataset.theme).toBeUndefined();
    expect(currentColourScheme()).toBe("light");
  });

  it("presses the palette on screen and keeps the viewer's choice", async () => {
    const user = userEvent.setup();
    toggle();
    expect(screen.getByRole("group", { name: "Renkler" })).toBeInTheDocument();
    expect(pressed()).toEqual(["Gündüz"]);
    act(() => systemPrefers(true));
    expect(pressed()).toEqual(["Gece"]);

    await user.click(screen.getByRole("button", { name: "Gündüz" }));
    expect(pressed()).toEqual(["Gündüz"]);
    expect(root().dataset.theme).toBe("light");
    expect(window.localStorage.getItem(COLOUR_SCHEME_KEY)).toBe("light");
    // A choice holds when the system changes its mind.
    act(() => systemPrefers(false));
    act(() => systemPrefers(true));
    expect(pressed()).toEqual(["Gündüz"]);

    await user.click(screen.getByRole("button", { name: "Gece" }));
    expect(root().dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(COLOUR_SCHEME_KEY)).toBe("dark");
  });

  it("still switches for the visit where storage refuses", async () => {
    const user = userEvent.setup();
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new DOMException("refused", "SecurityError");
    };
    try {
      toggle();
      await user.click(screen.getByRole("button", { name: "Gece" }));
      expect(root().dataset.theme).toBe("dark");
      expect(pressed()).toEqual(["Gece"]);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
