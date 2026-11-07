import { useLanguage } from "../../i18n/context";
import type { ReminderBrowser, ReminderTarget } from "./deadlineReminder";
import styles from "./ReminderToggle.module.css";
import { useDeadlineReminder } from "./useDeadlineReminder";

/**
 * The one control of the deadline reminder (ADR 0013): a pressed button, "Hatırlat" off and
 * "Hatırlatma açık" on, beside Değiştir in the sidebar's identity block. Nothing where the
 * browser cannot hold a reminder.
 */
export function ReminderToggle({
  target,
  browser,
}: {
  target: ReminderTarget | null;
  browser?: ReminderBrowser;
}) {
  const { messages } = useLanguage();
  const { state, toggle } = useDeadlineReminder(target, browser);
  if (state === "hidden") return null;
  const on = state === "on";
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-pressed={on}
      aria-busy={state === "busy" || undefined}
      disabled={state === "busy"}
      onClick={toggle}
      data-reminder={state}
    >
      <span className={styles.light} aria-hidden="true" />
      {on ? messages.reminder.on : messages.reminder.off}
    </button>
  );
}
