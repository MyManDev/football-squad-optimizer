import { useCallback, useEffect, useMemo, useState } from "react";

import {
  currentSubscription,
  disableReminder,
  enableReminder,
  pageBrowser,
  reminderSupport,
  type ReminderBrowser,
  type ReminderTarget,
} from "./deadlineReminder";

export type ReminderState = "hidden" | "off" | "on" | "busy";

type Held = "off" | "on" | "busy";

/**
 * The reminder control's state for one member: hidden where the browser cannot hold a
 * reminder or has refused, and until the browser has said whether it holds one; else off or
 * on, and busy while a change is under way. `toggle` turns it on or off; a refusal leaves
 * the state as it was. A new member starts unknown again.
 */
export function useDeadlineReminder(
  target: ReminderTarget | null,
  browser?: ReminderBrowser,
): { state: ReminderState; toggle(): void } {
  const page = useMemo(() => browser ?? pageBrowser(), [browser]);
  const support = reminderSupport(page);
  const key = target === null ? null : `${target.leagueId}:${target.entryId}`;
  const hidden = key === null || support !== "available";
  const [known, setKnown] = useState<{ key: string | null; held: Held | null }>({
    key: null,
    held: null,
  });
  const held = known.key === key ? known.held : null;

  useEffect(() => {
    if (hidden || key === null) return;
    let live = true;
    currentSubscription(page)
      .then((subscription) => {
        if (live) setKnown({ key, held: subscription === null ? "off" : "on" });
      })
      .catch(() => {
        if (live) setKnown({ key, held: "off" });
      });
    return () => {
      live = false;
    };
  }, [hidden, key, page]);

  const toggle = useCallback(() => {
    if (target === null || hidden || held === null || held === "busy") return;
    const was = held;
    setKnown({ key, held: "busy" });
    const change: Promise<Held> =
      was === "on"
        ? disableReminder(page).then((): Held => "off")
        : enableReminder(page, target).then((kept): Held => (kept === null ? "off" : "on"));
    change.then((next) => setKnown({ key, held: next })).catch(() => setKnown({ key, held: was }));
  }, [target, hidden, held, key, page]);

  return { state: hidden || held === null ? "hidden" : held, toggle };
}
