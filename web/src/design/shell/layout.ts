import { useSyncExternalStore } from "react";

/**
 * Direction D's three shell layouts, by viewport width:
 * - phone, under 600 px: one column, a sticky phone bar, the sidebar as a drawer;
 * - tablet, 600 to 1179 px: a 72 px icon rail that opens the full sidebar over the page;
 * - desktop, 1180 px and up: the sidebar beside the page, open at 264 px or collapsed to 72.
 */
export type ShellLayout = "phone" | "tablet" | "desktop";

export const PHONE_QUERY = "(max-width: 599.98px)";
export const DESKTOP_QUERY = "(min-width: 1180px)";

function queries(): MediaQueryList[] | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return [window.matchMedia(PHONE_QUERY), window.matchMedia(DESKTOP_QUERY)];
}

/** Where no media query can be asked (jsdom), the page is laid out as a desktop. */
export function readShellLayout(): ShellLayout {
  const lists = queries();
  if (!lists) return "desktop";
  const [phone, desktop] = lists;
  if (phone!.matches) return "phone";
  if (desktop!.matches) return "desktop";
  return "tablet";
}

function subscribe(onChange: () => void): () => void {
  const lists = queries();
  if (!lists) return () => undefined;
  for (const list of lists) list.addEventListener("change", onChange);
  return () => {
    for (const list of lists) list.removeEventListener("change", onChange);
  };
}

export function useShellLayout(): ShellLayout {
  return useSyncExternalStore(subscribe, readShellLayout, () => "desktop");
}
