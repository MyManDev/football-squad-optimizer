/**
 * The site once had a different dark theme and stored the viewer's choice under this key.
 * That choice was never made between today's palettes, so a value left by an older visit
 * means nothing: it is removed on load, so no code later mistakes it for a live preference.
 * Today's choice has its own key (colourScheme.ts).
 */
export const RETIRED_THEME_KEY = "squadopt.theme";

export function forgetRetiredTheme(storage?: Pick<Storage, "removeItem">): void {
  try {
    (storage ?? window.localStorage).removeItem(RETIRED_THEME_KEY);
  } catch {
    /* Storage may be unavailable; there is then nothing stored to forget. */
  }
}
