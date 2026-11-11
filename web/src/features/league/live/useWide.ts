/**
 * Whether the LIVE page has room for its two columns: the rival and Farklar beside the rest
 * from 1024 px. Where no media query can be asked (jsdom) it reads one column, as a phone.
 */

import { useSyncExternalStore } from "react";

export const WIDE_QUERY = "(min-width: 1024px)";

function list(): MediaQueryList | null {
  return typeof window === "undefined" || typeof window.matchMedia !== "function"
    ? null
    : window.matchMedia(WIDE_QUERY);
}

function subscribe(onChange: () => void): () => void {
  const query = list();
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}

const read = () => list()?.matches ?? false;

export function useWide(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
