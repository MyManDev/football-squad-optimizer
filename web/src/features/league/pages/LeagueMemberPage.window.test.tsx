/**
 * A three- or five-week window on the card: the first week's moves and lineup as before,
 * then one row per gameweek and the limits the producer states — as sentences the reader
 * can act on in either language, never as a promise about the later weeks.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  WINDOW_STATED_LIMITS,
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function renderAdvice(advice: LeagueViewEnvelope<EntryAdvice>, language: "tr" | "en" = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?window=${advice.payload.window}`]}>
        <LeagueMemberView squad={mockEntrySquadEnvelopes[ENTRY]} advice={advice} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the advice card shows a window week by week", () => {
  it("renders one row per gameweek with transfers, hit points, chip and expected points", () => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    const weeks = advice.payload.plan_weeks!;
    expect(weeks).toHaveLength(3);
    renderAdvice(advice);

    const section = screen.getByRole("region", { name: "3 haftalık pencere" });
    const rows = within(section).getAllByRole("row");
    expect(rows).toHaveLength(1 + weeks.length);
    expect(within(rows[1]!).getByText("OH2")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(weeks[0]!.transfers_in[0]!.name)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(weeks[0]!.transfers_out[0]!.name)).toBeInTheDocument();
    // The paid transfer's hit points and the last week's chip are on their rows.
    expect(within(rows[2]!).getByText("4")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Bench Boost")).toBeInTheDocument();
    expect(within(section).getByText("Bu pencerenin varsaydıkları")).toBeInTheDocument();
    // The first week's moves and lineup still render above, unchanged in shape.
    expect(screen.getByRole("region", { name: "Bu haftaki kadron" })).toBeInTheDocument();
    expect(screen.getByText("Kanıt tamamlanamadı")).toBeInTheDocument();
  });

  it("states every limit the producer sends, translated where the site knows it", () => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 5);
    const known = MESSAGES.tr.leagueMembers.statedLimits;
    for (const sentence of WINDOW_STATED_LIMITS) {
      expect(known[sentence], sentence).toBeTruthy();
    }
    renderAdvice(advice);
    const section = screen.getByRole("region", { name: "5 haftalık pencere" });
    const items = within(section).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(
      WINDOW_STATED_LIMITS.map((sentence) => known[sentence]),
    );
    expect(
      within(section).getByText(/İlk haftanın projeksiyonu sonraki haftalarda tekrarlanır/),
    ).toBeInTheDocument();
  });

  it("shows the producer's own words in English and for a sentence it does not know", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    const stranger = "A sentence the site has never seen.";
    renderAdvice(
      {
        ...base,
        payload: { ...base.payload, stated_limits: [WINDOW_STATED_LIMITS[0]!, stranger] },
      },
      "en",
    );
    const section = screen.getByRole("region", { name: "The 3-week window" });
    expect(within(section).getByText(WINDOW_STATED_LIMITS[0]!)).toBeInTheDocument();
    expect(within(section).getByText(stranger)).toBeInTheDocument();
    expect(within(section).getByText("GW2")).toBeInTheDocument();
    expect(within(section).getByText("What this window assumes")).toBeInTheDocument();
  });

  it("shows no window for a one-week document", () => {
    renderAdvice(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    expect(screen.queryByRole("region", { name: /haftalık pencere/ })).toBeNull();
  });
});
