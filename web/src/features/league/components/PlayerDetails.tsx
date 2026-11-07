import { useEffect, useId, useRef, useState } from "react";

import { motionDuration } from "../../../design/motion";
import { useLanguage } from "../../../i18n/context";
import { clubCode, type ClubCodes } from "../../../lib/clubs";
import { figure, utcShort } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import type { CoachAbsence } from "../advice/coachAbsences";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import { TOP100_COPY } from "../advice/top100Copy";
import type { EntryAdvice, EntrySquad } from "../types";
import { CoachNews } from "./CoachNews";
import type { BenchPlayer, PitchPlayer, PitchPointsKind } from "./MemberPitch";
import { playerPoints } from "./playerPoints";
import styles from "./PlayerDetails.module.css";

const COPY = {
  tr: {
    close: "Kapat",
    points: "Beklenen puan",
    actualPoints: "Hafta puanı",
    minutes: "Beklenen dakika",
    fixtures: "Bu haftanın maçları",
    home: "Ev",
    away: "Deplasman",
    reason: "Bu transfer neden?",
    blank: "Bu hafta maç yok.",
  },
  en: {
    close: "Close",
    points: "Expected Points",
    actualPoints: "Gameweek Points",
    minutes: "Expected Minutes",
    fixtures: "This Week's Fixtures",
    home: "Home",
    away: "Away",
    reason: "Why this transfer?",
    blank: "No fixture this week.",
  },
};

/** A keyboard and touch accessible view of facts already carried by the shown plan. */
export function PlayerDetails({
  player,
  plan,
  held,
  fixtures,
  codes,
  news,
  onClose,
  pointsKind = "expected",
}: {
  player: PitchPlayer | BenchPlayer;
  plan: EntryAdvice | null;
  held?: EntrySquad;
  fixtures?: FixturesPayload | null;
  codes: ClubCodes;
  news: ReadonlyMap<number, CoachAbsence>;
  onClose: () => void;
  pointsKind?: PitchPointsKind;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = COPY[language];
  const points = playerPoints(player, pointsKind);
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const [closing, setClosing] = useState(false);
  const dismissTimer = useRef<number | undefined>(undefined);
  const outsidePress = useRef(false);
  const dismiss = () => {
    if (dismissTimer.current !== undefined) return;
    const duration = motionDuration("ui");
    if (duration === 0) {
      onClose();
      return;
    }
    setClosing(true);
    dismissTimer.current = window.setTimeout(onClose, duration);
  };
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement;
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    element.showModal();
    return () => {
      window.clearTimeout(dismissTimer.current);
      root.style.overflow = overflow;
      element.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus({ preventScroll: true });
    };
  }, []);
  const basis = plan ?? held;
  const calendar =
    basis &&
    fixtures?.season === basis.season &&
    fixtures.source_snapshot_id === basis.source_snapshot_id
      ? fixtures
      : null;
  const week = calendar?.gameweeks.find((row) => row.gameweek === basis?.gameweek);
  const teamCode = clubCode(player.team, codes);
  const sameTeam = (team: { name: string; short_name: string }) =>
    team.name.trim().toLocaleLowerCase("en-GB") === player.team.trim().toLocaleLowerCase("en-GB") ||
    (teamCode !== null && team.short_name === teamCode);
  const matches = week?.fixtures.filter((match) => sameTeam(match.home) || sameTeam(match.away));
  const move = plan?.moves.find((row) => row.player_in?.player_id === player.playerId);
  // Said only of a move the club's page or the Top 100 setting put in the plan.
  const reason =
    move?.reason_code === "manager_word"
      ? EVIDENCE_COPY[language].moveReason
      : move?.reason_code === "top100_preference"
        ? TOP100_COPY[language].moveReason
        : null;
  const roleRows =
    plan?.role_forecast?.rows.filter(
      (row) =>
        row.player_id === player.playerId &&
        row.gameweek === plan.gameweek &&
        row.status === "fitted_known_start_labels" &&
        Number.isFinite(row.expected_minutes) &&
        row.expected_minutes >= 0 &&
        row.expected_minutes <= 90,
    ) ?? [];
  const position = Object.hasOwn(messages.positions, player.position)
    ? messages.positions[player.position as keyof typeof messages.positions]
    : player.position;
  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby={titleId}
      data-closing={closing || undefined}
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onPointerDown={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        outsidePress.current =
          event.target === event.currentTarget &&
          (event.clientX < box.left ||
            event.clientX > box.right ||
            event.clientY < box.top ||
            event.clientY > box.bottom);
      }}
      onClick={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        if (
          outsidePress.current &&
          (event.clientX < box.left ||
            event.clientX > box.right ||
            event.clientY < box.top ||
            event.clientY > box.bottom)
        )
          dismiss();
        outsidePress.current = false;
      }}
      // A browser fires close from a queued task. StrictMode's development replay of the effect
      // above closes and reopens the dialog, so that close arrives while it is open again: only
      // a dialog that is really closed ends the selection.
      onClose={(event) => {
        if (!event.currentTarget.open) onClose();
      }}
    >
      <header className={styles.head}>
        <div>
          <h2 id={titleId}>{player.name}</h2>
          <p>
            {player.team} · {position}
          </p>
        </div>
        <button type="button" onClick={dismiss}>
          {copy.close}
        </button>
      </header>
      {points !== null && Number.isFinite(points) ? (
        <dl className={styles.points}>
          <dt>{pointsKind === "actual" ? copy.actualPoints : copy.points}</dt>
          <dd>
            {pointsKind === "actual" ? points.toLocaleString(locale) : figure(points, locale)}
          </dd>
        </dl>
      ) : null}
      {reason ? (
        <section>
          <h3>{copy.reason}</h3>
          <p>{reason}</p>
        </section>
      ) : null}
      {week ? (
        <section>
          <h3>{copy.fixtures}</h3>
          {matches?.length ? (
            <ul className={styles.fixtures}>
              {matches.map((match) => {
                const home = sameTeam(match.home);
                const rows = roleRows.filter((row) => row.fixture_id === match.fixture_id);
                const minutes = rows.length === 1 ? rows[0]!.expected_minutes : null;
                return (
                  <li key={match.fixture_id}>
                    <strong>{home ? match.away.name : match.home.name}</strong> ·{" "}
                    {home ? copy.home : copy.away}
                    {match.kickoff_utc ? (
                      <time dateTime={match.kickoff_utc}>
                        {utcShort(match.kickoff_utc, locale)}
                      </time>
                    ) : null}
                    {minutes !== null ? (
                      <p>
                        {copy.minutes}: {figure(minutes, locale)}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p>{copy.blank}</p>
          )}
        </section>
      ) : null}
      <CoachNews news={news} players={new Map([[player.playerId, player.name]])} />
    </dialog>
  );
}
