/**
 * Whether the opening cover (OpeningMark, the owner's four-second brand opening) has gone: the
 * GOL moments and their replay wait for it, and nothing plays under it.
 */

import { useEffect, useState } from "react";

const COVER = "[data-opening-mark]";

export function useCoverGone(): boolean {
  const [gone, setGone] = useState(
    () => typeof document === "undefined" || !document.querySelector(COVER),
  );
  useEffect(() => {
    if (gone) return undefined;
    const observer = new MutationObserver(() => {
      if (!document.querySelector(COVER)) setGone(true);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [gone]);
  return gone;
}
