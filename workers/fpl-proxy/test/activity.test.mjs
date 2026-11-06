import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { cacheKeys, liveActivityDocument, liveDocument, routeFor } from "../src/proxy.js";
import { contractFile, problems } from "./schema.mjs";

function inputs() {
  return {
    season: "2026-27",
    gameweek: 9,
    sourceTime: "2026-10-31T16:00:00Z",
    fixtures: [
      {
        id: 91,
        event: 9,
        team_h: 1,
        team_a: 2,
        started: true,
        finished: false,
      },
      { id: 92, event: 9, team_h: 1, team_a: 3, started: true, finished: true },
    ],
    live: {
      elements: [
        {
          id: 1,
          stats: {
            total_points: 9,
            minutes: 130,
            yellow_cards: 0,
            red_cards: 0,
            goals_scored: 1,
            assists: 1,
          },
          explain: [
            {
              fixture: 91,
              stats: [
                { identifier: "minutes", value: 40 },
                { identifier: "goals_scored", value: 1 },
              ],
            },
            {
              fixture: 92,
              stats: [
                { identifier: "minutes", value: 90 },
                { identifier: "assists", value: 1 },
              ],
            },
          ],
          raw_only: "never send this",
        },
      ],
    },
  };
}

describe("the opt-in live activity view", () => {
  it("preserves the old route and strictly accepts only its named activity view", () => {
    const read = (query) =>
      routeFor("GET", new URL(`https://example.test/api/v1/fpl/live/9${query}`));
    assert.deepEqual(read(""), { kind: "live", gameweek: 9 });
    assert.deepEqual(read("?view=activity"), {
      kind: "live",
      gameweek: 9,
      view: "activity",
    });
    for (const query of ["?view=other", "?view=activity&view=activity", "?view=activity&key=1"]) {
      assert.equal(read(query).status, 404);
    }
    assert.notDeepEqual(cacheKeys(read("")), cacheKeys(read("?view=activity")));
  });

  it("keeps fixture-specific goals, assists and participation through a double week", async () => {
    const source = inputs();
    const document = liveActivityDocument(source);
    assert.deepEqual(document.week, liveDocument(source));
    assert.deepEqual(document.activity, {
      in_play_fixtures: [91],
      appearances: [
        { element_id: 1, fixture_id: 91, minutes: 40, goals: 1, assists: 0 },
        { element_id: 1, fixture_id: 92, minutes: 90, goals: 0, assists: 1 },
      ],
    });
    assert.ok(!JSON.stringify(document).includes("never send this"));
    assert.deepEqual(problems(await contractFile("week_activity_v1.schema.json"), document), []);
  });

  for (const [name, corrupt] of [
    [
      "missing explanation",
      (source) => {
        delete source.live.elements[0].explain;
      },
    ],
    [
      "unknown fixture",
      (source) => {
        source.live.elements[0].explain[0].fixture = 999;
      },
    ],
    [
      "repeated fixture",
      (source) => {
        source.live.elements[0].explain.push(source.live.elements[0].explain[0]);
      },
    ],
    [
      "repeated event",
      (source) => {
        source.live.elements[0].explain[0].stats.push({
          identifier: "minutes",
          value: 40,
        });
      },
    ],
    [
      "negative event",
      (source) => {
        source.live.elements[0].explain[0].stats[1].value = -1;
      },
    ],
    [
      "inconsistent totals",
      (source) => {
        source.live.elements[0].stats.goals_scored = 2;
      },
    ],
    [
      "unknown fixture start",
      (source) => {
        delete source.fixtures[0].started;
      },
    ],
  ]) {
    it(`keeps the score but shows no activity with ${name}`, () => {
      const source = inputs();
      corrupt(source);
      const document = liveActivityDocument(source);
      assert.deepEqual(document.week, liveDocument(source));
      assert.equal(document.activity, null);
    });
  }
});
