/**
 * The honesty gate as a test: no advice state, in either language, may show a
 * probability. The rival-relative window probabilities fell three pre-registered
 * calibrations and the line is closed; the copy says so, and this test keeps every
 * rendered advice state — proven, unproven, priced modes, partial data — inside the
 * envelope: expected points and price tags only, no percent signs, no P(...), no
 * "probability" in any spelling the site uses.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { ScoreboardCard } from "../components/ScoreboardCard";
import type { EntryAdvice, LeagueViewEnvelope, Scoreboard, ScoreboardGameweek } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

// The plan's regex plus the two words that crept past it in mode copy.
const FORBIDDEN = /%|probabilit|olasılık|\bP\(/i; // the plan's regex, verbatim
// The mode copy that used to reach the member page ("reduce the chance of falling
// behind") is not a probability claim by the regex but reads as one; it must not return.
const MODE_PROMISE = /chance of falling behind|geride kalma ihtimalini/i;

function withAdvice(overrides: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(35249001, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...overrides } };
}

function renderState(language: Language, advice: LeagueViewEnvelope<EntryAdvice>): string {
  const { container, unmount } = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter
        initialEntries={[
          `/league/members/35249001?mode=${advice.payload.mode}&window=${advice.payload.window}`,
        ]}
      >
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[35249001]}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={mockEntryAdviceIndex(35249001).payload}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
  const text = container.textContent ?? "";
  unmount();
  return text;
}

const STATES: Array<[string, LeagueViewEnvelope<EntryAdvice>]> = [
  ["proven baseline", withAdvice({ solver_status: "OPTIMAL", optimality_gap: 0 })],
  ["unproven plan", withAdvice({ solver_status: "FEASIBLE", optimality_gap: 1.3 })],
  ["priced competitive mode", mockEntryAdviceEnvelope(35249001, "garantici", 1)],
  ["rival strategy: keep the shared core", mockEntryAdviceEnvelope(35249001, "ortak-koru", 1)],
  ["rival strategy: create a gap", mockEntryAdviceEnvelope(35249001, "fark-yarat", 1)],
  [
    "rival strategy on an unproven control",
    {
      ...mockEntryAdviceEnvelope(35249001, "fark-yarat", 1),
      payload: {
        ...mockEntryAdviceEnvelope(35249001, "fark-yarat", 1).payload,
        control_solver_status: "FEASIBLE",
        control_optimality_gap: 0.4,
      },
    },
  ],
  [
    "partial data",
    withAdvice({ data_quality: "partial", missing_fields: ["free_transfers"], moves: [] }),
  ],
  ["legacy document without solver fields", withAdvice({})],
  // The multi-week window: the per-week table, the stated limits and the found-not-proven
  // badge, all in expected points and plain sentences.
  ["three-week window", mockEntryAdviceEnvelope(35249001, "saf-puan", 3)],
  ["five-week window", mockEntryAdviceEnvelope(35249001, "saf-puan", 5)],
];

describe("no advice state shows a probability, in either language", () => {
  for (const language of ["tr", "en"] as const) {
    for (const [name, advice] of STATES) {
      it(`${language}: ${name}`, () => {
        const text = renderState(language, advice);
        expect(text.length).toBeGreaterThan(0);
        const match = text.match(FORBIDDEN);
        expect(match, match ? `forbidden fragment: …${match[0]}…` : undefined).toBeNull();
        expect(text.match(MODE_PROMISE)).toBeNull();
      });
    }
  }
});

/** One scoreboard, in the state named: a netted Top-100, a gross one, or nothing finished. */
function mockScoreboardEnvelope(state: "net" | "gross" | "empty"): LeagueViewEnvelope<Scoreboard> {
  const week: ScoreboardGameweek = {
    gameweek: 3,
    deadline_utc: "2026-09-04T17:30:00Z",
    finished: state !== "empty",
    data_checked: false,
    average_entry_score: 51,
    highest_score: 119,
    ours: {
      net: 26,
      xi: 26,
      hits: 0,
      projected: 56.1,
      mode: "replay",
      scoring_basis: "named_eleven_no_autosubs",
      vice_captain_named: false,
    },
    top100:
      state === "net"
        ? {
            gameweek: 3,
            basis: "net",
            mean_score: 68.75,
            hit_points: 4,
            picks_snapshot_id: "fpl-elite-picks-test",
            cohort_size: 100,
            final: true,
          }
        : {
            gameweek: 3,
            basis: "gross",
            mean_score: 68.79,
            hit_points: null,
            picks_snapshot_id: null,
            cohort_size: 100,
            final: true,
          },
    members: [],
    members_mean_net: 58.7,
    members_counted: 15,
  };
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-09-07T13:20:00Z",
    source_kind: "live",
    payload: {
      season: "2026-27",
      league_id: 352490,
      source_snapshot_id: "fpl-live-20260907T131414Z-db9314d00961",
      captured_at_utc: "2026-09-07T13:14:14Z",
      cohort_snapshot_id: "fpl-top100-test",
      cohort_picks_snapshot_id: state === "net" ? "fpl-elite-picks-test" : null,
      registered_members: 15,
      histories_held: 15,
      gameweeks: [week],
      cumulative: {
        through_gameweek: state === "empty" ? null : 3,
        gameweeks: state === "empty" ? [] : [3],
        ours_net: state === "empty" ? null : 26,
        ours_gameweeks: state === "empty" ? [] : [3],
        members_mean_total_points: state === "empty" ? null : 199.2,
        members_gameweeks: state === "empty" ? [] : [3],
        members_counted: state === "empty" ? 0 : 15,
        average_entry_score: state === "empty" ? null : 182,
      },
    },
  };
}

// The scoreboard card lives on /league, not on the member page, so the states above
// never render it: a probability could reach a published page through the one surface
// this gate did not cover. Same regex, both languages, both Top-100 bases.
const SCOREBOARD_STATES: Array<[string, LeagueViewEnvelope<Scoreboard>]> = [
  ["net Top-100", mockScoreboardEnvelope("net")],
  ["gross Top-100", mockScoreboardEnvelope("gross")],
  ["nothing finished", mockScoreboardEnvelope("empty")],
];

describe("the weekly scoreboard shows no probability, in either language", () => {
  for (const language of ["tr", "en"] as const) {
    for (const [name, envelope] of SCOREBOARD_STATES) {
      it(`${language}: ${name}`, () => {
        const { container, unmount } = render(
          <LanguageProvider initialLanguage={language}>
            <ScoreboardCard envelope={envelope} />
          </LanguageProvider>,
        );
        const text = container.textContent ?? "";
        unmount();
        expect(text.length).toBeGreaterThan(0);
        const match = text.match(FORBIDDEN);
        expect(match, match ? `forbidden fragment: …${match[0]}…` : undefined).toBeNull();
      });
    }
  }
});

/**
 * The same rule applied to the two numbers a move card used to overstate: the week's
 * hit charge, which the game takes once for the week and the card printed once per move,
 * and the caption, which claimed a longer window under a one-week plan.
 */
const MOVE: EntryAdvice["moves"][number] = {
  move_id: "gw02-1",
  player_out: {
    player_id: 901,
    name: "Static Winger",
    short_name: "Winger",
    position: "MID",
    team: "HAR",
  },
  player_in: {
    player_id: 902,
    name: "Computed Midfielder",
    short_name: "Midfielder",
    position: "MID",
    team: "HAR",
  },
  expected_points_delta: 2.5,
  reason_code: "points_gain",
};

describe("a move card claims only what the payload carries", () => {
  it("states the week's hit charge once, not once per move", () => {
    const advice = withAdvice({
      moves: [MOVE, { ...MOVE, move_id: "gw02-2" }],
      transfer_hit_points: 4,
    });
    for (const [language, needle] of [
      ["en", /expected-point cost/g],
      ["tr", /beklenen puan maliyeti/g],
    ] as const) {
      const text = renderState(language, advice);
      expect(text.match(needle)).toHaveLength(1);
    }
  });

  it("says nothing about a hit on a document published without the week's charge", () => {
    const legacy = withAdvice({ moves: [MOVE] });
    delete (legacy.payload as { transfer_hit_points?: number }).transfer_hit_points;
    expect(renderState("en", legacy)).not.toMatch(/expected-point cost/);
  });

  it("does not caption a one-week plan with a longer window", () => {
    const advice = withAdvice({ moves: [MOVE], transfer_hit_points: 0 });
    expect(advice.payload.window).toBe(1);
    const english = renderState("en", advice);
    expect(english).not.toMatch(/longer window/);
    expect(english).toMatch(/Part of the one-week pure-points plan/);
    const turkish = renderState("tr", advice);
    expect(turkish).not.toMatch(/Uzun pencere/);
    expect(turkish).toMatch(/Bir haftalık saf puan planının parçası/);
  });

  it("keeps the longer-window caption for a window that solved one", () => {
    const window = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
    expect(window.payload.moves[0]?.reason_code).toBe("window_value");
    expect(renderState("en", window)).toMatch(/longer window/);
  });
});
