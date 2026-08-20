import { useIndex, useStatus } from "../../../data/queries";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { local, utcShort } from "../../../lib/format";
import styles from "./StatusPage.module.css";

const TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "accent"> = {
  capture: "accent",
  decide: "good",
  settle: "good",
  wait: "neutral",
};

export function StatusPage() {
  const { locale, messages } = useLanguage();
  const copy = messages.status;
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
          label={copy.hours}
          value={
            view.hours_to_deadline !== null
              ? view.hours_to_deadline.toLocaleString(locale, { maximumFractionDigits: 1 })
              : "—"
          }
          note={view.latest_capture ? copy.latestCapture(view.latest_capture) : copy.noCapture}
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
                <span>{action.reason}</span>
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
