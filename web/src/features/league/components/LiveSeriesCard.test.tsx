import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { LiveSeriesCard } from "./LiveSeriesCard";

afterEach(cleanup);
describe.each<Language>(["en", "tr"])("live record in %s", (language) => {
  it.each([null, 11, 0])("explains the current accumulation from the record (%s)", (remaining) => {
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
  });
});
