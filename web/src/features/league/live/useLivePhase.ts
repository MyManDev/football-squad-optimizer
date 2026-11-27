/**
 * `livePhase` kept current: worked out again when it can next change (the week's first
 * kickoff, the end of its last match's window), at least every half hour, and when the page
 * comes back into view, since a hidden page's timers may not run on time.
 */

import { useEffect, useState } from "react";
import type { WeekEvent } from "../../../lib/weekState";

import type { FixturesPayload } from "../../fixtures/types";
import { livePhase, type LivePhase } from "../../liveScore/liveWindow";

const LONGEST_WAIT_MS = 30 * 60_000;

export function useLivePhase(
  fixtures: FixturesPayload | null,
  events: readonly WeekEvent[] = [],
): LivePhase {
  const [now, setNow] = useState(() => Date.now());
  const phase = livePhase(fixtures, now, events);
  const changesIn = phase.changesIn;
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
  return phase;
}
