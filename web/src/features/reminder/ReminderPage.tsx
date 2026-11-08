import { Link, useParams } from "react-router";

import { EmptyState } from "../../design/components/EmptyState";
import { useLanguage } from "../../i18n/context";
import { memberAddress } from "../../lib/leagueAddresses";
import type { ReminderBrowser, ReminderTarget } from "./deadlineReminder";
import { HomeScreenPicture, NotificationPicture, PermissionPicture } from "./ReminderIllustrations";
import styles from "./ReminderPage.module.css";
import { ReminderSwitch } from "./ReminderSwitch";
import { useDeadlineReminder } from "./useDeadlineReminder";

/**
 * How notifications are received (ADR 0013): the switch, where it stands, and three steps with
 * their pictures: allow the browser's question, on an iPhone add the site to the home screen
 * first, and what arrives three hours before the deadline. The owner asked for this page to
 * explain simply, with pictures, so it is the one page that does.
 */
export function ReminderPage({ browser }: { browser?: ReminderBrowser }) {
  const { messages, language } = useLanguage();
  const { leagueId: leagueParam, entryId: entryParam } = useParams();
  const leagueId = Number(leagueParam);
  const entryId = Number(entryParam);
  const valid =
    /^\d+$/.test(leagueParam ?? "") &&
    /^[1-9]\d*$/.test(entryParam ?? "") &&
    Number.isSafeInteger(entryId);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  return <ReminderPageView target={{ leagueId, entryId, language }} browser={browser} />;
}

export function ReminderPageView({
  target,
  browser,
}: {
  target: ReminderTarget;
  browser?: ReminderBrowser;
}) {
  const { messages } = useLanguage();
  const copy = messages.reminder;
  const { state } = useDeadlineReminder(target, browser);
  const status =
    state === "on"
      ? copy.statusOn
      : state === "unsupported"
        ? copy.statusUnsupported
        : state === "denied"
          ? copy.statusDenied
          : copy.statusOff;
  return (
    <div className={styles.page}>
      <header>
        <Link to={memberAddress(target.leagueId, target.entryId)}>{copy.back}</Link>
        <h1>{copy.title}</h1>
      </header>
      <section className={styles.control} aria-labelledby="reminder-switch-title">
        <h2 id="reminder-switch-title" className="visually-hidden">
          {copy.label}
        </h2>
        <ReminderSwitch target={target} browser={browser} inline />
        <p className={styles.status} role="status" data-reminder-status={state}>
          {status}
        </p>
      </section>
      <ol className={styles.steps}>
        <li className={styles.step}>
          <PermissionPicture allow={copy.allowWord} />
          <div>
            <h2>{copy.step1Title}</h2>
            <p>{copy.step1}</p>
          </div>
        </li>
        <li className={styles.step}>
          <HomeScreenPicture add={copy.addWord} />
          <div>
            <h2>{copy.step2Title}</h2>
            <p>{copy.step2}</p>
          </div>
        </li>
        <li className={styles.step}>
          <NotificationPicture title={copy.sampleTitle} body={copy.sampleBody} />
          <div>
            <h2>{copy.step3Title}</h2>
            <p>{copy.step3}</p>
          </div>
        </li>
      </ol>
    </div>
  );
}
