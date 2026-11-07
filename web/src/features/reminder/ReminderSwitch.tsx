import { useNavigate } from "react-router";

import { useLanguage } from "../../i18n/context";
import { memberReminderAddress } from "../../lib/leagueAddresses";
import type { ReminderBrowser, ReminderTarget } from "./deadlineReminder";
import styles from "./ReminderSwitch.module.css";
import { useDeadlineReminder, type ReminderState } from "./useDeadlineReminder";

/**
 * The reminder's switch (ADR 0013). Off to on starts the browser's permission question and
 * opens the page that shows how notifications are received; on to off drops the reminder in
 * place. Where the browser cannot hold a reminder, or has refused, the switch stays off and
 * opens the same page, which says what to do. In the sidebar beside Değiştir, and on the page
 * itself (`inline`).
 */
export function ReminderSwitch({
  target,
  browser,
  inline = false,
}: {
  target: ReminderTarget | null;
  browser?: ReminderBrowser;
  inline?: boolean;
}) {
  const { messages } = useLanguage();
  const navigate = useNavigate();
  const { state, enable, disable } = useDeadlineReminder(target, browser);
  if (target === null || state === "unknown") return null;
  const on = state === "on";
  const busy = state === "busy";
  const open = () => navigate(memberReminderAddress(target.leagueId, target.entryId));
  const flip = () => {
    if (busy) return;
    if (on) {
      disable();
      return;
    }
    if (state === "off") enable();
    if (!inline) open();
  };
  // In the sidebar the switch is the track alone, named for the reader, so the identity block
  // stays one row beside Değiştir; on the page the word stands beside it.
  const word = wordFor(state, messages.reminder);
  return (
    <button
      type="button"
      role="switch"
      className={inline ? styles.inlineSwitch : styles.sidebarSwitch}
      aria-checked={on}
      aria-busy={busy || undefined}
      aria-label={inline ? undefined : word}
      disabled={busy}
      onClick={flip}
      data-reminder={state}
    >
      <span className={styles.track} aria-hidden="true">
        <span className={styles.knob} />
      </span>
      {inline ? <span className={styles.word}>{word}</span> : null}
    </button>
  );
}

function wordFor(state: ReminderState, copy: { label: string; on: string }): string {
  return state === "on" ? copy.on : copy.label;
}
