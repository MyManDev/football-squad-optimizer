import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { figure, signedPoints } from "../../../lib/format";
import { PointsUnit } from "../components/PointsUnit";
import type { EntrySquad, EntryView, LeagueViewEnvelope } from "../types";
import { duelOf, type DuelSide } from "./duelSides";
import styles from "./RivalDuel.module.css";

function nameOf(entry: { team_name: string | null; manager_name: string | null }, id: number) {
  return entry.team_name ?? entry.manager_name ?? `#${id}`;
}

function Side({
  side,
  title,
  shared,
}: {
  side: DuelSide;
  title: string;
  shared: ReadonlySet<number>;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  const position = (code: string) =>
    Object.hasOwn(messages.positions, code)
      ? messages.positions[code as keyof typeof messages.positions]
      : code;
  return (
    <section className={styles.side} aria-labelledby={titleId}>
      <h3 className={styles.sideTitle} id={titleId}>
        <span className={styles.team}>{title}</span>
        <span className={`${styles.total} num`}>
          {figure(side.total, locale)} <PointsUnit />
        </span>
      </h3>
      <ol className={styles.eleven}>
        {side.eleven.map((player) => {
          const both = shared.has(player.player_id);
          return (
            <li
              key={player.player_id}
              className={styles.player}
              data-shared={both ? "" : undefined}
            >
              <span className={styles.position}>{position(player.position)}</span>
              <span className={styles.name}>{player.short_name || player.name}</span>
              {player.is_captain ? (
                <>
                  <span className={styles.captain} aria-hidden="true">
                    {copy.captainMark}
                  </span>
                  <span className="visually-hidden">{messages.squad.captainLabel}</span>
                </>
              ) : null}
              {both ? <span className="visually-hidden">{copy.duelSharedMark}</span> : null}
              <span className={`${styles.points} num`}>
                {figure(player.expected_points, locale)}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/**
 * The member's eleven beside one rival's (#1133), both from this capture's entry documents:
 * the players both start are dimmed, the ones only one side starts stand out, and the strip
 * between them gives the expected-points difference with what the differing players and
 * the two captains each make of it. The rival changes with one tap and the layout stays;
 * on a phone the two elevens stack with the strip between them.
 */
export function RivalDuel({
  squad,
  candidates,
  selected,
  rival,
  issue,
  onSelect,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  /** The other human members, in the league table's order. */
  candidates: EntryView[];
  selected: number | null;
  rival: LeagueViewEnvelope<EntrySquad> | null;
  issue?: "loading" | "missing" | "unreadable";
  onSelect: (entryId: number) => void;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const pickId = useId();
  const duel = rival ? duelOf(squad, rival) : null;
  const own = squad.payload.entry;

  return (
    <div className={styles.duel}>
      <p className="visually-hidden" id={pickId}>
        {copy.duelPick}
      </p>
      <div className={styles.picker} role="group" aria-labelledby={pickId}>
        {candidates.map((member) =>
          member.entry_id === null ? null : (
            <button
              key={member.entry_id}
              type="button"
              className={styles.pick}
              aria-pressed={member.entry_id === selected}
              onClick={() => onSelect(member.entry_id!)}
            >
              {nameOf(member, member.entry_id)}
            </button>
          ),
        )}
      </div>
      {selected === null ? null : issue === "loading" ? (
        <p className={styles.state}>{copy.duelLoading}</p>
      ) : issue === "missing" ? (
        <p className={styles.state}>{copy.duelMissing}</p>
      ) : issue === "unreadable" ? (
        <p className={styles.state}>{copy.duelUnreadable}</p>
      ) : !rival ? null : !duel ? (
        <p className={styles.state}>{copy.duelMissing}</p>
      ) : (
        <div className={styles.board} data-duel={duel.rival.entryId}>
          <Side side={duel.member} title={nameOf(own, own.entry_id)} shared={duel.shared} />
          <dl className={styles.strip}>
            <div className={styles.headline}>
              <dt>{copy.duelDifference}</dt>
              <dd className="num">
                {signedPoints(duel.difference, 1, locale)} <PointsUnit />
              </dd>
            </div>
            <div className={styles.part}>
              <dt>{copy.duelFromPlayers}</dt>
              <dd className="num">{signedPoints(duel.fromPlayers, 1, locale)}</dd>
            </div>
            <div className={styles.part}>
              <dt>{copy.duelFromCaptains}</dt>
              <dd>
                <span className={styles.captains}>
                  {duel.member.captain.short_name || duel.member.captain.name}
                  {" · "}
                  {duel.rival.captain.short_name || duel.rival.captain.name}
                </span>{" "}
                <span className="num">{signedPoints(duel.fromCaptains, 1, locale)}</span>
              </dd>
            </div>
            <div className={styles.part}>
              <dt className="visually-hidden">{copy.duelSharedMark}</dt>
              <dd>{copy.duelShared(duel.shared.size)}</dd>
            </div>
          </dl>
          <Side
            side={duel.rival}
            title={nameOf(rival!.payload.entry, duel.rival.entryId)}
            shared={duel.shared}
          />
        </div>
      )}
    </div>
  );
}
