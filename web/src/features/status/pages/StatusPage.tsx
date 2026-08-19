import { useIndex, useStatus } from "../../../data/queries";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { local, utcShort } from "../../../lib/format";
import styles from "./StatusPage.module.css";

const TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "accent"> = {
  capture: "accent",
  decide: "good",
  settle: "good",
  wait: "neutral",
};

export function StatusPage() {
  const index = useIndex();
  const season = index.data?.payload.seasons[0];
  const status = useStatus(season);
  if (index.isPending || (season && status.isPending)) {
    return <EmptyState title="Loading the tick status…" />;
  }
  if (index.isError || status.isError) {
    return (
      <EmptyState title="Status is not available.">
        {String(index.error ?? status.error)}
      </EmptyState>
    );
  }
  if (!status.data) return <EmptyState title="No status recorded." />;
  const view = status.data.payload;
  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>
          season tick · {view.tick_contract_version} · as of {utcShort(view.now_utc)}
        </div>
        <h1 className={styles.title}>Status</h1>
      </header>
      <StatRow>
        <Stat
          label="next gameweek"
          value={view.next_gameweek ?? "—"}
          note={
            view.next_deadline_utc
              ? `deadline ${local(view.next_deadline_utc)}`
              : "no open deadline in the latest capture"
          }
        />
        <Stat
          label="hours to deadline"
          value={view.hours_to_deadline !== null ? view.hours_to_deadline.toFixed(1) : "—"}
          note={view.latest_capture ? `latest capture ${view.latest_capture}` : "no capture held"}
        />
        <Stat
          label="decided · settled"
          value={`${view.decided_gameweeks.length} · ${view.settled_gameweeks.length}`}
          note={
            view.decided_gameweeks.length
              ? `GW ${view.decided_gameweeks.join(", ")}`
              : "nothing decided yet"
          }
        />
      </StatRow>
      <Card
        title="What the tick would do now"
        aside={view.is_idle ? "idle" : `${view.actions.length} action(s)`}
      >
        {view.actions.length === 0 ? (
          <span className={styles.muted}>Nothing is due.</span>
        ) : (
          <ul className={styles.actions}>
            {view.actions.map((action, i) => (
              <li key={`${action.kind}-${i}`} className={styles.action}>
                <Badge tone={TONE[action.kind] ?? "neutral"}>
                  {action.kind}
                  {action.gameweek ? ` GW${action.gameweek}` : ""}
                </Badge>
                <span>{action.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Recent run log" aside="newest first">
        {view.recent_events.length === 0 ? (
          <span className={styles.muted}>
            No run log yet — the tick has not run on this machine.
          </span>
        ) : (
          <ul className={styles.events}>
            {view.recent_events.map((event, i) => (
              <li key={`${event.run_id}-${i}`} className={styles.event}>
                <span className={`${styles.ts} mono`}>{utcShort(event.ts)}</span>
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
