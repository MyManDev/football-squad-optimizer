import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { LiveSeriesCard } from "./LiveSeriesCard";

afterEach(cleanup);
describe.each<Language>(["en", "tr"])("live record in %s", (language) => {
  it.each([null, 1, 11, 0])(
    "explains the current accumulation from the record (%s)",
    (remaining) => {
      const series = {
        memberWeeks: 2,
        weekClusters: 1,
        meanDifference: -2,
        weeks: [{ gameweek: 4, members: 2, meanDifference: -2 }],
        rows: [101, 202].map((entryId) => ({
          entryId,
          gameweek: 4,
          suggested: 26,
          actual: 28,
          difference: -2,
          recordKey: String(entryId),
        })),
      };
      const { container } = render(
        <MemoryRouter>
          <LanguageProvider initialLanguage={language}>
            <LiveSeriesCard series={series} remaining={remaining} unavailableMembers={1} />
          </LanguageProvider>
        </MemoryRouter>,
      );
      const copy = MESSAGES[language].liveSeries;
      expect(screen.getByText(copy.accumulated(2, 1))).toBeInTheDocument();
      expect(
        screen.getByText(
          remaining === null ? copy.unknown : remaining ? copy.remaining(remaining) : copy.reached,
        ),
      ).toBeInTheDocument();
      expect(screen.getByText(copy.missing(1))).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "101" })).toHaveAttribute(
        "href",
        "/league/members/101/history",
      );
      expect(container.textContent).not.toMatch(AS_A_CHANCE);
    },
  );
  it.each([2.5, -2.5, -0.04, 0.04, 0])(
    "formats every difference consistently (%s)",
    (difference) => {
      const expected = difference === 2.5 ? "+2.5" : difference === -2.5 ? "−2.5" : "0.0";
      const text = language === "tr" ? expected.replace(".", ",") : expected;
      const series = {
        memberWeeks: 1,
        weekClusters: 1,
        meanDifference: difference,
        weeks: [{ gameweek: 4, members: 1, meanDifference: difference }],
        rows: [
          { entryId: 101, gameweek: 4, suggested: 26, actual: 28, difference, recordKey: "101" },
        ],
      };
      const { container } = render(
        <MemoryRouter>
          <LanguageProvider initialLanguage={language}>
            <LiveSeriesCard series={series} remaining={null} unavailableMembers={0} />
          </LanguageProvider>
        </MemoryRouter>,
      );
      expect(screen.getByText(MESSAGES[language].liveSeries.mean(text))).toBeInTheDocument();
      for (const row of container.querySelectorAll("tbody tr"))
        expect(row.lastElementChild?.textContent).toBe(text);
    },
  );
});

it("uses the singular only for one remaining English week", () => {
  expect(MESSAGES.en.liveSeries.remaining(1)).toBe(
    "Not yet: the recorded measurement calls for 1 more settled week.",
  );
  expect(MESSAGES.en.liveSeries.remaining(2)).toBe(
    "Not yet: the recorded measurement calls for 2 more settled weeks.",
  );
});
