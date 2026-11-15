import { useEffect, useState } from "react";

const RECHECK_MS = 60_000;

/**
 * The page's clock, read once a minute and again at an optional boundary. The countdown
 * and deadline check can read the same clock, including the instant the week closes.
 */
export function useMinuteClock(clock: () => number = Date.now, boundary: number | null = null) {
  const [now, setNow] = useState(clock);
  useEffect(() => {
    if (boundary === null) {
      const interval = window.setInterval(() => setNow(clock()), RECHECK_MS);
      return () => window.clearInterval(interval);
    }
    const updateAt = boundary;
    let timer: number;
    function tick() {
      const current = clock();
      setNow(current);
      schedule(current);
    }
    function schedule(from: number) {
      const remaining = updateAt - from;
      const delay = remaining > 0 ? Math.min(RECHECK_MS, remaining) : RECHECK_MS;
      timer = window.setTimeout(tick, delay);
    }
    const current = clock();
    if (current >= updateAt) {
      timer = window.setTimeout(tick, 0);
    } else {
      schedule(current);
    }
    return () => window.clearTimeout(timer);
  }, [clock, boundary]);
  return now;
}
