import { useEffect, useId, useRef, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { EntryView } from "../types";
import { neighbourGaps, placesMoved, type LeagueRace, type RaceLine } from "./leagueRace";
import styles from "./LeagueRaceCard.module.css";

/** Every place has its own row this many pixels apart, whatever the league's size. */
export const RACE_ROW = 20;
/** Every gameweek has its own column; a long season scrolls inside the chart. */
export const RACE_COLUMN = 48;
const LEFT = 32;
const TOP = 14;
const BOTTOM = 26;
const RIGHT = 18;

const x = (index: number) => LEFT + index * RACE_COLUMN;
const y = (place: number) => TOP + (place - 1) * RACE_ROW;

/** The line through a member's places, broken where a week has no place. */
function path(line: RaceLine): string {
  let d = "";
  let drawing = false;
  line.ranks.forEach((place, index) => {
    if (place === null) {
      drawing = false;
      return;
    }
    d += `${drawing ? "L" : "M"}${x(index)} ${y(place)} `;
    drawing = true;
  });
  return d.trim();
}

const signed = (moved: number) => `${moved > 0 ? "+" : "−"}${Math.abs(moved)}`;

/**
 * The league race (#1135): every human member's place after each settled gameweek as one
 * line, one row per place and one column per gameweek, so a league of fifty keeps its lines
 * apart and a long season scrolls sideways inside the chart rather than the page. Tapping a
 * line, or choosing the member, brings that line forward with its weeks marked where a place
 * was gained or lost; stepping through the gameweeks lists whose place changed. Under it,
 * each member's points to the member just ahead and just behind after the latest settled
 * week, the viewer's own row emphasised.
 */
export function LeagueRaceCard({
  race,
  members,
  initialEntry = null,
  viewer = null,
}: {
  race: LeagueRace;
  members: readonly EntryView[];
  /** The member to bring forward first, the viewer where the page knows one. */
  initialEntry?: number | null;
  /** The claimed member, whose own gaps are emphasised; none when the page knows no viewer. */
  viewer?: number | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  const memberId = useId();
  const gapsId = useId();
  const chart = useRef<HTMLDivElement>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const [weekIndex, setWeekIndex] = useState(race.gameweeks.length - 1);
  const highlighted =
    race.lines.find((line) => line.entryId === chosen) ??
    race.lines.find((line) => line.entryId === initialEntry) ??
    race.lines[0]!;
  const week = Math.min(weekIndex, race.gameweeks.length - 1);

  // The latest weeks are the ones a member comes back for, so the chart opens on them.
  useEffect(() => {
    const element = chart.current;
    if (element) element.scrollLeft = element.scrollWidth;
  }, []);

  const names = new Map(
    members.map((member) => [
      member.entry_id,
      member.manager_name ?? member.team_name ?? `#${member.entry_id}`,
    ]),
  );
  const name = (entryId: number) => names.get(entryId) ?? `#${entryId}`;
  const width = LEFT + (race.gameweeks.length - 1) * RACE_COLUMN + RIGHT;
  const height = TOP + (race.places - 1) * RACE_ROW + BOTTOM;
  const moves = race.lines
    .map((line) => ({ line, moved: placesMoved(line, week) }))
    .filter(
      (item): item is { line: RaceLine; moved: number } => item.moved !== null && item.moved !== 0,
    )
    .sort((a, b) => (a.line.ranks[week] ?? 0) - (b.line.ranks[week] ?? 0));
  const others = race.lines.filter((line) => line !== highlighted);
  const gaps = neighbourGaps(race);
  const count = (value: number) => points(value, 0, locale);

  return (
    <section className={styles.race} aria-labelledby={titleId}>
      <h2 className={styles.title} id={titleId}>
        {copy.raceTitle}
      </h2>

      <div className={styles.controls}>
        <label className={styles.memberPick} htmlFor={memberId}>
          <span>{copy.raceMember}</span>
          <select
            id={memberId}
            value={highlighted.entryId}
            onChange={(event) => setChosen(Number(event.target.value))}
          >
            {race.lines.map((line) => (
              <option key={line.entryId} value={line.entryId}>
                {name(line.entryId)}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.stepper}>
          <button
            type="button"
            className={styles.step}
            aria-label={copy.racePrevious}
            disabled={week === 0}
            onClick={() => setWeekIndex(week - 1)}
          >
            ‹
          </button>
          <span className={`${styles.weekLabel} num`} aria-live="polite">
            {copy.raceWeek(race.gameweeks[week]!)}
          </span>
          <button
            type="button"
            className={styles.step}
            aria-label={copy.raceNext}
            disabled={week === race.gameweeks.length - 1}
            onClick={() => setWeekIndex(week + 1)}
          >
            ›
          </button>
        </div>
      </div>

      <div className={styles.chart} ref={chart}>
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={copy.raceChart(name(highlighted.entryId))}
        >
          <rect
            className={styles.guide}
            x={-RACE_COLUMN / 2}
            y={0}
            width={RACE_COLUMN}
            height={height - BOTTOM + 6}
            style={{ transform: `translateX(${x(week)}px)` }}
          />
          {Array.from({ length: race.places }, (_, index) => (
            <text
              key={index}
              className={styles.place}
              x={LEFT - 12}
              y={y(index + 1)}
              data-place={index + 1}
            >
              {index + 1}
            </text>
          ))}
          {race.gameweeks.map((gameweek, index) => (
            <text key={gameweek} className={styles.gameweek} x={x(index)} y={height - 6}>
              {gameweek}
            </text>
          ))}
          {[...others, highlighted].map((line) => (
            <g
              key={line.entryId}
              className={styles.member}
              data-entry={line.entryId}
              data-highlighted={line === highlighted ? "" : undefined}
              onClick={() => setChosen(line.entryId)}
            >
              <path className={styles.hit} d={path(line)} />
              <path className={styles.line} d={path(line)} />
            </g>
          ))}
          {highlighted.ranks.map((place, index) => {
            if (place === null) return null;
            const moved = placesMoved(highlighted, index);
            const kind = moved === null || moved === 0 ? undefined : moved > 0 ? "gained" : "lost";
            return (
              <circle
                key={index}
                className={styles.mark}
                cx={x(index)}
                cy={y(place)}
                r={kind ? 5 : 3}
                data-move={kind}
              />
            );
          })}
        </svg>
      </div>

      <div className={styles.week}>
        <h3 className={styles.weekTitle}>{copy.raceMoved}</h3>
        {week === 0 ? (
          <p className={styles.quiet}>{copy.raceFirstWeek}</p>
        ) : moves.length === 0 ? (
          <p className={styles.quiet}>{copy.raceNoMoves}</p>
        ) : (
          <ul className={styles.moves}>
            {moves.map(({ line, moved }) => (
              <li key={line.entryId} data-move={moved > 0 ? "gained" : "lost"}>
                <span>
                  {copy.raceMove(name(line.entryId), line.ranks[week - 1]!, line.ranks[week]!)}
                </span>
                <span className={`${styles.moved} num`}>{signed(moved)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.table}>
        <table>
          <caption>{name(highlighted.entryId)}</caption>
          <thead>
            <tr>
              <th scope="row">{copy.raceGameweek}</th>
              {race.gameweeks.map((gameweek) => (
                <th key={gameweek} scope="col" className="num">
                  {gameweek}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{copy.racePlaces}</th>
              {highlighted.ranks.map((place, index) => (
                <td key={index} className="num">
                  {place ?? "-"}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">{copy.racePoints}</th>
              {highlighted.totals.map((total, index) => (
                <td key={index} className="num">
                  {total ?? "-"}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {/* The latest settled week's gaps, whichever week the stepper is on; a lone member
          has no neighbour to measure against. */}
      {gaps.length > 1 ? (
        <div className={styles.week}>
          <h3 className={styles.weekTitle} id={gapsId}>
            {copy.raceGaps(race.gameweeks[race.gameweeks.length - 1]!)}
          </h3>
          <ol className={styles.gaps} aria-labelledby={gapsId}>
            {gaps.map((gap) => {
              const own = gap.entryId === viewer;
              return (
                <li key={gap.entryId} aria-current={own ? "true" : undefined}>
                  <span className={`${styles.gapPlace} num`}>{gap.place}</span>
                  <span className={styles.gapName}>
                    {name(gap.entryId)}
                    {own ? ` · ${copy.viewerYouBadge}` : null}
                  </span>
                  <span className={styles.gapFigures}>
                    {gap.ahead !== null ? (
                      <span data-gap="ahead">
                        {gap.ahead === 0
                          ? copy.raceLevelAhead
                          : copy.raceGapAhead(count(gap.ahead))}
                      </span>
                    ) : null}
                    {gap.behind !== null ? (
                      <span data-gap="behind">
                        {gap.behind === 0
                          ? copy.raceLevelBehind
                          : copy.raceGapBehind(count(gap.behind))}
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
