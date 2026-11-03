import { useEffect, useState } from "react";

const RECHECK_MS = 60_000;

/**
 * The page's clock, read once a minute so an open page notices the deadline. A page keeps
 * one: the member page's deadline check and its top bar's countdown read the same minute,
 * so the bar never counts down a week the page already calls closed. A test hands in its
 * own clock, or drives this one with fake timers.
 */
export function useMinuteClock(clock: () => number = Date.now): number {
  const [now, setNow] = useState(clock);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(clock()), RECHECK_MS);
    return () => window.clearInterval(timer);
  }, [clock]);
  return now;
}
