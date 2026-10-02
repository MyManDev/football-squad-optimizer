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
import { isAdvicePayload } from "../advice/adviceShape";

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
    expect(screen.queryByTestId(`week-lineup-${weeks[0]!.gameweek}`)).not.toBeInTheDocument();
    expect(within(rows[1]!).getByText("OH2")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(weeks[0]!.transfers_in[0]!.name)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(weeks[0]!.transfers_out[0]!.name)).toBeInTheDocument();
    // The paid transfer's hit points and the last week's chip are on their rows.
    expect(within(rows[2]!).getByText("4")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Bench Boost")).toBeInTheDocument();
    // What the window assumes is not listed on the page.
    expect(screen.queryByRole("region", { name: "Bu pencerenin varsaydıkları" })).toBeNull();
    // The first week's moves and lineup still render above, unchanged in shape: the
    // eleven on the pitch, and the same week as a list one toggle away.
    expect(screen.getByRole("list", { name: MESSAGES.tr.squad.pitchLabel })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: MESSAGES.tr.leagueMembers.viewList }));
    expect(screen.getByRole("region", { name: "Bu haftaki kadron" })).toBeInTheDocument();
    expect(screen.getByText("Kanıt tamamlanamadı")).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "holds a sentence for each published limit and lists none on the page in %s",
    (language) => {
      const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 5);
      const copy = MESSAGES[language].leagueMembers;
      for (const sentence of WINDOW_STATED_LIMITS) {
        expect(Object.hasOwn(copy.statedLimits, sentence), sentence).toBe(true);
      }
      const { container } = renderAdvice(advice, language);
      const section = screen.getByRole("region", { name: copy.windowTitle(5) });
      expect(screen.queryByRole("region", { name: copy.windowLimitsLabel })).toBeNull();
      for (const sentence of WINDOW_STATED_LIMITS) {
        expect(container).not.toHaveTextContent(copy.statedLimits[sentence]!);
      }
      expect(
        within(section).getByRole("columnheader", { name: copy.windowHits }),
      ).toBeInTheDocument();
      if (language === "tr") expect(section).not.toHaveTextContent(/capture|\bhit\b/i);
    },
  );

  it.each([3, 5] as const)("expands each distinct planned lineup across %s weeks", (window) => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", window);
    advice.payload.plan_weeks = advice.payload.plan_weeks!.map((week, index) => {
      const starting_xi = [...advice.payload.starting_xi!];
      const bench = [...advice.payload.bench!];
      if (index % 2) [starting_xi[10], bench[1]] = [bench[1]!, starting_xi[10]!];
      return {
        ...week,
        lineup: { starting_xi, bench, captain: starting_xi[0]!, vice_captain: starting_xi[1]! },
      };
    });
    expect(isAdvicePayload(advice.payload)).toBe(true);
    renderAdvice(advice);
    for (const week of advice.payload.plan_weeks) {
      const detail = screen.getByTestId(`week-lineup-${week.gameweek}`);
      fireEvent.click(within(detail).getByText(/Bu haftanın ilk 11’i ve yedekleri/));
      expect(detail).toHaveAttribute("open");
      expect(detail).toHaveTextContent(
        `İlk 11: ${week.lineup!.starting_xi.map((player) => player.name).join(", ")}`,
      );
      expect(detail).toHaveTextContent(`Yardımcı kaptan: ${week.lineup!.vice_captain.name}`);
      expect(detail).toHaveTextContent(
        `Yedek sırası: ${week.lineup!.bench.map((player) => player.name).join(" → ")}`,
      );
    }
    expect(advice.payload.plan_weeks[0]!.lineup!.starting_xi).not.toEqual(
      advice.payload.plan_weeks[1]!.lineup!.starting_xi,
    );
    advice.payload.plan_weeks[1]!.lineup!.bench.pop();
    expect(isAdvicePayload(advice.payload)).toBe(false);
  });

  it.each(["tr", "en"] as const)(
    "prints no published limit it has never seen in %s",
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
      const { container } = renderAdvice(advice, language);
      const copy = MESSAGES[language].leagueMembers;
      const section = screen.getByRole("region", { name: copy.windowTitle(3) });
      expect(screen.queryByRole("region", { name: copy.windowLimitsLabel })).toBeNull();
      for (const sentence of [raw[0]!, raw[3]!]) {
        expect(container).not.toHaveTextContent(sentence);
      }
      expect(container).not.toHaveTextContent(copy.statedLimitUnknown);
      expect(advice.payload.stated_limits).toEqual(published);
      expect(within(section).getByText(copy.windowWeekOf(2))).toBeInTheDocument();
    },
  );

  it("shows no window for a one-week document", () => {
    renderAdvice(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    expect(screen.queryByRole("region", { name: /haftalık pencere/ })).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "shows no assumptions under a one-week plan whose only limit is the chip one in %s",
    (language) => {
      const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const copy = MESSAGES[language].leagueMembers;
      expect(advice.payload.stated_limits).toEqual([NO_CHIP_STATED_LIMIT]);
      renderAdvice(advice, language);

      // The sentence is still in the document; the page leaves it, and the empty heading, out.
      expect(screen.queryByRole("region", { name: copy.planLimitsLabel })).toBeNull();
      expect(screen.queryByRole("region", { name: copy.windowLimitsLabel })).toBeNull();
      expect(document.body).not.toHaveTextContent(copy.statedLimits[NO_CHIP_STATED_LIMIT]!);
    },
  );
});
