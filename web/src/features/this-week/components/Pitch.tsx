import type { PlayerView } from "../../../data/schema";
import { points } from "../../../lib/format";
import styles from "./Pitch.module.css";

const ROWS: Array<PlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function Pitch({ starters }: { starters: PlayerView[] }) {
  return (
    <div className={styles.pitch} role="list" aria-label="Starting eleven by position">
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
  return (
    <div className={styles.chip}>
      {player.is_captain && (
        <span className={styles.captain} aria-label="captain" title="Captain">
          C
        </span>
      )}
      <div className={styles.name}>{player.name}</div>
      <div className={styles.meta}>
        <span>{player.team}</span>
        <span className={styles.xp}>{points(player.expected_points)}</span>
      </div>
    </div>
  );
}
