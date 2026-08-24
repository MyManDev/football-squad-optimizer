import recommendationDocument from "../../public/data/2026-27/gw01/recommendation.json" with { type: "json" };

import type { PlayerView, RecommendationView } from "../data/schema";

const rawView = recommendationDocument.payload as unknown as RecommendationView;

function withEventPoints(player: PlayerView, eventPoints: number | null): PlayerView {
  return { ...player, event_points: eventPoints };
}

export const unsettledRecommendationFixture: RecommendationView = {
  ...rawView,
  captain_multiplier: 2,
  settled: false,
  outcome_realized_score: null,
  outcome_net_score: null,
  squad: rawView.squad.map((player) => withEventPoints(player, null)),
  starting_xi: rawView.starting_xi.map((player) => withEventPoints(player, null)),
  bench: rawView.bench.map((player) => withEventPoints(player, null)),
};

const starterPoints = [3, 6, 2, 4, 8, 5, 3, 7, 2, 9, 4] as const;
const benchPoints = [2, 1, 4, 0] as const;
const eventPointsByPlayer = new Map<number, number>([
  ...unsettledRecommendationFixture.starting_xi.map(
    (player, index) => [player.player_id, starterPoints[index]!] as const,
  ),
  ...unsettledRecommendationFixture.bench.map(
    (player, index) => [player.player_id, benchPoints[index]!] as const,
  ),
]);

const settledStartingXi = unsettledRecommendationFixture.starting_xi.map((player) =>
  withEventPoints(player, eventPointsByPlayer.get(player.player_id) ?? 0),
);
const realizedScore = settledStartingXi.reduce((total, player) => {
  const multiplier = player.is_captain ? unsettledRecommendationFixture.captain_multiplier : 1;
  return total + (player.event_points ?? 0) * multiplier;
}, 0);

export const settledRecommendationFixture: RecommendationView = {
  ...unsettledRecommendationFixture,
  settled: true,
  outcome_realized_score: realizedScore,
  outcome_net_score: realizedScore,
  squad: unsettledRecommendationFixture.squad.map((player) =>
    withEventPoints(player, eventPointsByPlayer.get(player.player_id) ?? 0),
  ),
  starting_xi: settledStartingXi,
  bench: unsettledRecommendationFixture.bench.map((player) =>
    withEventPoints(player, eventPointsByPlayer.get(player.player_id) ?? 0),
  ),
};
