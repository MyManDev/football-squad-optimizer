import type { PlayerView } from "../../../data/schema";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import styles from "./Pitch.module.css";

const ROWS: Array<PlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function Pitch({ starters }: { starters: PlayerView[] }) {
  const { messages } = useLanguage();
  return (
    <div className={styles.pitch} role="list" aria-label={messages.squad.pitchLabel}>
      {ROWS.map((position) => {
        const row = starters.filter((p) => p.position === position);
        if (row.length === 0) return null;
        return (
          <div key={position} className={styles.row} role="listitem" aria-label={position}>
            {row.map((player) => (
              <PlayerChip key={player.player_id} player={player} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function PlayerChip({ player }: { player: PlayerView }) {
  const { locale, messages } = useLanguage();
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
    </div>
  );
}
