import { Card } from "../../design/components/Card";
import { Stat, StatRow } from "../../design/components/Stat";
import { useLanguage } from "../../i18n/context";
import type { LiveWeekScore } from "./officialScoring";
import styles from "./MemberLiveScoreCard.module.css";

const COPY = {
  tr: {
    title: (week: number) => `${week}. hafta puanın`,
    net: "Net puan",
    hit: "Transfer cezası",
    matches: "Maçlar",
    bonusDone: "Bonus eklendi",
    bonusPending: "Bonus bekleniyor",
    captain: "Kaptan",
    none: "Yok",
    substitutions: "Otomatik değişiklikler",
    out: "Çıkan",
    incoming: "Giren",
    updated: "Veri zamanı",
    refresh: "Yenile",
    refreshing: "Yenileniyor",
  },
  en: {
    title: (week: number) => `Your gameweek ${week} score`,
    net: "Net points",
    hit: "Transfer hit",
    matches: "Matches",
    bonusDone: "Bonus added",
    bonusPending: "Bonus pending",
    captain: "Captain",
    none: "None",
    substitutions: "Automatic substitutions",
    out: "Out",
    incoming: "In",
    updated: "Data time",
    refresh: "Refresh",
    refreshing: "Refreshing",
  },
};

/** Display only. The source adapter owns loading; neither score nor refresh is recorded here. */
export function MemberLiveScoreCard({
  gameweek,
  score,
  names,
  onRefresh,
  refreshing = false,
}: {
  gameweek: number;
  score: LiveWeekScore | null;
  /** Names resolved from the same season's element ids. */
  names: ReadonlyMap<number, string>;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  if (
    score === null ||
    score.refused ||
    !Number.isInteger(gameweek) ||
    gameweek < 1 ||
    gameweek > 38
  )
    return null;
  const shown = [...score.autosubs.flat(), ...(score.captain === null ? [] : [score.captain])];
  if (shown.some((id) => !names.get(id)?.trim())) return null;
  const time = new Date(score.source_time);
  if (!Number.isFinite(time.valueOf())) return null;
  const integer = (value: number) => value.toLocaleString(locale);
  return (
    <div data-member-live-score>
      <Card
        title={copy.title(gameweek)}
        aside={
          onRefresh && (
            <button
              className={styles.refresh}
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? copy.refreshing : copy.refresh}
            </button>
          )
        }
      >
        <StatRow>
          <Stat label={copy.net} value={integer(score.net)} tone="accent" />
          <Stat label={copy.hit} value={integer(score.transfer_cost)} />
          <Stat
            label={copy.matches}
            value={`${integer(score.fixtures_finished)} / ${integer(score.fixtures_total)}`}
          />
        </StatRow>
        <p className={styles.bonus}>{score.bonus_confirmed ? copy.bonusDone : copy.bonusPending}</p>
        <dl className={styles.details}>
          <div>
            <dt>{copy.captain}</dt>
            <dd>{score.captain === null ? copy.none : names.get(score.captain)}</dd>
          </div>
          <div>
            <dt>{copy.updated}</dt>
            <dd>
              <time dateTime={score.source_time}>
                {time.toLocaleString(locale, {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZoneName: "short",
                })}
              </time>
            </dd>
          </div>
        </dl>
        <div className={styles.substitutions}>
          <h3>{copy.substitutions}</h3>
          {score.autosubs.length === 0 ? (
            <p>{copy.none}</p>
          ) : (
            <ul>
              {score.autosubs.map(([out, incoming]) => (
                <li key={`${out}:${incoming}`}>
                  <span>
                    <small>{copy.out}</small> {names.get(out)}
                  </span>
                  <span aria-hidden="true">→</span>
                  <span>
                    <small>{copy.incoming}</small> {names.get(incoming)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
