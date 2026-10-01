import type { EntryAdvice } from "../features/league/types";

/** Explicit hypothetical information, never a captured player report. */
export function mockInformationReview(
  window: 3 | 5 = 3,
): NonNullable<EntryAdvice["information_review"]> {
  return {
    version: "football_information_review_v1",
    status: "compared",
    reason: "compared",
    source_snapshot_id: "synthetic",
    captured_at_utc: "2026-09-01T00:00:00Z",
    player_name: "Doubtful Player",
    source_playing_chance_percent: 75,
    information_gameweek: 3,
    candidates: [
      {
        selected: true,
        baseline: true,
        transfers_in: [],
        transfers_out: [],
        chip: null,
        expected_net_points: 155.5,
        branches: (["eligible", "unavailable"] as const).map((state) => ({
          state,
          expected_net_points: state === "eligible" ? 160 : 142,
          hit_points: 0,
          weeks: Array.from({ length: window - 1 }, (_, i) => ({
            gameweek: 3 + i,
            transfers_in: i === 0 ? ["New Player"] : [],
            transfers_out: i === 0 ? ["Old Player"] : [],
            chip: null,
            bank_tenths: 5,
            free_transfers: 2 + i,
          })),
        })),
      },
    ],
  };
}
