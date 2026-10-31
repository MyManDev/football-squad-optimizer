import { deadlineIcs, futureDeadlines } from "./deadlineIcs";
import type { FixturesCopy } from "./fixturesCopy";
import type { FixturesPayload } from "./types";
import styles from "./DeadlineCalendar.module.css";

const FILE_NAME = "squadopt-deadlines.ics";

/**
 * The deadlines still ahead as a calendar file, built on this device from the fixture list on
 * screen when the button is pressed. The site sends no reminder of its own: the member's
 * calendar app gives it, two hours before each deadline. Drawn only while a deadline is ahead.
 */
export function DeadlineCalendar({
  payload,
  copy,
}: {
  payload: FixturesPayload;
  copy: FixturesCopy;
}) {
  if (futureDeadlines(payload.gameweeks).length === 0) return null;

  const download = () => {
    const site = new URL(import.meta.env.BASE_URL, window.location.origin).href;
    const file = deadlineIcs(
      payload,
      { summary: copy.calendarSummary, description: copy.calendarDescription(site) },
      Date.now(),
    );
    const url = URL.createObjectURL(new Blob([file], { type: "text/calendar;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = FILE_NAME;
    document.body.append(link);
    link.click();
    link.remove();
    // The browser reads the file after the click returns, so the URL outlives it a while.
    window.setTimeout(() => URL.revokeObjectURL(url), 40_000);
  };

  return (
    <div className={styles.calendar} data-mark="deadline-calendar">
      <button type="button" className={styles.action} onClick={download}>
        {copy.calendarAction}
      </button>
    </div>
  );
}
