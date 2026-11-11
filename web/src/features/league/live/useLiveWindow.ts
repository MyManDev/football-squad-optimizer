/**
 * `liveWindow` kept current: it is worked out again when it can next change (a kickoff, the
 * end of a match's window, the next deadline), at least every half hour, and when the page
 * comes back into view, since a hidden page's timers may not run on time.
 */

import { useEffect, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import { liveWindow, type LiveWindow, type LiveWindowFilter } from "../../liveScore/liveWindow";

const LONGEST_WAIT_MS = 30 * 60_000;

/**
 * A filter's content as one string: a caller's new object naming the same clubs and matches is
 * the same filter, so it takes no new reading of the clock (and no render after it).
 */
function filterKey(filter: LiveWindowFilter): string {
  return [filter.clubs, filter.unfinished]
    .map((ids) => (ids == null ? "-" : [...ids].sort((a, b) => a - b).join(",")))
    .join("|");
}

/** `filter` is what the member's latest live read said: their clubs and the unfinished matches. */
export function useLiveWindow(
  fixtures: FixturesPayload | null,
  filter: LiveWindowFilter = {},
): LiveWindow {
  const [now, setNow] = useState(() => Date.now());
  const match = liveWindow(fixtures, now, filter);
  const changesIn = match.changesIn;
  const key = filterKey(filter);
  // A new filter (a read named the member's clubs) is read with the clock of now, not with
  // the one the last timer left, which can be up to half an hour old.
  useEffect(() => {
    const timer = setTimeout(() => setNow(Date.now()), 0);
    return () => clearTimeout(timer);
  }, [key]);
  useEffect(() => {
    if (changesIn === null) return undefined;
    const timer = setTimeout(
      () => setNow(Date.now()),
      Math.min(Math.max(changesIn, 1_000), LONGEST_WAIT_MS),
    );
    return () => clearTimeout(timer);
  }, [changesIn, now]);
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") setNow(Date.now());
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  return match;
}
