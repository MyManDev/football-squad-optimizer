import { useEffect, useState, type CSSProperties } from "react";

import { motionDuration } from "../../design/motion";
import { useLanguage } from "../../i18n/context";
import { advanceActivity, type ActivityHistory, type PlayerActivity } from "./playerActivity";
import styles from "./LivePlayerActivity.module.css";

export function LivePlayerActivity({
  identity,
  sourceTime,
  players,
  names,
  counted = null,
}: {
  identity: string;
  sourceTime: string;
  players: readonly PlayerActivity[] | null;
  names: ReadonlyMap<number, string>;
  /**
   * The picks whose points count (the official scorer's), the only ones listed: a reserve not
   * brought on is left out, and under the bench boost the bench counts (the owner's word of
   * 2026-11-11). Every pick's events are still followed, so a reserve brought on later does
   * not flash an old goal as new. Null lists every pick.
   */
  counted?: ReadonlySet<number> | null;
}) {
  const { language } = useLanguage();
  const [history, setHistory] = useState<ActivityHistory | null>(null);
  const [expired, setExpired] = useState<{ identity: string; counts: ReadonlyMap<number, number> }>(
    {
      identity,
      counts: new Map(),
    },
  );
  const next = players === null ? history : advanceActivity(history, identity, sourceTime, players);
  if (next !== history) setHistory(next);
  const highlights = next?.highlights;
  useEffect(() => {
    if (!highlights?.size) return;
    const timer = setTimeout(
      () => setExpired({ identity, counts: highlights }),
      motionDuration("data"),
    );
    return () => clearTimeout(timer);
  }, [highlights, identity]);
  if (players === null) return null;
  const shown = players.filter(
    (player) =>
      (counted === null || counted.has(player.elementId)) &&
      (player.matchInProgress || player.goals > 0 || player.assists > 0),
  );
  if (shown.length === 0 || shown.some((player) => !names.get(player.elementId)?.trim()))
    return null;
  const tr = language === "tr";
  const duration = motionDuration("data");
  return (
    <ul className={styles.players} aria-label={tr ? "Oyuncular" : "Players"}>
      {shown.map((player) => {
        const revision = next?.highlights.get(player.elementId) ?? 0;
        return (
          <li
            key={`${player.elementId}:${revision}`}
            className={styles.player}
            data-live-player={player.elementId}
            data-live-match={player.matchInProgress || undefined}
            data-live-highlight={
              duration > 0 &&
              revision >
                (expired.identity === identity ? (expired.counts.get(player.elementId) ?? 0) : 0)
                ? revision
                : undefined
            }
            style={{ "--live-event-duration": `${duration}ms` } as CSSProperties}
          >
            <span className={styles.name}>{names.get(player.elementId)}</span>
            {player.matchInProgress ? (
              <span
                className={styles.playing}
                role="img"
                aria-label={tr ? "Maç sürüyor" : "Match in Progress"}
              />
            ) : null}
            {player.goals > 0 ? (
              <span
                className={styles.event}
                role="img"
                aria-label={`${tr ? "Gol" : "Goals"}: ${player.goals}`}
              >
                <span aria-hidden="true">⚽ {player.goals}</span>
              </span>
            ) : null}
            {player.assists > 0 ? (
              <span
                className={styles.event}
                role="img"
                aria-label={`${tr ? "Asist" : "Assists"}: ${player.assists}`}
              >
                <span aria-hidden="true">A {player.assists}</span>
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
