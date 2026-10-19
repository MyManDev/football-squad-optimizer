import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { forgetCounts } from "../../../design/countMotion";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdviceLineupExpectation } from "../types";
import { ExpectedLineup } from "./ExpectedLineup";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);
const expectation: AdviceLineupExpectation = {
  version: "expected_lineup_v1",
  expected_net_points: 42.75,
  starting_points: 38,
  autosub_points: 2.5,
  captain_bonus_points: 6,
  vice_bonus_points: 0.25,
  bench_boost_points: 0,
  assumptions: [
    "independent_player_week_appearances",
    "any_positive_gameweek_minutes_including_cameos_block_autosubs",
  ],
};

it.each(["tr", "en"] as const)(
  "explains automatic substitutes and vice recovery in %s",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      transfer_hit_points: 4,
      lineup_expectation: expectation,
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <ExpectedLineup view={view} />
      </LanguageProvider>,
    );
    const region = screen.getByTestId("lineup-expectation");
    expect(region).toHaveTextContent(
      language === "tr"
        ? "Yedeklere sabit bir puan payı eklenmez"
        : "No fixed share of bench points is added",
    );
    expect(region).toHaveTextContent(
      language === "tr" ? "yardımcısının ek puanı" : "Vice-captain bonus",
    );
    expect(region).not.toHaveTextContent(
      language === "tr" ? "birbirinden bağımsız" : "treated as independent",
    );
    expect(region).not.toHaveTextContent(
      language === "tr" ? "Oynama varsayımları" : "Playing assumptions",
    );
    expect(region).not.toHaveTextContent("independent_player_week_appearances");
  },
);

it("keeps legacy documents unchanged and rejects invalid expected scores", () => {
  const view = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  render(
    <LanguageProvider initialLanguage="en">
      <ExpectedLineup view={view} />
    </LanguageProvider>,
  );
  expect(screen.queryByTestId("lineup-expectation")).not.toBeInTheDocument();
  expect(isAdvicePayload({ ...view, lineup_expectation: expectation })).toBe(true);
  expect(
    isAdvicePayload({ ...view, lineup_expectation: { ...expectation, vice_bonus_points: NaN } }),
  ).toBe(false);
  expect(
    isAdvicePayload({ ...view, lineup_expectation: { ...expectation, scoring_multipliers: {} } }),
  ).toBe(false);
});

/** Runs `test` with a stand-in `element.animate` and motion allowed, and returns its calls. */
function withCounting(test: (animate: ReturnType<typeof vi.fn>) => void): void {
  const animate = vi.fn(() => ({
    effect: { getComputedTiming: () => ({ progress: 0 }) },
    playState: "running",
    addEventListener: () => undefined,
    cancel: () => undefined,
  }));
  Object.defineProperty(HTMLElement.prototype, "animate", { value: animate, configurable: true });
  vi.stubGlobal("matchMedia", () => ({ matches: false }) as MediaQueryList);
  vi.stubGlobal("requestAnimationFrame", () => 0);
  try {
    test(animate);
  } finally {
    forgetCounts();
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as { animate?: unknown }).animate;
  }
}

const base = mockEntryAdviceEnvelope(101, "saf-puan", 1).payload;
const planWithNet = (net: number, leagueId = base.league_id) => ({
  ...base,
  league_id: leagueId,
  lineup_expectation: { ...expectation, expected_net_points: net },
});
const lineup = (net: number, leagueId?: number) => (
  <LanguageProvider initialLanguage="en">
    <ExpectedLineup view={planWithNet(net, leagueId)} />
  </LanguageProvider>
);

it("counts the net expected points when the shown plan changes, also after a remount", () => {
  withCounting((animate) => {
    const { rerender, unmount } = render(lineup(42.75));
    expect(animate).not.toHaveBeenCalled();
    rerender(lineup(42.75));
    expect(animate).not.toHaveBeenCalled();
    rerender(lineup(46.5));
    expect(animate).toHaveBeenCalledTimes(1);
    // The details are unmounted while the next plan loads; the count still starts from 46.5.
    unmount();
    render(lineup(44));
    expect(animate).toHaveBeenCalledTimes(2);
  });
});

it("writes the same entry's first figure in another league as it is", () => {
  withCounting((animate) => {
    render(lineup(42.75)).unmount();
    render(lineup(44, base.league_id + 1));
    expect(animate).not.toHaveBeenCalled();
    expect(screen.getByTestId("lineup-expectation")).toHaveTextContent("44.0");
  });
});
