import { useLiveScore } from "../../../data/queries";
import type { RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import styles from "./LiveScoreCard.module.css";

/** A capture older than one hour is marked old; this promises no capture cadence. */
export function LiveScoreCard({ view, now }: { view: RecommendationView; now: Date }) {
  const { locale, messages } = useLanguage();
  const copy = messages.squad;
  const live = useLiveScore(view.season, view.gameweek, !view.settled);
  if (view.settled || now.getTime() < Date.parse(view.deadline_utc)) return null;
  const data = live.data?.payload;
  const matches =
    data?.season === view.season &&
    data?.gameweek === view.gameweek &&
    data.decision_snapshot_id === view.snapshot_id &&
    data.prediction_fingerprint === view.prediction_fingerprint;
  const captured = data?.captured_at_utc;
  const age = captured ? now.getTime() - Date.parse(captured) : Number.NaN;
  const available = matches && data?.status === "available" && age >= 0;
  const stale = age > 60 * 60 * 1000;
  const timestamp = (value: string) =>
    new Date(value).toLocaleString(locale, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  return (
    <Card
      title={copy.liveTitle}
      aside={
        <Badge tone="neutral">
          {available ? (stale ? copy.liveStale : copy.liveProvisional) : copy.liveUnavailable}
        </Badge>
      }
    >
      {available ? (
        <>
          <StatRow>
            <Stat
              label={copy.liveNamed}
              value={points(data.named_score!, 0, locale)}
              note={copy.liveRule}
            />
            <Stat
              label={copy.liveNet}
              value={points(data.net_score!, 0, locale)}
              note={copy.liveHit(points(data.transfer_hit_points!, 0, locale))}
            />
            <Stat
              label={copy.liveFixtures}
              value={`${data.fixtures_finished} / ${data.fixtures_total}`}
              note={data.bonus_confirmed ? copy.liveBonusConfirmed : copy.liveBonusPending}
            />
          </StatRow>
          <p className={styles.note}>{copy.liveSnapshotNote}</p>
          <div className={styles.provenance}>
            <p className={styles.note}>
              {copy.liveCaptured} <time dateTime={captured!}>{timestamp(captured!)}</time> ·{" "}
              {data.source_snapshot_id}
            </p>
            <p className={styles.note}>
              {copy.generated}{" "}
              <time dateTime={live.data!.generatedAtUtc}>
                {timestamp(live.data!.generatedAtUtc)}
              </time>
            </p>
          </div>
        </>
      ) : (
        <p className={styles.note}>{live.isFetching ? copy.loading : copy.liveUnavailableNote}</p>
      )}
    </Card>
  );
}
