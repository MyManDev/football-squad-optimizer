import { useId, type CSSProperties } from "react";

import { useLanguage } from "../../../i18n/context";
import { clubCode, clubSwatch, type ClubCodes } from "../../../lib/clubs";
import { figure } from "../../../lib/format";
import styles from "./MemberPitch.module.css";

/** One player as the pitch draws them: a white name plate on the grass. */
export interface PitchPlayer {
  playerId: number;
  name: string;
  shortName: string;
  /** The published position code: GK, DEF, MID or FWD. */
  position: string;
  team: string;
  /** Expected points; null where the document states none, which is never drawn as 0. */
  expectedPoints: number | null;
  captain: boolean;
  vice: boolean;
  /** Arrives with this plan's transfers. */
  isNew: boolean;
}

const LINES = ["GK", "DEF", "MID", "FWD"] as const;

/** Vertical distance between plate centres in a line of `count`, horizontal layout. */
function lineStep(count: number): number {
  return count <= 3 ? 68 : count === 4 ? 56 : 50;
}

/** A line of `count` plates from the first top edge to the last bottom edge. */
function lineSpan(count: number): number {
  return count <= 1 ? 40 : (count - 1) * lineStep(count) + 40;
}

/**
 * The height of the horizontal pitch: 256 px as drawn for up to four in a line, taller
 * for a line of five, and taller again when the defence is too crowded for the direction
 * of attack to sit under its first player and it has to sit under the whole line.
 */
function horizontalHeight(counts: readonly number[], defenders: number): number {
  const widest = Math.max(1, ...counts);
  return Math.max(256, lineSpan(widest) + 48, defenders >= 4 ? lineSpan(defenders) + 76 : 0);
}

function ArrowIcon() {
  return (
    <svg
      className={styles.arrow}
      width="18"
      height="10"
      viewBox="0 0 18 10"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 5h15M12.5 1.5L16 5l-3.5 3.5" />
    </svg>
  );
}

function Plate({ player, codes }: { player: PitchPlayer; codes: ClubCodes }) {
  const { locale, messages } = useLanguage();
  const code = clubCode(player.team, codes);
  const swatch = clubSwatch(code);
  const shortName = player.shortName.trim() || player.name;
  return (
    <div className={styles.plate}>
      <span className={styles.name} title={player.name}>
        {swatch ? (
          <span
            className={`${styles.swatch} ${styles.swatchAcross}`}
            style={{ background: swatch }}
            aria-hidden="true"
          />
        ) : null}
        <span className={styles.nameText} aria-hidden={shortName !== player.name || undefined}>
          {shortName}
        </span>
      </span>
      {shortName !== player.name ? <span className="visually-hidden">{player.name}</span> : null}
      <span className={styles.code}>
        {swatch ? (
          <span
            className={`${styles.swatch} ${styles.swatchUpright}`}
            style={{ background: swatch }}
            aria-hidden="true"
          />
        ) : null}
        <span className={styles.codeText}>{code ?? player.team}</span>
      </span>
      {player.expectedPoints !== null && Number.isFinite(player.expectedPoints) ? (
        <span className={styles.xp}>
          {figure(player.expectedPoints, locale)}
          <span className="visually-hidden"> {messages.leagueMembers.pointsUnitSpoken}</span>
        </span>
      ) : null}
      {player.isNew ? <span className={styles.new}>{messages.leagueMembers.boardNew}</span> : null}
      {player.captain ? (
        <span className={styles.mark} role="img" aria-label={messages.squad.captainLabel}>
          {messages.leagueMembers.captainMark}
        </span>
      ) : player.vice ? (
        <span
          className={`${styles.mark} ${styles.vice}`}
          role="img"
          aria-label={messages.squad.viceCaptainLabel}
        >
          {messages.leagueMembers.viceMark}
        </span>
      ) : null}
    </div>
  );
}

function AttackLabel({ at }: { at: "first" | "last" }) {
  const copy = useLanguage().messages.leagueMembers;
  return (
    <span className={styles.attack} data-at={at} aria-hidden="true">
      {copy.attackDirection}
      <ArrowIcon />
    </span>
  );
}

/**
 * The eleven on a marked pitch.
 *
 * One list, one item per line in the order GK, DEF, MID, FWD, whatever way the pitch is
 * drawn. It is drawn across (own goal on the left, attacking to the right) where it has
 * 640 px, and upright (own goal at the bottom) where it has less: the stylesheet decides
 * with a container query, and the description names the direction for a screen reader.
 *
 * The midfield is centred on the halfway line in both drawings, the defence and the attack
 * stand at mirrored distances from it, and the keeper stands at the own goal. The direction
 * of attack is written on a white plate directly under the first defender in the published
 * order; where the defence is too crowded for that across the pitch, under the whole line.
 */
export function MemberPitch({ players, codes }: { players: PitchPlayer[]; codes: ClubCodes }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const describedBy = useId();
  const lines = LINES.map((position) => ({
    position,
    players: players.filter((player) => player.position === position),
  }));
  const defenders = lines[1]!.players.length;
  const height = horizontalHeight(
    lines.map((line) => line.players.length),
    defenders,
  );
  // With no defender the direction of attack stands under the keeper instead.
  const labelLine = defenders > 0 ? "DEF" : "GK";
  return (
    <div
      className={styles.wrap}
      data-mark="pitch"
      data-def-crowded={defenders >= 4 ? "true" : undefined}
      style={{ "--hh": `${height}px` } as CSSProperties}
    >
      <p id={describedBy} className="visually-hidden">
        <span className={styles.descAcross}>{copy.pitchHorizontal}</span>
        <span className={styles.descUpright}>{copy.pitchVertical}</span>
      </p>
      <div className={styles.field}>
        <div className={styles.markings} aria-hidden="true">
          <span className={styles.boundary} />
          <span className={styles.halfway} />
          <span className={styles.circle} />
          <span className={styles.centreSpot} />
          {(["own", "far"] as const).map((end) => (
            <span key={end} className={styles[end]}>
              <span className={styles.box} />
              <span className={styles.goalArea} />
              <span className={styles.penaltySpot} />
              <span className={styles.arc} />
              <span className={styles.goal} />
            </span>
          ))}
        </div>
        <div
          className={styles.lines}
          role="list"
          aria-label={messages.squad.pitchLabel}
          aria-describedby={describedBy}
        >
          {lines.map((line) =>
            line.players.length === 0 ? null : (
              <div
                key={line.position}
                className={styles.line}
                data-line={line.position.toLowerCase()}
                role="listitem"
                aria-label={messages.positions[line.position]}
                style={
                  {
                    "--n": line.players.length,
                    "--step": `${lineStep(line.players.length)}px`,
                  } as CSSProperties
                }
              >
                {line.players.map((player, index) => (
                  <div
                    key={player.playerId}
                    className={styles.token}
                    style={{ "--i": index } as CSSProperties}
                  >
                    <Plate player={player} codes={codes} />
                    {line.position === labelLine && index === 0 ? <AttackLabel at="first" /> : null}
                    {line.position === "DEF" && defenders >= 4 && index === defenders - 1 ? (
                      <AttackLabel at="last" />
                    ) : null}
                  </div>
                ))}
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
}

/** One bench player, in the order the game's automatic substitutions walk the bench. */
export interface BenchPlayer {
  playerId: number;
  name: string;
  shortName: string;
  position: string;
  team: string;
  expectedPoints: number | null;
  /** The published order, or null where none is published (shown as a hyphen, last). */
  order: number | null;
}

/** The bench under the pitch, read left to right in the published order. */
export function MemberBench({ players, codes }: { players: BenchPlayer[]; codes: ClubCodes }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  if (players.length === 0) return null;
  return (
    <section className={styles.bench} aria-labelledby={titleId} data-mark="bench">
      <div className={styles.benchInner}>
        <h3 className={styles.benchTitle} id={titleId}>
          {copy.bench}
        </h3>
        <ol className={styles.benchList}>
          {players.map((player) => {
            const code = clubCode(player.team, codes);
            const swatch = clubSwatch(code);
            const shortName = player.shortName.trim() || player.name;
            return (
              <li key={player.playerId} className={styles.benchItem}>
                <span className={styles.benchOrder}>{player.order ?? "-"}</span>
                <strong className={styles.benchName}>
                  <span aria-hidden={shortName !== player.name || undefined}>{shortName}</span>
                  {shortName !== player.name ? (
                    <span className="visually-hidden">{player.name}</span>
                  ) : null}
                </strong>
                <span className={styles.benchMeta}>
                  {swatch ? (
                    <span
                      className={styles.swatch}
                      style={{ background: swatch }}
                      aria-hidden="true"
                    />
                  ) : null}
                  <span className={code ? styles.benchCode : undefined}>{code ?? player.team}</span>
                  {Object.hasOwn(messages.positions, player.position) ? (
                    <span>
                      {" · "}
                      {messages.positions[player.position as keyof typeof messages.positions]}
                    </span>
                  ) : null}
                </span>
                {player.expectedPoints !== null && Number.isFinite(player.expectedPoints) ? (
                  <span className={styles.benchXp}>
                    {figure(player.expectedPoints, locale)}
                    <span className="visually-hidden">
                      {" "}
                      {messages.leagueMembers.pointsUnitSpoken}
                    </span>
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
