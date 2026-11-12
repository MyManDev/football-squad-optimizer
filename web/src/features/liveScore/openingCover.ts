/**
 * Whether the page is clear for the GOL board: the opening cover (OpeningMark, the owner's
 * four-second brand opening) has gone, no modal dialog is open (a player's details), no modal
 * panel is open (the menu drawer, the fixture sheet), and the board's own layer is not made
 * inert by a cover over the page (the device solve's progress). The board waits while any of
 * these is up, so no moment is spent unseen, and a board already up gives way when one opens.
 */

import { useEffect, useState, type RefObject } from "react";

const COVER = "[data-opening-mark]";

function clear(layer: HTMLElement | null): boolean {
  if (typeof document === "undefined") return true;
  if (document.querySelector(COVER) !== null) return false;
  if (document.querySelector("dialog[open]") !== null) return false;
  if (document.querySelector('[aria-modal="true"]') !== null) return false;
  return layer === null || !layer.closest("[inert]");
}

/** Whether the opening cover has gone. */
export function useCoverGone(): boolean {
  const [gone, setGone] = useState(
    () => typeof document === "undefined" || !document.querySelector(COVER),
  );
  useEffect(() => {
    if (gone) return undefined;
    const check = () => {
      if (!document.querySelector(COVER)) setGone(true);
    };
    const observer = new MutationObserver(check);
    observer.observe(document.body, { childList: true, subtree: true });
    // The cover may have gone in the very render that asked: looked at again once watched.
    check();
    return () => observer.disconnect();
  }, [gone]);
  return gone;
}

/** Whether nothing covers the page, for the layer `layer`: watched as the page changes. */
export function usePageClear(layer: RefObject<HTMLElement | null>): boolean {
  const [isClear, setClear] = useState(() => clear(null));
  useEffect(() => {
    const check = () => setClear(clear(layer.current));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["open", "inert", "aria-modal"],
    });
    return () => observer.disconnect();
  }, [layer]);
  return isClear;
}
