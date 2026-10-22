import { useEffect, useId, useRef } from "react";

import { useLanguage } from "../../../i18n/context";
import { clubCode, type ClubCodes } from "../../../lib/clubs";
import { figure, utcShort } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import type { CoachAbsence } from "../advice/coachAbsences";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import { TOP100_COPY } from "../advice/top100Copy";
import type { EntryAdvice, EntrySquad } from "../types";
import { CoachNews } from "./CoachNews";
import type { BenchPlayer, PitchPlayer } from "./MemberPitch";
import styles from "./PlayerDetails.module.css";

const COPY = {
  tr: {
    close: "Kapat",
    points: "Beklenen puan",
    minutes: "Beklenen dakika",
    fixtures: "Bu haftanın maçları",
    home: "Ev",
    away: "Deplasman",
    reason: "Bu transfer neden?",
    points_gain: "Bu haftanın beklenen puanına göre önerildi.",
    window_value: "Seçilen haftaların toplam puanı için önerildi.",
    mode_tradeoff: "Seçtiğin rakip ve oyun tarzına göre önerildi.",
    blank: "Bu hafta maç yok.",
  },
  en: {
    close: "Close",
    points: "Expected points",
    minutes: "Expected minutes",
    fixtures: "This week's fixtures",
    home: "Home",
    away: "Away",
    reason: "Why this transfer?",
    points_gain: "Recommended for this week's expected points.",
    window_value: "Recommended for the total points across your selected weeks.",
    mode_tradeoff: "Recommended for your selected rival and playing style.",
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
}: {
  player: PitchPlayer | BenchPlayer;
  plan: EntryAdvice | null;
  held?: EntrySquad;
  fixtures?: FixturesPayload | null;
  codes: ClubCodes;
  news: ReadonlyMap<number, CoachAbsence>;
  onClose: () => void;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = COPY[language];
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
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
  const reason = !move
    ? null
    : move.reason_code === "manager_word"
      ? EVIDENCE_COPY[language].moveReason
      : move.reason_code === "top100_preference"
        ? TOP100_COPY[language].moveReason
        : copy[move.reason_code];
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
        <button type="button" onClick={onClose}>
          {copy.close}
        </button>
      </header>
      {player.expectedPoints !== null && Number.isFinite(player.expectedPoints) ? (
        <dl className={styles.points}>
          <dt>{copy.points}</dt>
          <dd>{figure(player.expectedPoints, locale)}</dd>
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
