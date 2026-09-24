import { useId, useState, type ReactNode } from "react";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import type { ClubCodes } from "../../../lib/clubs";
import { figure } from "../../../lib/format";
import { ClubMark } from "../components/ClubMark";
import { MemberBench, MemberPitch, type PitchPlayer } from "../components/MemberPitch";
import type { EntryAdvice, EntrySquad, EntrySquadPlayer } from "../types";
import { finite, heldBench, type SquadOnPitch } from "./squadOnPitch";
import styles from "./MemberSquad.module.css";

/** '3-4-3' for a full eleven with one keeper; nothing for a partial one. */
function formation(eleven: readonly PitchPlayer[]): string | null {
  const count = (position: string) => eleven.filter((player) => player.position === position);
  if (eleven.length !== 11 || count("GK").length !== 1) return null;
  return [count("DEF").length, count("MID").length, count("FWD").length].join("-");
}

/**
 * The squad section the sidebar's 'Kadro' opens (#kadro): the eleven on the pitch with the
 * bench under it, or, one toggle away, the same week as the list the plan publishes.
 */
export function MemberSquad({
  onPitch,
  plan,
  codes,
  list,
}: {
  onPitch: SquadOnPitch;
  plan: EntryAdvice | null;
  codes: ClubCodes;
  /** The plan's lineup as a list; without one there is no list view and no toggle. */
  list: ReactNode;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  const [view, setView] = useState<"pitch" | "list">("pitch");
  if (onPitch.source === null) {
    return (
      <section id="kadro" className={styles.squad} aria-labelledby={titleId}>
        <h2 className={styles.title} id={titleId}>
          {copy.memberSquad}
        </h2>
        <EmptyState title={copy.emptySquad}>{copy.emptySquadBody}</EmptyState>
      </section>
    );
  }
  const planned = onPitch.source === "plan";
  const hasList = planned && list != null;
  const own = planned && finite(plan?.expected_own_points) ? plan.expected_own_points : null;
  const line = [
    formation(onPitch.eleven),
    own !== null ? copy.squadOwnPoints(figure(own, locale)) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <section id="kadro" className={styles.squad} aria-labelledby={titleId}>
      <div className={styles.head}>
        <div className={styles.heading}>
          <h2 className={styles.title} id={titleId}>
            {planned ? copy.squadAfterTitle : copy.memberSquad}
          </h2>
          {line ? <p className={styles.line}>{line}</p> : null}
        </div>
        {hasList ? (
          <div className={styles.toggle} role="group" aria-label={copy.viewLabel}>
            {(["pitch", "list"] as const).map((option) => (
              <button
                key={option}
                type="button"
                className={styles.option}
                aria-pressed={view === option}
                onClick={() => setView(option)}
              >
                <span className={styles.face}>
                  {option === "pitch" ? copy.viewPitch : copy.viewList}
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className={styles.pitchView} hidden={hasList && view !== "pitch"}>
        <MemberPitch players={onPitch.eleven} codes={codes} />
        <MemberBench players={onPitch.bench} codes={codes} />
        {planned ? null : <p className={styles.note}>{copy.heldViceCaptainUnavailable}</p>}
      </div>
      {hasList ? (
        <div className={styles.listView} hidden={view !== "list"}>
          {list}
        </div>
      ) : null}
    </section>
  );
}

function ShortName({ name, shortName }: { name: string; shortName: string }) {
  const short = shortName.trim() || name;
  if (short === name) return <>{name}</>;
  return (
    <>
      <span aria-hidden="true">{short}</span>
      <span className="visually-hidden">{name}</span>
    </>
  );
}

/**
 * The squad the member holds before the plan's transfers, as a compact list: the eleven
 * with the captain the game records, the bench in its published order, and the note that
 * the published squad names no vice-captain (none is inferred).
 */
export function HeldSquad({ squad, codes }: { squad: EntrySquad; codes: ClubCodes }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const position = (code: string) =>
    Object.hasOwn(messages.positions, code)
      ? messages.positions[code as keyof typeof messages.positions]
      : code;
  const row = (player: EntrySquadPlayer, lead: ReactNode) => (
    <li key={player.player_id} className={styles.heldRow}>
      <span className={styles.heldLead}>{lead}</span>
      <strong className={styles.heldName}>
        <ShortName name={player.name} shortName={player.short_name} />
      </strong>
      {player.is_captain ? (
        <>
          <span className={styles.heldMark} aria-hidden="true">
            {copy.captainMark}
          </span>
          <span className="visually-hidden">{messages.squad.captainLabel}</span>
        </>
      ) : null}
      <span className={styles.heldMeta}>
        <ClubMark team={player.team} codes={codes} /> · {position(player.position)}
      </span>
      {finite(player.expected_points) ? (
        <span className={styles.heldXp}>{figure(player.expected_points, locale)} xP</span>
      ) : null}
    </li>
  );
  return (
    <div className={styles.held}>
      <h3 className={styles.heldTitle}>{copy.startingXiLabel}</h3>
      <ol className={styles.heldList}>
        {squad.starting_xi.map((player) => row(player, position(player.position)))}
      </ol>
      {squad.bench.length > 0 ? (
        <>
          <h3 className={styles.heldTitle}>{copy.bench}</h3>
          <ol className={styles.heldList}>
            {heldBench(squad.bench).map((player) => row(player, player.bench_order ?? "—"))}
          </ol>
        </>
      ) : null}
      <p className={styles.note}>{copy.heldViceCaptainUnavailable}</p>
    </div>
  );
}
