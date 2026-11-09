/**
 * The viewer's choice between the day and night palettes (tokens.css). Until the viewer
 * chooses, the operating system's preference decides and nothing is stored. A choice is
 * kept under COLOUR_SCHEME_KEY and written to <html data-theme>, which tokens.css reads, so
 * it holds against the system's preference. Like the sidebar's state it is a convenience for
 * the viewer's own browser: it holds no entry, no plan and no language.
 *
 * The browser paints its own bars beside the page (Safari's address bar, Android's status
 * bar) from <meta name="theme-color">; it is kept on the palette on screen, so a viewer who
 * chose the night palette on a light phone sees no white bar above a dark page.
 *
 * The key is new: the value an older visit left under the retired theme key means nothing
 * here (retiredTheme.ts removes it).
 */
import { useSyncExternalStore } from "react";

export type ColourScheme = "light" | "dark";

export const COLOUR_SCHEME_KEY = "squadopt.scheme";
export const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";
/** Each palette's page background, as tokens.css paints it (colourScheme.test.tsx holds them to it). */
export const THEME_COLOURS: Record<ColourScheme, string> = { light: "#ffffff", dark: "#0d1320" };

let chosen: ColourScheme | null = null;
const listeners = new Set<() => void>();

function readChoice(): ColourScheme | null {
  try {
    const value = window.localStorage.getItem(COLOUR_SCHEME_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(DARK_SCHEME_QUERY) : null;
}

/** The palette on screen: the viewer's choice, else the system's preference. */
export function currentColourScheme(): ColourScheme {
  return chosen ?? (darkQuery()?.matches ? "dark" : "light");
}

/** Paints the browser's own bars with the background of the palette on screen. */
function paintBrowserChrome(root: HTMLElement): void {
  const meta = root.ownerDocument.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.content = THEME_COLOURS[currentColourScheme()];
}

/** Reads a stored choice onto <html> before the first render, so the page opens in it. */
export function applyStoredColourScheme(root: HTMLElement = document.documentElement): void {
  chosen = readChoice();
  if (chosen === null) delete root.dataset.theme;
  else root.dataset.theme = chosen;
  paintBrowserChrome(root);
}

export function chooseColourScheme(
  scheme: ColourScheme,
  root: HTMLElement = document.documentElement,
): void {
  chosen = scheme;
  root.dataset.theme = scheme;
  paintBrowserChrome(root);
  try {
    window.localStorage.setItem(COLOUR_SCHEME_KEY, scheme);
  } catch {
    /* Storage may be unavailable; the palette still follows the click for this visit. */
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const query = darkQuery();
  // The system changing its mind repaints the bars where no choice holds against it.
  const onChange = () => {
    paintBrowserChrome(document.documentElement);
    listener();
  };
  query?.addEventListener?.("change", onChange);
  return () => {
    listeners.delete(listener);
    query?.removeEventListener?.("change", onChange);
  };
}

export function useColourScheme(): ColourScheme {
  return useSyncExternalStore(subscribe, currentColourScheme, () => "light");
}
