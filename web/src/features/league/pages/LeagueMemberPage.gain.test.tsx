/**
 * Every number on the advice card means what its label says.
 *
 * The card used to print three different quantities in the same units: a raw difference
 * between two players' projections on each move row, the eleven with the captain doubled
 * as the lineup total, and the planner's own objective as the solver's bound. This holds
 * the repair: the rows and the lineup total are one basis, the rows add up to the plan's
 * gain against holding the squad, and a figure that rounds to zero is never given a sign.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { AdviceMove, EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const COPY = MESSAGES.en.leagueMembers;

function move(id: string, delta: number | null): AdviceMove {
  return {
    move_id: id,
    player_out: {
      player_id: 900 + Number(id.slice(1)),
      name: `Out ${id}`,
      short_name: "Out",
      position: "MID",
      team: "HAR",
    },
    player_in: {
      player_id: 910 + Number(id.slice(1)),
      name: `In ${id}`,
      short_name: "In",
      position: "MID",
      team: "HAR",
    },
    expected_points_delta: delta,
    reason_code: "points_gain",
  };
}

function renderAdvice(advice: LeagueViewEnvelope<EntryAdvice>, language: "tr" | "en" = "en") {
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?window=${advice.payload.window}`]}>
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
  return document.body.textContent ?? "";
}

function withPayload(patch: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...patch } };
}

describe("the card states one basis for the rows, the total and the gain", () => {
  it("prints each row and the plan's gain as the eleven with the captain doubled", () => {
    const text = renderAdvice(
      withPayload({
        moves: [move("m1", 1.2), move("m2", 0.5)],
        expected_gain_vs_hold: 1.7,
        transfer_hit_points: 0,
      }),
    );

    expect(text).toContain(COPY.projectedGain("+1.2"));
    expect(text).toContain(COPY.projectedGain("+0.5"));
    // The rows are read in order, which is what makes them add up, and the total they
    // add up to is on the page beside them.
    expect(text).toContain(COPY.moveRowsBasis);
    expect(text).toContain(COPY.planGainVsHold("+1.7"));
  });

  it("names the week's transfer cost in the gain sentence when the plan pays one", () => {
    const text = renderAdvice(
      withPayload({
        moves: [move("m1", 3.5)],
        expected_gain_vs_hold: 3.5,
        transfer_hit_points: 4,
      }),
    );

    expect(text).toContain(COPY.planGainVsHoldBeforeCost("+3.5", "4.0"));
    expect(text).not.toContain(COPY.planGainVsHold("+3.5"));
  });

  it("prints no gain sentence where the producer measured none", () => {
    const unmeasured = withPayload({ moves: [move("m1", null)], expected_gain_vs_hold: null });

    expect(renderAdvice(unmeasured)).not.toContain("against keeping the squad you hold");

    cleanup();
    const absent = withPayload({ moves: [move("m1", 1.2)] });
    delete (absent.payload as { expected_gain_vs_hold?: number | null }).expected_gain_vs_hold;

    expect(renderAdvice(absent)).not.toContain("against keeping the squad you hold");
    expect(COPY.planGainVsHold("+1.0")).toContain("against keeping the squad you hold");
  });

  it("says a row's share was not published rather than printing it as zero", () => {
    const text = renderAdvice(
      withPayload({ moves: [move("m1", null)], expected_gain_vs_hold: null }),
    );

    expect(text).toContain(COPY.projectedGainUnknown);
    expect(text).not.toContain(COPY.projectedGain("0.0"));
  });

  it("does not relabel an older document's row as a share of a gain it never published", () => {
    // Before the producer measured shares, a row carried the raw difference between the
    // two players' own projections. Printing that under this label would be the same
    // claim the repair removed, made about a document that cannot support it.
    const legacy = withPayload({ moves: [move("m1", 2.5)] });
    delete (legacy.payload as { expected_gain_vs_hold?: number | null }).expected_gain_vs_hold;
    const text = renderAdvice(legacy);

    expect(text).toContain(COPY.projectedGainUnknown);
    expect(text).not.toContain(COPY.projectedGain("+2.5"));
  });

  it("never prints a minus in front of a zero", () => {
    const advice = withPayload({
      moves: [move("m1", -0.04)],
      expected_gain_vs_hold: -0.04,
      transfer_hit_points: 0,
    });

    for (const language of ["en", "tr"] as const) {
      cleanup();
      expect(renderAdvice(advice, language)).not.toMatch(/[−-]0[.,]0\b/);
    }
  });
});

describe("the solver's bound is labelled for what it bounds", () => {
  it("calls a one-week bound a bound on the planner's objective, not on points", () => {
    const text = renderAdvice(withPayload({ solver_status: "FEASIBLE", optimality_gap: 1.1 }));

    expect(text).toContain(COPY.unprovenPlanBody("1.1"));
    expect(text).not.toMatch(/gap ≤ 1\.1 pts/);
  });

  it("says a window bound covers every gameweek of the plan at once", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 5);
    const weeks = base.payload.plan_weeks!.length;
    const text = renderAdvice(base);

    expect(weeks).toBe(5);
    expect(base.payload.solver_status).toBe("FEASIBLE");
    expect(text).toContain(
      COPY.unprovenPlanBodyWindow(base.payload.optimality_gap!.toFixed(1), weeks),
    );
  });
});
