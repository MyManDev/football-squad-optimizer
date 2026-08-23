import { describe, expect, it } from "vitest";

import {
  settledRecommendationFixture,
  unsettledRecommendationFixture,
} from "./settledRecommendation";

describe("settled recommendation contract fixture", () => {
  it("moves event points from null to numbers without changing the player set", () => {
    expect(unsettledRecommendationFixture.settled).toBe(false);
    expect(
      unsettledRecommendationFixture.squad.every((player) => player.event_points === null),
    ).toBe(true);
    expect(settledRecommendationFixture.settled).toBe(true);
    expect(
      settledRecommendationFixture.squad.every((player) => typeof player.event_points === "number"),
    ).toBe(true);
    expect(settledRecommendationFixture.squad.map((player) => player.player_id)).toEqual(
      unsettledRecommendationFixture.squad.map((player) => player.player_id),
    );
  });

  it("keeps the published total consistent with event points and captain multiplier", () => {
    const expectedTotal = settledRecommendationFixture.starting_xi.reduce((total, player) => {
      const multiplier = player.is_captain ? settledRecommendationFixture.captain_multiplier : 1;
      return total + player.event_points! * multiplier;
    }, 0);

    expect(settledRecommendationFixture.captain_multiplier).toBe(2);
    expect(settledRecommendationFixture.outcome_realized_score).toBe(expectedTotal);
    expect(settledRecommendationFixture.outcome_net_score).toBe(expectedTotal);
  });
});
