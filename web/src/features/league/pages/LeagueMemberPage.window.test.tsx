/**
 * A three- or five-week window on the card: the first week's moves and lineup as before,
 * then one row per gameweek and the limits the producer states — as sentences the reader
 * can act on in either language, never as a promise about the later weeks.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  NO_CHIP_STATED_LIMIT,
  WINDOW_STATED_LIMITS,
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
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
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
        />
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
    // What the window assumes is its own region now, beside every other plan's.
    expect(screen.getByRole("region", { name: "Bu pencerenin varsaydıkları" })).toBeInTheDocument();
    // The first week's moves and lineup still render above, unchanged in shape: the
    // eleven on the pitch, and the same week as a list one toggle away.
    expect(screen.getByRole("list", { name: MESSAGES.tr.squad.pitchLabel })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: MESSAGES.tr.leagueMembers.viewList }));
    expect(screen.getByRole("region", { name: "Bu haftaki kadron" })).toBeInTheDocument();
    expect(screen.getByText("Kanıt tamamlanamadı")).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)("translates each known published limit in %s", (language) => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 5);
    const copy = MESSAGES[language].leagueMembers;
    for (const sentence of WINDOW_STATED_LIMITS) {
      expect(Object.hasOwn(copy.statedLimits, sentence), sentence).toBe(true);
    }
    renderAdvice(advice, language);
    const section = screen.getByRole("region", { name: copy.windowTitle(5) });
    const limits = screen.getByRole("region", { name: copy.windowLimitsLabel });
    const items = within(limits).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(
      WINDOW_STATED_LIMITS.map((sentence) => copy.statedLimits[sentence]),
    );
    expect(
      within(section).getByRole("columnheader", { name: copy.windowHits }),
    ).toBeInTheDocument();
    if (language === "tr") expect(section).not.toHaveTextContent(/capture|\bhit\b/i);
  });

  it.each(["tr", "en"] as const)(
    "keeps unknown and inherited published limits neutral in %s",
    (language) => {
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
      const raw = [
        "A sentence the site has never seen.",
        "__proto__",
        "toString",
        "probability 97% chance",
      ];
      const published = [WINDOW_STATED_LIMITS[0]!, ...raw];
      const advice = {
        ...base,
        payload: { ...base.payload, stated_limits: [...published] },
      };
      renderAdvice(advice, language);
      const copy = MESSAGES[language].leagueMembers;
      const section = screen.getByRole("region", { name: copy.windowTitle(3) });
      const limits = screen.getByRole("region", { name: copy.windowLimitsLabel });
      const items = within(limits).getAllByRole("listitem");
      expect(items.map((item) => item.textContent)).toEqual([
        copy.statedLimits[WINDOW_STATED_LIMITS[0]!],
        ...raw.map(() => copy.statedLimitUnknown),
      ]);
      for (const sentence of raw) expect(limits).not.toHaveTextContent(sentence);
      expect(advice.payload.stated_limits).toEqual(published);
      expect(within(section).getByText(copy.windowWeekOf(2))).toBeInTheDocument();
      expect(within(limits).getByText(copy.windowLimitsLabel)).toBeInTheDocument();
    },
  );

  it("shows no window for a one-week document", () => {
    renderAdvice(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    expect(screen.queryByRole("region", { name: /haftalık pencere/ })).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "still says the one-week plan was never offered a chip in %s",
    (language) => {
      const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const copy = MESSAGES[language].leagueMembers;
      expect(advice.payload.stated_limits).toEqual([NO_CHIP_STATED_LIMIT]);
      renderAdvice(advice, language);

      // A one-week document names the plan, not a window nobody can see.
      const limits = screen.getByRole("region", { name: copy.planLimitsLabel });
      expect(
        within(limits)
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual([copy.statedLimits[NO_CHIP_STATED_LIMIT]]);
      expect(screen.queryByRole("region", { name: copy.windowLimitsLabel })).toBeNull();
    },
  );
});
