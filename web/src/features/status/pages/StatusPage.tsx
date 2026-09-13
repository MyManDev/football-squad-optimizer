import { useEffect, useState } from "react";

import { useIndex, useStatus } from "../../../data/queries";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { reasonText } from "../../../i18n/reasons";
import { countdown, local, utcShort } from "../../../lib/format";
import styles from "./StatusPage.module.css";

const TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "accent"> = {
  capture: "accent",
  decide: "good",
  settle: "good",
  wait: "neutral",
};

/**
 * The browser's own clock, re-read on a modest interval.
 *
 * The document's `hours_to_deadline` is honest about the moment it was published and about
 * nothing else, so a page left open, or opened a day later, cannot read remaining time off
 * it. A minute is coarse enough that nothing flickers and fine enough that the tile does not
 * keep claiming time that has already run out.
 */
function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function StatusPage() {
  const { locale, messages } = useLanguage();
  const copy = messages.status;
  const now = useNow(60_000);
  const index = useIndex();
  const season = index.data?.payload.seasons[0];
  const status = useStatus(season);
  if (index.isPending || (season && status.isPending)) {
    return <EmptyState title={copy.loading} />;
  }
  if (index.isError || status.isError) {
    return <EmptyState title={copy.unavailable}>{String(index.error ?? status.error)}</EmptyState>;
  }
  if (!status.data) return <EmptyState title={copy.noStatus} />;
  const view = status.data.payload;
  // Absent is not zero. Without a deadline there is nothing to count towards, and the tile
  // has to say so rather than fall back on the frozen published number.
  const remaining = view.next_deadline_utc
    ? countdown(view.next_deadline_utc, now, {
        closed: copy.deadlinePassed,
        day: messages.common.dayShort,
      })
    : null;
  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>
          {copy.kicker(view.tick_contract_version, utcShort(view.now_utc, locale))}
        </div>
        <h1 className={styles.title}>{copy.title}</h1>
      </header>
      <StatRow>
        <Stat
          label={copy.nextGameweek}
          value={view.next_gameweek ?? "—"}
          note={
            view.next_deadline_utc
              ? copy.deadline(local(view.next_deadline_utc, locale))
              : copy.noDeadline
          }
        />
        <Stat
          label={copy.timeToDeadline}
          value={remaining && remaining.text ? remaining.text : copy.deadlineUnknown}
          tone={remaining?.isClosed ? "muted" : "default"}
          note={
            <>
              <div>
                {view.latest_capture ? copy.latestCapture(view.latest_capture) : copy.noCapture}
              </div>
              {view.hours_to_deadline !== null && (
                <div>
                  {copy.atPublish(
                    view.hours_to_deadline.toLocaleString(locale, { maximumFractionDigits: 1 }),
                  )}
                </div>
              )}
            </>
          }
        />
        <Stat
          label={copy.decidedSettled}
          value={`${view.decided_gameweeks.length} · ${view.settled_gameweeks.length}`}
          note={
            view.decided_gameweeks.length
              ? copy.gameweeks(view.decided_gameweeks)
              : copy.nothingDecided
          }
        />
      </StatRow>
      <Card
        title={copy.actionsTitle}
        aside={view.is_idle ? copy.idle : copy.actionCount(view.actions.length)}
      >
        {view.actions.length === 0 ? (
          <span className={styles.muted}>{copy.nothingDue}</span>
        ) : (
          <ul className={styles.actions}>
            {view.actions.map((action, i) => (
              <li key={`${action.kind}-${i}`} className={styles.action}>
                <Badge tone={TONE[action.kind] ?? "neutral"}>
                  {action.kind}
                  {action.gameweek ? ` ${messages.common.gameweekShort(action.gameweek)}` : ""}
                </Badge>
                <span>
                  {reasonText(messages, action.reason_code, action.reason_params, action.reason)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={copy.recent} aside={copy.newest}>
        {view.recent_events.length === 0 ? (
          <span className={styles.muted}>{copy.noLog}</span>
        ) : (
          <ul className={styles.events}>
            {view.recent_events.map((event, i) => (
              <li key={`${event.run_id}-${i}`} className={styles.event}>
                <span className={`${styles.ts} mono`}>{utcShort(event.ts, locale)}</span>
                <span className={`${styles.level} ${event.level === "ERROR" ? styles.error : ""}`}>
                  {event.level}
                </span>
                <span className="mono">{event.message}</span>
                <span className={styles.muted}>
                  {Object.entries(event.fields)
                    .map(
                      ([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`,
                    )
                    .join(" ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
