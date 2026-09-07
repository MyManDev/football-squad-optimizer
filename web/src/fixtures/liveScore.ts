import type { ViewEnvelope } from "../data/client";
import type { LiveScoreView } from "../data/liveScore";
import { unsettledRecommendationFixture } from "./settledRecommendation";

/** Synthetic score only; never publish as a real capture. */
export const liveScoreFixture: ViewEnvelope<LiveScoreView> = {
  contract_version: "live_score_v1",
  generated_at_utc: "2026-08-23T18:00:00Z",
  payload: {
    season: "2026-27",
    gameweek: 1,
    decision_snapshot_id: unsettledRecommendationFixture.snapshot_id,
    prediction_fingerprint: unsettledRecommendationFixture.prediction_fingerprint,
    status: "available",
    reason: null,
    source_snapshot_id: "synthetic-live-capture",
    captured_at_utc: "2026-08-23T17:30:00Z",
    named_score: 41,
    transfer_hit_points: 4,
    net_score: 37,
    fixtures_finished: 4,
    fixtures_total: 10,
    bonus_confirmed: false,
  },
};
