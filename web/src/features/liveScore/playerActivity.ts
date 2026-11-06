import type { LiveActivity, LiveAppearance } from "./weekActivity";

export interface PlayerActivity {
  elementId: number;
  matchInProgress: boolean;
  goals: number;
  assists: number;
  appearances: LiveAppearance[];
}

/** The indicator means participation in an unfinished match, not an inferred on-pitch status. */
export function playerActivities(
  activity: LiveActivity,
  picks: readonly number[],
): PlayerActivity[] {
  const playing = new Set(activity.in_play_fixtures);
  return picks.map((elementId) => {
    const appearances = activity.appearances.filter((row) => row.element_id === elementId);
    return {
      elementId,
      matchInProgress: appearances.some((row) => row.minutes > 0 && playing.has(row.fixture_id)),
      goals: appearances.reduce((sum, row) => sum + row.goals, 0),
      assists: appearances.reduce((sum, row) => sum + row.assists, 0),
      appearances,
    };
  });
}

export interface ActivityHistory {
  identity: string;
  time: number;
  counts: ReadonlyMap<string, number>;
  highlights: ReadonlyMap<number, number>;
}

/** Keep event high-water marks: rereads, corrections and older cache copies never replay. */
export function advanceActivity(
  previous: ActivityHistory | null,
  identity: string,
  sourceTime: string,
  players: readonly PlayerActivity[],
): ActivityHistory {
  const time = Date.parse(sourceTime);
  const sameWeek = previous?.identity === identity;
  if (sameWeek && time <= previous.time) return previous;
  const counts = new Map(sameWeek ? previous.counts : []);
  const highlights = new Map(sameWeek ? previous.highlights : []);
  let changed = false;
  for (const player of players) {
    let fresh = false;
    for (const appearance of player.appearances) {
      for (const kind of ["goals", "assists"] as const) {
        const key = `${player.elementId}:${appearance.fixture_id}:${kind}`;
        const seen = counts.get(key) ?? 0;
        const value = appearance[kind];
        if (sameWeek && value > seen) fresh = true;
        counts.set(key, Math.max(seen, value));
      }
    }
    if (fresh) {
      changed = true;
      highlights.set(player.elementId, (highlights.get(player.elementId) ?? 0) + 1);
    }
  }
  return {
    identity,
    time,
    counts,
    highlights: sameWeek && !changed ? previous.highlights : highlights,
  };
}
