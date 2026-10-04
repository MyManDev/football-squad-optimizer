/**
 * Every number on the advice card means what its label says.
 *
 * The card used to print three different quantities in the same units: a raw difference
 * between two players' projections on each move row, the eleven with the captain doubled
 * as the lineup total, and the planner's own objective as the solver's bound. This holds
 * the repair: the boards and the lineup total are one basis, the boards add up to the plan's
 * gain against holding the squad, and a figure that rounds to zero is never given a sign.
 *
 * In direction D a move is a substitution board whose LED figure is its share, and the
 * plan's gain is the gain strip's figure with the sentence that names its basis beside it.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
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
import { withLeague } from "../../../testSupport/league";

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
      <MemoryRouter
        initialEntries={[`/league/352490/members/${ENTRY}?window=${advice.payload.window}`]}
      >
        {withLeague(
          <LeagueMemberView
            index={mockEntryAdviceIndex(ENTRY).payload}
            squad={mockEntrySquadEnvelopes[ENTRY]}
            advice={advice}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
  return document.body.textContent ?? "";
}

/** The substitution boards, in the order the plan publishes its moves. */
function boards(): HTMLElement[] {
  const decision = screen.getByRole("region", { name: COPY.decisionTitle });
  return within(decision).getAllByRole("article");
}

/** The gain strip's figure and the sentence beside it, as one line of text. */
function gainLine(caption: string): string {
  return screen.getByText(caption).closest("p")?.textContent ?? "";
}

function withPayload(patch: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...patch } };
}

describe("the card states one basis for the rows, the total and the gain", () => {
  it("prints each board's share and the plan's gain as the eleven with the captain doubled", () => {
    const text = renderAdvice(
      withPayload({
        moves: [move("m1", 1.2), move("m2", 0.5)],
        expected_gain_vs_hold: 1.7,
        transfer_hit_points: 0,
      }),
    );

    const [first, second] = boards();
    expect(within(first!).getByText("+1.2")).toBeInTheDocument();
    expect(within(second!).getByText("+0.5")).toBeInTheDocument();
    for (const board of [first!, second!]) {
      expect(within(board).getByText(COPY.boardGainLabel)).toBeInTheDocument();
    }
    // The boards are read in order, which is what makes them add up, and the total they
    // add up to is on the page beside them as a bare figure.
    expect(text).toContain(COPY.moveRowsBasis);
    const figure = screen.getByText("+1.7", { selector: "strong" });
    expect(figure.nextElementSibling).toHaveClass("visually-hidden");
    expect(figure.closest("p")?.textContent).toBe(`+1.7 ${COPY.boardGainLabel}`);
  });

  it("names the week's transfer cost in the gain sentence when the plan pays one", () => {
    const text = renderAdvice(
      withPayload({
        moves: [move("m1", 3.5)],
        expected_gain_vs_hold: 3.5,
        transfer_hit_points: 4,
      }),
    );

    expect(text).toContain(COPY.gainCaptionBeforeCost("4.0"));
    expect(gainLine(COPY.gainCaptionBeforeCost("4.0"))).toBe(
      `+3.5 ${COPY.gainCaptionBeforeCost("4.0")}`,
    );
  });

  it("prints no gain sentence where the producer measured none", () => {
    // Both pay a hit, so a measured gain would carry its sentence; these print none.
    const unmeasured = withPayload({
      moves: [move("m1", null)],
      expected_gain_vs_hold: null,
      transfer_hit_points: 4,
    });

    expect(renderAdvice(unmeasured)).not.toContain("over making no transfer");

    cleanup();
    const absent = withPayload({ moves: [move("m1", 1.2)], transfer_hit_points: 4 });
    delete (absent.payload as { expected_gain_vs_hold?: number | null }).expected_gain_vs_hold;

    expect(renderAdvice(absent)).not.toContain("over making no transfer");

    cleanup();
    const measured = withPayload({
      moves: [move("m1", 1.2)],
      expected_gain_vs_hold: 1.2,
      transfer_hit_points: 4,
    });
    expect(renderAdvice(measured)).toContain("over making no transfer");
  });

  it("says a row's share was not published rather than printing it as zero", () => {
    const text = renderAdvice(
      withPayload({ moves: [move("m1", null)], expected_gain_vs_hold: null }),
    );

    expect(text).toContain(COPY.projectedGainUnknown);
    const [board] = boards();
    expect(within(board!).getByText(COPY.projectedGainUnknown)).toBeInTheDocument();
    expect(within(board!).queryByText(COPY.boardGainLabel)).toBeNull();
    expect(board!.textContent).not.toMatch(/[+−-]?0[.,]0\b/);
  });

  it("does not relabel an older document's row as a share of a gain it never published", () => {
    // Before the producer measured shares, a row carried the raw difference between the
    // two players' own projections. Printing that under this label would be the same
    // claim the repair removed, made about a document that cannot support it.
    const legacy = withPayload({ moves: [move("m1", 2.5)] });
    delete (legacy.payload as { expected_gain_vs_hold?: number | null }).expected_gain_vs_hold;
    const text = renderAdvice(legacy);

    expect(text).toContain(COPY.projectedGainUnknown);
    expect(text).not.toContain("+2.5");
    const [board] = boards();
    expect(within(board!).queryByText(COPY.boardGainLabel)).toBeNull();
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

describe("the solver's bound is not printed", () => {
  it("says nothing about a one-week bound", () => {
    const text = renderAdvice(withPayload({ solver_status: "FEASIBLE", optimality_gap: 1.1 }));

    expect(text).toContain("Your gameweek");
    expect(text).not.toMatch(/could not finish the proof/);
    expect(text).not.toMatch(/gap ≤ 1\.1 pts/);
    expect(text).not.toMatch(/within 1\.1 of the best value/);
  });

  it("says nothing about a window bound either", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 5);
    const weeks = base.payload.plan_weeks!.length;
    const text = renderAdvice(base);

    expect(weeks).toBe(5);
    expect(base.payload.solver_status).toBe("FEASIBLE");
    expect(text).toContain("Your gameweek");
    expect(text).not.toMatch(/could not finish the proof/);
    expect(text).not.toMatch(/gameweeks of the plan at once/);
  });
});
