import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { LeagueWeekView } from "../../../data/schema";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AverageChart } from "./AverageChart";

afterEach(cleanup);

function week(gameweek: number, ours: number | null, average: number | null): LeagueWeekView {
  return {
    gameweek,
    our_realized_net_score: ours,
    average_entry_score: average,
    difference_to_average: ours !== null && average !== null ? ours - average : null,
    deadline_utc: "2026-08-01T12:00:00Z",
    finished: true,
    highest_score: null,
    our_projected_score: null,
    our_realized_score: null,
  };
}

function chart(weeks: LeagueWeekView[], language: Language = "en") {
  const { container } = render(
    <LanguageProvider initialLanguage={language}>
      <AverageChart weeks={weeks} />
    </LanguageProvider>,
  );
  const bars = [...container.querySelectorAll("rect")];
  const zero = Number(container.querySelector('line[class*="zero"]')?.getAttribute("y1"));
  return { container, bars, zero };
}

describe("average chart score range", () => {
  it.each([
    ["mixed", [-8, 12], [4, 20]],
    ["all negative", [-8, -2], [-6, -4]],
    ["zero", [0, 0], [0, 0]],
    ["positive", [8, 12], [6, 20]],
  ] as const)(
    "draws %s scores from zero with nonnegative heights inside the plot",
    (_, ours, averages) => {
      const { container, bars, zero } = chart(
        ours.map((score, i) => week(i + 1, score, averages[i])),
      );
      expect(bars).toHaveLength(2);
      expect(zero).toBeGreaterThanOrEqual(12);
      expect(zero).toBeLessThanOrEqual(174);
      bars.forEach((bar, i) => {
        const top = Number(bar.getAttribute("y"));
        const height = Number(bar.getAttribute("height"));
        expect(top).toBeGreaterThanOrEqual(12);
        expect(height).toBeGreaterThanOrEqual(0);
        expect(top + height).toBeLessThanOrEqual(174);
        if (ours[i] < 0) {
          expect(top).toBeCloseTo(zero);
          expect(height).toBeGreaterThan(0);
        } else {
          expect(top + height).toBeCloseTo(zero);
          if (ours[i] === 0) expect(height).toBe(0);
          if (ours[i] > 0) expect(height).toBeGreaterThan(0);
        }
      });
      container.querySelectorAll("circle").forEach((dot) => {
        const cy = Number(dot.getAttribute("cy"));
        expect(cy).toBeGreaterThanOrEqual(12);
        expect(cy).toBeLessThanOrEqual(174);
      });
    },
  );

  it("leaves missing scores absent and keeps their gameweek spacing", () => {
    const { container, bars } = chart([
      week(1, -4, 10),
      week(2, null, 10),
      week(3, 5, null),
      week(4, 0, 10),
    ]);
    expect(bars).toHaveLength(2);
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(Number(bars[1].getAttribute("x")) - Number(bars[0].getAttribute("x"))).toBe(584);
    expect(bars[1]).toHaveAttribute("height", "0");
  });

  it("has no chart when no week has both scores", () => {
    chart([week(1, null, 10), week(2, 5, null)]);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "distinguishes the recorded net and official average in %s",
    (language) => {
      chart([week(1, -4, 10)], language);
      const copy = MESSAGES[language].league;
      expect(screen.getByRole("img", { name: copy.averageLabel(1) })).toBeInTheDocument();
      expect(screen.getByText(copy.ourNet)).toBeInTheDocument();
      expect(screen.getByText(copy.gameAverage)).toBeInTheDocument();
      expect(screen.getByText(copy.lastWeek("-14"))).toBeInTheDocument();
    },
  );
});
