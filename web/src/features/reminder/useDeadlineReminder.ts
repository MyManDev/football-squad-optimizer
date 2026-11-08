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

/**
 * Where the reminder stands for this browser and member: not yet known, a browser that cannot
 * hold one, a permission refused, off, on, or changing.
 */
export type ReminderState = "unknown" | "unsupported" | "denied" | "off" | "on" | "busy";

type Held = "off" | "on" | "busy";

/**
 * The reminder for one member in this browser. `enable` asks the browser's permission and
 * subscribes; `disable` drops the subscription; a refusal leaves the state as it was. A new
 * member starts unknown again. `target` null gives "unknown" and does nothing.
 */
export function useDeadlineReminder(
  target: ReminderTarget | null,
  browser?: ReminderBrowser,
): { state: ReminderState; enable(): void; disable(): void } {
  const page = useMemo(() => browser ?? pageBrowser(), [browser]);
  const support = reminderSupport(page);
  const key = target === null ? null : `${target.leagueId}:${target.entryId}`;
  const [known, setKnown] = useState<{ key: string | null; held: Held | null }>({
    key: null,
    held: null,
  });
  const held = known.key === key ? known.held : null;

  useEffect(() => {
    if (key === null || support !== "available") return;
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
  }, [key, support, page]);

  const state: ReminderState =
    key === null ? "unknown" : support !== "available" ? support : (held ?? "unknown");

  const enable = useCallback(() => {
    if (target === null || state !== "off") return;
    setKnown({ key, held: "busy" });
    enableReminder(page, target)
      .then((kept): Held => (kept === null ? "off" : "on"))
      .then((next) => setKnown({ key, held: next }))
      .catch(() => setKnown({ key, held: "off" }));
  }, [target, state, key, page]);

  const disable = useCallback(() => {
    if (state !== "on") return;
    setKnown({ key, held: "busy" });
    disableReminder(page)
      .then(() => setKnown({ key, held: "off" }))
      .catch(() => setKnown({ key, held: "on" }));
  }, [state, key, page]);

  return { state, enable, disable };
}
