import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { EmptyState } from "../../../design/components/EmptyState";
import type { FixturesPayload } from "../../fixtures/types";
import type { CoachAbsence } from "../advice/coachAbsences";
import { CoachNews } from "../components/CoachNews";
import { useLanguage } from "../../../i18n/context";
import type { ClubCodes } from "../../../lib/clubs";
import { figure } from "../../../lib/format";
import { ClubMark } from "../components/ClubMark";
import { MemberBench, MemberPitch, type PitchPlayer } from "../components/MemberPitch";
import { PitchLookControl } from "../components/PitchLookControl";
import { PlayerDetails } from "../components/PlayerDetails";
import { PointsUnit } from "../components/PointsUnit";
import { expectedLineupLabel } from "../advice/expectedLineupLabel";
import { modelChangeOf, popChanged, releasePop } from "../advice/modelSwitch";
import type { EntryAdvice, EntrySquad, EntrySquadPlayer } from "../types";
import { finite, heldBench, type SquadOnPitch } from "./squadOnPitch";
import { usePitchMovement } from "./usePitchMovement";
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
  news = new Map<number, CoachAbsence>(),
  held,
  fixtures,
}: {
  onPitch: SquadOnPitch;
  plan: EntryAdvice | null;
  codes: ClubCodes;
  /** The plan's lineup as a list; without one there is no list view and no toggle. */
  list: ReactNode;
  news?: ReadonlyMap<number, CoachAbsence>;
  held?: EntrySquad;
  fixtures?: FixturesPayload | null;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  const [view, setView] = useState<"pitch" | "list">("pitch");
  const field = useRef<HTMLDivElement>(null);
  const planned = onPitch.source === "plan";
  const basis = planned ? plan : held;
  const context = basis
    ? JSON.stringify([
        basis.league_id,
        "entry_id" in basis ? basis.entry_id : basis.entry.entry_id,
        basis.season,
        basis.gameweek,
        basis.source_snapshot_id,
      ])
    : null;
  const layoutKey = JSON.stringify([
    onPitch.eleven.map((player) => [player.playerId, player.position]),
    onPitch.bench.map((player) => [player.playerId, player.order]),
  ]);
  usePitchMovement(field, context, layoutKey, view === "pitch", planned);
  const [selection, setSelection] = useState<{ context: string | null; id: number } | null>(null);
  const selected =
    selection?.context === context
      ? [...onPitch.eleven, ...onPitch.bench].find((player) => player.playerId === selection?.id)
      : undefined;
  // A selection ends once its player is no longer drawn or the context changes, so a later
  // plan or the held squad drawing the player again does not reopen the details by itself.
  if (selection !== null && selected === undefined) setSelection(null);
  const selectPlayer = (id: number) => setSelection({ context, id });
  const modelChange = planned ? modelChangeOf(plan) : null;
  const changeKey = modelChange?.key ?? null;
  // The changed players' plates, on the pitch and the bench, move once per change; the marks
  // stay until the next plan.
  useEffect(() => {
    if (changeKey === null || field.current === null) return undefined;
    const running = popChanged(changeKey, [
      ...field.current.querySelectorAll<HTMLElement>("[data-model-changed] [data-plate]"),
    ]);
    return () => {
      const unfinished = running.filter((motion) => motion.playState !== "finished");
      unfinished.forEach((motion) => motion.cancel());
      if (unfinished.length > 0) releasePop(changeKey);
    };
  }, [changeKey]);
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
  const hasList = planned && list != null;
  const own = planned && finite(plan?.expected_own_points) ? plan.expected_own_points : null;
  const newsPlayers = new Map(
    [...onPitch.eleven, ...onPitch.bench].map((player) => [player.playerId, player.name]),
  );
  for (const player of [...(held?.starting_xi ?? []), ...(held?.bench ?? [])])
    newsPlayers.set(player.player_id, player.name);
  // The list view states the plan's own total in its first line, so the heading row
  // does not say it twice.
  const line = [
    formation(onPitch.eleven),
    own !== null && !(hasList && view === "list")
      ? plan?.lineup_expectation
        ? expectedLineupLabel(figure(own, locale), language)
        : copy.squadOwnPoints(figure(own, locale))
      : null,
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
      <div ref={field} className={styles.pitchView} hidden={hasList && view !== "pitch"}>
        <MemberPitch
          players={onPitch.eleven}
          codes={codes}
          modelChange={modelChange}
          news={news}
          onSelectPlayer={selectPlayer}
        />
        <MemberBench
          players={onPitch.bench}
          codes={codes}
          modelChange={modelChange}
          news={news}
          onSelectPlayer={selectPlayer}
        />
        <PitchLookControl />
      </div>
      {hasList ? (
        <div className={styles.listView} hidden={view !== "list"}>
          {list}
        </div>
      ) : null}
      <CoachNews news={news} players={newsPlayers} />
      {selected ? (
        <PlayerDetails
          key={`${context}:${selected.playerId}`}
          player={selected}
          plan={planned ? plan : null}
          held={held}
          fixtures={fixtures}
          codes={codes}
          news={news}
          onClose={() => setSelection(null)}
        />
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
 * The squad the member holds before the plan's transfers, as a compact list, one line per
 * player: the eleven led by the position word with the captain the game records, the bench
 * led by its published order with the position after the club, and the note that the
 * published squad names no vice-captain (none is inferred).
 */
export function HeldSquad({ squad, codes }: { squad: EntrySquad; codes: ClubCodes }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const position = (code: string) =>
    Object.hasOwn(messages.positions, code)
      ? messages.positions[code as keyof typeof messages.positions]
      : code;
  const row = (player: EntrySquadPlayer, lead: ReactNode, onBench: boolean) => (
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
        <ClubMark team={player.team} codes={codes} />
        {onBench ? ` · ${position(player.position)}` : null}
      </span>
      {finite(player.expected_points) ? (
        <span className={styles.heldXp}>
          {figure(player.expected_points, locale)} <PointsUnit />
        </span>
      ) : null}
    </li>
  );
  return (
    <div className={styles.held}>
      <h3 className={styles.heldTitle}>{copy.startingXiLabel}</h3>
      <ol className={styles.heldList}>
        {squad.starting_xi.map((player) => row(player, position(player.position), false))}
      </ol>
      {squad.bench.length > 0 ? (
        <>
          <h3 className={styles.heldTitle}>{copy.bench}</h3>
          <ol className={styles.heldList}>
            {heldBench(squad.bench).map((player) => row(player, player.bench_order ?? "-", true))}
          </ol>
        </>
      ) : null}
    </div>
  );
}
