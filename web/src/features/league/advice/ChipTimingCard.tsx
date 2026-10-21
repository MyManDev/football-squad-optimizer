/**
 * The chip timing card (#1003): for each chip the member holds in the current half, when
 * the measured rule plays it, read on the member's own device in every league.
 *
 * The reading is the device's (`device/chipForecast`), from the table and the chip gains
 * the plain plan's run solved, the squad on the page and the calendar the page already
 * reads. Its rows follow the game's one chip per gameweek (`chipTimingRows`). A refused
 * reading, or one with no row to show, draws nothing at all.
 */

import { useMemo } from "react";

import { useLanguage } from "../../../i18n/context";
import { signedPoints } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { PointsUnit } from "../components/PointsUnit";
import { chipTimingRows, type ChipTimingRow } from "../device/chipForecast/display";
import { memberChipForecast, memberNextPointsAt } from "../device/chipForecast/member";
import type { DeviceChipTiming } from "../device/useDevicePlan";
import type { EntrySquad } from "../types";
import { CHIP_TIMING_COPY } from "./chipTimingCopy";
import styles from "./ChipTimingCard.module.css";

/** The rows the card shows, or none where the reading is refused or names no row. */
function chipTimingRowsFor(
  squad: EntrySquad,
  timing: DeviceChipTiming | null | undefined,
  fixtures: FixturesPayload | null | undefined,
): ChipTimingRow[] {
  if (!timing) return [];
  const inputs = { table: timing.table, squad, fixtures, gains: timing.gains };
  const reading = memberChipForecast(inputs);
  if (reading.status !== "available" || reading.forecast === null) return [];
  return chipTimingRows(reading.forecast, (name, after) => memberNextPointsAt(inputs, name, after));
}

export function ChipTimingCard({
  squad,
  timing,
  fixtures,
}: {
  squad: EntrySquad;
  /** What the device's plain plan run solved for the chip timing; nothing before it ran. */
  timing: DeviceChipTiming | null | undefined;
  fixtures: FixturesPayload | null | undefined;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = CHIP_TIMING_COPY[language];
  const rows = useMemo(() => chipTimingRowsFor(squad, timing, fixtures), [squad, timing, fixtures]);
  if (rows.length === 0) return null;
  // The Triple Captain's player by the name the page already shows for them.
  const names = new Map(
    [...squad.starting_xi, ...squad.bench].map((player) => [player.player_id, player.name]),
  );
  const points = (value: number) => (
    <span className={styles.points}>
      {signedPoints(value, 1, locale)} <PointsUnit />
    </span>
  );
  return (
    <section className={styles.card} aria-labelledby="chip-timing-title" data-chip-timing>
      <h3 className={styles.title} id="chip-timing-title">
        {copy.title}
      </h3>
      <dl className={styles.rows}>
        {rows.map(({ name, when }) => {
          const captain =
            name === "3xc" && when.kind === "gameweek" && when.playerIds.length > 0
              ? names.get(when.playerIds[0]!)
              : undefined;
          return (
            <div className={styles.row} key={name} data-chip={name}>
              <dt>{messages.leagueMembers.chipNames[name] ?? name}</dt>
              <dd>
                {when.kind === "this-week" ? (
                  <>
                    {copy.thisWeek}, {points(when.gain)}
                  </>
                ) : when.kind === "gameweek" ? (
                  <>
                    {copy.gameweek(when.gameweek)}, {points(when.gain)}
                    {captain !== undefined ? (
                      <>
                        {" "}
                        <span className={styles.player}>{copy.captain(captain)}</span>
                      </>
                    ) : null}
                  </>
                ) : (
                  copy.notThisWeek(when.lastGameweek)
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
