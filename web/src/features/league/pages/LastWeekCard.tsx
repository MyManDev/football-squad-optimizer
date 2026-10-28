import { Link } from "react-router";

import { Badge, type BadgeTone } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import type { LastWeekResult } from "./lastWeekResult";
import styles from "./LastWeekCard.module.css";

/**
 * The member's latest finished week, one card above this week's decisions: the gameweek,
 * marked provisional as the scoreboard marks a finished week nobody has data-checked yet,
 * the member's net that week and how it stands against the league's mean, what the
 * published suggestion scored beside it, then a row of the other figures the published
 * files state for it (the rank movement, the league's mean and the game's average). A
 * figure no file states has no line; nothing stands in for it.
 */
export function LastWeekCard({
  result,
  historyHref,
}: {
  result: LastWeekResult;
  /** The member's history page, offered when the history holds this week's score. */
  historyHref: string | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const scoreboard = messages.leagueScoreboard;
  // A whole figure is written whole, as the scoreboard writes the week; anything else to one
  // decimal, so no figure reads rounder than the file states it.
  const figure = (value: number) => points(value, Number.isInteger(value) ? 0 : 1, locale);
  // The difference is taken from the mean as printed, so the two figures on the card add up.
  const against =
    result.leagueMean === null
      ? null
      : Math.round((result.net - Math.round(result.leagueMean.mean * 10) / 10) * 10) / 10;
  const tone: BadgeTone =
    against === null || against === 0 ? "neutral" : against > 0 ? "good" : "bad";
  const movement = result.movement;
  const cells = [
    movement === null
      ? null
      : {
          key: "movement",
          label: copy.lastWeekMovement,
          value: copy.movementLabel(movement.movement, movement.places),
          sub: null,
        },
    result.leagueMean === null
      ? null
      : {
          key: "mean",
          label: copy.lastWeekLeagueMean,
          value: points(result.leagueMean.mean, 1, locale),
          sub: copy.lastWeekMembers(result.leagueMean.counted),
        },
    result.gameAverage === null
      ? null
      : {
          key: "average",
          label: scoreboard.average,
          value: figure(result.gameAverage),
          sub: null,
        },
  ].filter((cell) => cell !== null);

  return (
    <div className={styles.enter} data-last-week={result.gameweek}>
      <Card
        title={result.previous ? copy.lastWeekTitle : copy.latestWeekTitle}
        aside={
          <span className={styles.aside}>
            <span className={styles.week}>{messages.common.gameweekShort(result.gameweek)}</span>
            {result.provisional ? <Badge tone="warn">{scoreboard.provisional}</Badge> : null}
          </span>
        }
      >
        <div className={styles.headline}>
          <p className={styles.score}>
            <span className={`${styles.figure} num`}>{figure(result.net)}</span>
            <span className={styles.unit}>{copy.lastWeekNet}</span>
          </p>
          {against === null ? null : (
            <Badge tone={tone}>{copy.lastWeekAgainstMean(signedPoints(against, 1, locale))}</Badge>
          )}
        </div>
        {/* The suggestion the history scores is the one-week pure-points plan the site
            published before the deadline, so the line names it. */}
        {result.suggested === null ? null : (
          <p className={styles.suggested} data-line="suggested">
            <span>{copy.lastWeekSuggested(figure(result.suggested))}</span>{" "}
            <span className={styles.plan}>
              {copy.strategies["saf-puan"].name} · {messages.decision.week(1)}
            </span>
          </p>
        )}
        {cells.length > 0 ? (
          <dl className={styles.facts}>
            {cells.map((cell) => (
              <div key={cell.key} className={styles.fact} data-fact={cell.key}>
                <dt>{cell.label}</dt>
                <dd className="num">{cell.value}</dd>
                {cell.sub ? <dd className={styles.sub}>{cell.sub}</dd> : null}
              </div>
            ))}
          </dl>
        ) : null}
        {result.provisional ? <p className={styles.note}>{scoreboard.provisionalNote}</p> : null}
        {historyHref ? (
          <Link className={styles.more} to={historyHref}>
            {copy.lastWeekDetails}
          </Link>
        ) : null}
      </Card>
    </div>
  );
}
