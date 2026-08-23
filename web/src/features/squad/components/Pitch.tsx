import type { PlayerView } from "../../../data/schema";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import styles from "./Pitch.module.css";

const ROWS: Array<PlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function Pitch({
  starters,
  showOutcomes = false,
  captainMultiplier = 2,
}: {
  starters: PlayerView[];
  showOutcomes?: boolean;
  captainMultiplier?: number;
}) {
  const { messages } = useLanguage();
  return (
    <div className={styles.pitch} role="list" aria-label={messages.squad.pitchLabel}>
      {ROWS.map((position) => {
        const row = starters.filter((p) => p.position === position);
        if (row.length === 0) return null;
        return (
          <div key={position} className={styles.row} role="listitem" aria-label={position}>
            {row.map((player) => (
              <PlayerChip
                key={player.player_id}
                player={player}
                showOutcome={showOutcomes}
                captainMultiplier={captainMultiplier}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function PlayerChip({
  player,
  showOutcome = false,
  captainMultiplier = 2,
}: {
  player: PlayerView;
  showOutcome?: boolean;
  captainMultiplier?: number;
}) {
  const { locale, messages } = useLanguage();
  const difference =
    player.event_points === null ? null : player.event_points - player.expected_points;
  return (
    <div className={styles.chip}>
      {player.is_captain && (
        <span
          className={styles.captain}
          aria-label={messages.squad.captainLabel}
          title={messages.squad.captain}
        >
          C
        </span>
      )}
      <div className={styles.name} title={player.name}>
        {player.short_name}
      </div>
      <div className={styles.meta}>
        <span>{player.team}</span>
        <span className={styles.xp}>{points(player.expected_points, 1, locale)}</span>
      </div>
      {showOutcome ? (
        <div className={styles.outcome}>
          <span>
            {messages.squad.projectedPlayerPoints(points(player.expected_points, 1, locale))}
          </span>
          <span>
            {player.event_points === null
              ? messages.squad.eventPointsUnavailable
              : messages.squad.realizedPlayerPoints(points(player.event_points, 0, locale))}
          </span>
          <strong>
            {difference === null
              ? messages.squad.pointDifferenceUnavailable
              : messages.squad.playerPointDifference(signedPoints(difference, 1, locale))}
          </strong>
          {player.is_captain ? (
            <span className={styles.captainMultiplier}>
              {messages.squad.captainMultiplier(captainMultiplier)}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
