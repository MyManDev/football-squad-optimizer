import { useEffect, useId, useRef } from "react";

import { CloseIcon } from "../../../design/shell/icons";
import { FIXTURE_SHEET_ID, useShell } from "../../../design/shell/ShellContext";
import { useLanguage } from "../../../i18n/context";
import { clubCode, type ClubCodes } from "../../../lib/clubs";
import type { FixturesPayload } from "../../fixtures/types";
import { clubWeeks, listedWeeks, meetings, nextThree, type ClubWeek } from "../clubFixtures";
import type { AdviceMove } from "../types";
import styles from "./MemberFixtureRail.module.css";

/** A player of the eleven as the rail lists them. */
export interface RailPlayer {
  playerId: number;
  name: string;
  shortName: string;
  team: string;
  captain: boolean;
}

/**
 * Where the rail stands: a column of its own beside the page from 1180 px, in the page
 * next to the squad on a tablet, and a sheet over the page on a phone.
 */
export type RailPlacement = "column" | "flow" | "sheet";

function ShortName({ name, shortName }: { name: string; shortName: string }) {
  const short = shortName.trim() || name;
  if (short === name) return <span className={styles.name}>{name}</span>;
  return (
    <span className={styles.name}>
      <span aria-hidden="true">{short}</span>
      <span className="visually-hidden">{name}</span>
    </span>
  );
}

/** One club's gameweek: every opponent of a double week, or 'no match' in a blank one. */
function WeekCell({ week }: { week: ClubWeek | null }) {
  const copy = useLanguage().messages.leagueMembers;
  if (!week) return <td className={styles.cell} />;
  return (
    <td className={styles.cell}>
      {week.matches.length === 0 ? (
        <span className={styles.fixture} data-venue="none">
          {copy.fixtureNone}
        </span>
      ) : (
        week.matches.map((match, index) => (
          <span
            key={`${match.opponent}-${index}`}
            className={styles.fixture}
            data-venue={match.home ? "home" : "away"}
          >
            <span className={styles.opponent}>{match.opponent}</span>{" "}
            <span className={styles.venue}>{match.home ? copy.fixtureHome : copy.fixtureAway}</span>
          </span>
        ))
      )}
    </td>
  );
}

function WeekHead({ weeks }: { weeks: readonly number[] }) {
  const copy = useLanguage().messages.leagueMembers;
  return (
    <thead>
      <tr>
        {/* Drawn as 'hafta 6 7 8'; named for a screen reader as the player column and
            the gameweeks. */}
        <th scope="col" className={styles.weekLabel} aria-label={copy.railPlayer}>
          {copy.railWeekHead}
        </th>
        {weeks.map((week) => (
          <th
            key={week}
            scope="col"
            className={styles.weekNumber}
            aria-label={copy.railWeekColumn(week)}
          >
            {week}
          </th>
        ))}
      </tr>
    </thead>
  );
}

/**
 * The member's fixtures beside the decision: the transfers' clubs, the eleven's clubs and
 * the eleven's players who face each other, for the plan's gameweek and the two after it.
 *
 * Everything is read from the published fixture calendar and joined to the players by
 * club. A home match is a filled cell and an away match an outlined one, and that is the
 * only encoding: no difficulty is rated or coloured. A week the calendar does not list is
 * left out; a blank week says so; with no calendar the rail says that and nothing else.
 *
 * On a phone it is a sheet over the page, opened from the phone bar through the shell: it
 * is a modal dialog while open, takes focus to its close button, and the shell locks and
 * makes inert the page behind it and closes it on Escape or the scrim.
 */
export function MemberFixtureRail({
  placement,
  fixtures,
  season,
  gameweek,
  moves,
  eleven,
  codes,
}: {
  placement: RailPlacement;
  fixtures: FixturesPayload | null;
  season: string;
  gameweek: number;
  moves: readonly AdviceMove[];
  eleven: readonly RailPlayer[];
  codes: ClubCodes;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const shell = useShell();
  const titleId = useId();
  const transfersId = useId();
  const elevenId = useId();
  const meetId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const register = shell?.registerSheet;
  const setSheetOpen = shell?.setSheetOpen;
  const sheet = placement === "sheet";
  const open = sheet && shell?.sheetOpen === true;

  // The phone bar's 'Fikstür' opens this page's sheet for as long as the page shows one.
  useEffect(() => register?.(), [register]);

  // Focus moves to the close button once the shell has noted where it came from.
  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  const weeks = listedWeeks(fixtures, season, nextThree(gameweek));
  const weeksOf = (team: string) => clubWeeks(fixtures, season, team, weeks, codes);
  const pairs = weeks.includes(gameweek) ? meetings(fixtures, season, gameweek, eleven, codes) : [];
  const names = (players: readonly RailPlayer[]) =>
    players.map((player) => player.shortName.trim() || player.name).join(", ");

  // An aside beside the page; on a phone a dialog over it, which an aside may not be.
  const Region = sheet ? "div" : "aside";
  return (
    <Region
      id={FIXTURE_SHEET_ID}
      className={styles.rail}
      data-placement={placement}
      data-open={open ? "true" : undefined}
      data-mark="rail"
      aria-labelledby={sheet && !open ? undefined : titleId}
      role={open ? "dialog" : undefined}
      aria-modal={open ? true : undefined}
      // A column that scrolls on its own must be reachable from the keyboard.
      tabIndex={placement === "column" ? 0 : undefined}
    >
      <div className={styles.head}>
        <h2 className={styles.title} id={titleId}>
          {messages.shell.fixtures}
        </h2>
        {weeks.length > 0 ? <span className={styles.weeks}>{copy.railWeeks(weeks)}</span> : null}
        {sheet ? (
          <button
            ref={closeRef}
            type="button"
            className={styles.close}
            aria-label={messages.shell.closeFixtures}
            onClick={() => setSheetOpen?.(false)}
          >
            <CloseIcon />
          </button>
        ) : null}
      </div>
      <div className={styles.body}>
        {!fixtures ? (
          <p className={styles.quiet}>{copy.railNoCalendar}</p>
        ) : weeks.length === 0 ? (
          <p className={styles.quiet}>{copy.railNoWeeks}</p>
        ) : (
          <>
            {moves.length > 0 ? (
              <section
                className={styles.block}
                aria-labelledby={transfersId}
                data-mark="rail-transfers"
              >
                <h3 className={styles.blockTitle} id={transfersId}>
                  {copy.railTransfers}
                </h3>
                <table className={`${styles.grid} ${styles.transfers}`}>
                  <WeekHead weeks={weeks} />
                  {moves.map((move) => (
                    <tbody key={move.move_id} className={styles.pair}>
                      {(["out", "in"] as const).map((kind) => {
                        const player = kind === "out" ? move.player_out : move.player_in;
                        return (
                          <tr key={kind}>
                            <th scope="row">
                              <span className={styles.player}>
                                <span className={styles.tag} data-kind={kind}>
                                  {kind === "out" ? copy.out : copy.in}
                                </span>
                                {player ? (
                                  <>
                                    <ShortName name={player.name} shortName={player.short_name} />
                                    <span className={styles.club}>
                                      {clubCode(player.team, codes) ?? player.team}
                                    </span>
                                  </>
                                ) : (
                                  <span className={styles.name}>
                                    {messages.suggestionHistory.unknownPlayer}
                                  </span>
                                )}
                              </span>
                            </th>
                            {player
                              ? weeksOf(player.team).map((week, index) => (
                                  <WeekCell key={weeks[index]} week={week} />
                                ))
                              : weeks.map((week) => <td key={week} className={styles.cell} />)}
                          </tr>
                        );
                      })}
                    </tbody>
                  ))}
                </table>
              </section>
            ) : null}
            {eleven.length > 0 ? (
              <section className={styles.block} aria-labelledby={elevenId} data-mark="rail-xi">
                <h3 className={styles.blockTitle} id={elevenId}>
                  {copy.railXi}
                </h3>
                <table className={styles.grid}>
                  <WeekHead weeks={weeks} />
                  <tbody>
                    {eleven.map((player) => (
                      <tr key={player.playerId}>
                        <th scope="row">
                          <span className={styles.player}>
                            <ShortName name={player.name} shortName={player.shortName} />
                            <span className={styles.club}>
                              {clubCode(player.team, codes) ?? player.team}
                            </span>
                            {player.captain ? (
                              <>
                                <span className={styles.captain} aria-hidden="true">
                                  {copy.captainMark}
                                </span>
                                <span className="visually-hidden">
                                  {messages.squad.captainLabel}
                                </span>
                              </>
                            ) : null}
                          </span>
                        </th>
                        {weeksOf(player.team).map((week, index) => (
                          <WeekCell key={weeks[index]} week={week} />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ) : null}
            {eleven.length > 0 && weeks.includes(gameweek) ? (
              <section className={styles.block} aria-labelledby={meetId}>
                <h3 className={styles.blockTitle} id={meetId}>
                  {copy.railMeet(gameweek)}
                </h3>
                {pairs.length > 0 ? (
                  <ul className={styles.meetings}>
                    {pairs.map((pair) => (
                      <li key={`${pair.home}-${pair.away}`}>
                        <span className={styles.match}>
                          {pair.home} - {pair.away}
                        </span>
                        <span className={styles.who}>
                          {names(pair.homePlayers)} / {names(pair.awayPlayers)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.quiet}>{copy.railMeetNone}</p>
                )}
              </section>
            ) : null}
            <p className={styles.legend}>
              {copy.railLegendVenue}
              <br />
              {copy.railLegendDifficulty}
            </p>
          </>
        )}
      </div>
    </Region>
  );
}
