import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { ChipForecastCard } from "../components/ChipForecastCard";
import type { EntrySquad } from "../types";
import { readChipForecast, type ForecastDocument } from "./chipForecast";
import { CHIP_FORECAST_COPY } from "./chipForecastCopy";

afterEach(cleanup);

function fixture() {
  const squad: EntrySquad = structuredClone(mockEntrySquadEnvelopes[35249001].payload);
  const week = squad.gameweek;
  squad.chips = {
    known: true,
    gameweek: week,
    states: Object.fromEntries(
      ["bboost", "3xc"].map((name) => [
        name,
        {
          first_half: {
            state: "available",
            gameweek: null,
            start_event: 1,
            stop_event: 19,
          },
          second_half: null,
        },
      ]),
    ),
  };
  const ids = [...squad.starting_xi, ...squad.bench].map((p) => p.player_id);
  const doc: ForecastDocument = {
    contract_version: "chip_forecast_v1",
    decision_gameweek: week,
    threshold_policy: "decaying",
    reserve: false,
    later_week_basis: "this_week_projection_scaled_by_relative_fixture_count_v1",
    players_without_fixture_this_week: [],
    limits: ["Fixture only"],
    chips: ["bboost", "3xc"].map((name) => ({
      name: name as "bboost" | "3xc",
      window: { first_gameweek: 1, last_gameweek: 19 },
      holding_value: 20,
      verdict: "hold",
      hold_reason: "gain_not_above_threshold",
      gain_this_week: -2,
      threshold_this_week: 10,
      reservation_allows_this_week: true,
      points_at_gameweek:
        name === "3xc"
          ? {
              gameweek: week + 1,
              estimated_gain: 12,
              threshold: 9,
              player_ids: [ids[0]],
            }
          : null,
      structured_gameweeks: null,
    })),
  };
  const envelope = {
    season: squad.season,
    league_id: squad.league_id,
    entry_id: squad.entry.entry_id,
    gameweek: week,
    source_snapshot_id: squad.source_snapshot_id,
    squad_player_ids: ids,
    bench_player_ids: squad.bench.map((p) => p.player_id),
    status: "available",
    reason: null,
    forecast: doc,
    calendar_has_structure: false,
    calendar_range: { first_gameweek: week + 1, last_gameweek: 19 },
  };
  return { squad, envelope, doc };
}

it("old publications remain absent and a complete identity-bound document is usable", () => {
  const { squad, envelope } = fixture();
  expect(readChipForecast(undefined, squad)).toEqual({ kind: "absent" });
  expect(readChipForecast(envelope, squad).kind).toBe("ready");
  expect(readChipForecast({ ...envelope, source_snapshot_id: "different" }, squad)).toEqual({
    kind: "refused",
    reason: "capture_mismatch",
  });
  expect(readChipForecast({ ...envelope, entry_id: 99 }, squad).kind).toBe("refused");
});

it("refuses duplicate chips, a false play verdict, or a later player outside the held squad", () => {
  const { squad, envelope } = fixture();
  const duplicate = structuredClone(envelope);
  duplicate.forecast.chips[1] = duplicate.forecast.chips[0];
  expect(readChipForecast(duplicate, squad).kind).toBe("refused");
  const falsePlay = structuredClone(envelope);
  falsePlay.forecast.chips[0].verdict = "play_now";
  expect(readChipForecast(falsePlay, squad).kind).toBe("refused");
  const foreign = structuredClone(envelope);
  foreign.forecast.chips[1].points_at_gameweek!.player_ids = [999999];
  expect(readChipForecast(foreign, squad).kind).toBe("refused");
  const incomplete = structuredClone(envelope);
  incomplete.forecast.chips.pop();
  expect(readChipForecast(incomplete, squad).kind).toBe("refused");
});

it.each(["en", "tr"] as const)(
  "shows two independent readings and honest copy in %s",
  (language) => {
    const { squad, envelope } = fixture();
    const fresh = structuredClone(envelope);
    fresh.forecast.chips[1].gain_this_week = null;
    fresh.forecast.chips[1].verdict = "unknown_this_week";
    fresh.forecast.chips[1].hold_reason = null;
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <ChipForecastCard published={envelope} computed={fresh} squad={squad} />
      </LanguageProvider>,
    );
    const copy = CHIP_FORECAST_COPY[language];
    const published = screen.getByRole("region", { name: copy.published });
    const computed = screen.getByRole("region", { name: copy.computed });
    expect(within(published).queryByText(copy.unknown)).not.toBeInTheDocument();
    expect(within(computed).getAllByText(copy.unknown).length).toBeGreaterThan(0);
    expect(screen.getByText(copy.separate)).toBeInTheDocument();
    expect(screen.getByText(copy.evidence)).toBeInTheDocument();
    expect(screen.getByText(copy.limits)).toBeInTheDocument();
    expect(screen.getByText(copy.action)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.querySelector("button")).toBeNull();
  },
);

it("distinguishes a blank bench from no later threshold crossing", () => {
  const { squad, envelope } = fixture();
  envelope.forecast.players_without_fixture_this_week = [...envelope.bench_player_ids];
  render(
    <LanguageProvider initialLanguage="en">
      <ChipForecastCard published={envelope} squad={squad} />
    </LanguageProvider>,
  );
  expect(screen.getByText(CHIP_FORECAST_COPY.en.noEstimate)).toBeInTheDocument();
  expect(screen.queryByText(CHIP_FORECAST_COPY.en.noLater)).not.toBeInTheDocument();
});

it("names unscheduled fixtures and never renders untrusted refusal text", () => {
  const { squad, envelope } = fixture();
  const refused = {
    ...envelope,
    status: "unavailable",
    forecast: null,
    reason: "fixtures_unscheduled",
    calendar_has_structure: null,
    calendar_range: null,
  };
  const view = render(
    <LanguageProvider initialLanguage="en">
      <ChipForecastCard published={refused} squad={squad} />
    </LanguageProvider>,
  );
  expect(view.container.textContent).toContain(CHIP_FORECAST_COPY.en.reasons.fixtures_unscheduled);
  view.rerender(
    <LanguageProvider initialLanguage="en">
      <ChipForecastCard published={{ ...refused, reason: "invented certainty" }} squad={squad} />
    </LanguageProvider>,
  );
  expect(view.container.textContent).not.toContain("invented certainty");
});

it("every new bilingual sentence passes the shared honesty stem guard", () => {
  expect(JSON.stringify(CHIP_FORECAST_COPY)).not.toMatch(AS_A_CHANCE);
});

it.each(["en", "tr"] as const)(
  "refused calendar is never an ordinary-calendar claim in %s",
  (language) => {
    const { squad, envelope } = fixture();
    const refused = {
      ...envelope,
      status: "unavailable",
      reason: "fixtures_unscheduled",
      forecast: null,
      calendar_has_structure: null,
      calendar_range: null,
    };
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <ChipForecastCard published={refused} squad={squad} />
      </LanguageProvider>,
    );
    const copy = CHIP_FORECAST_COPY[language];
    expect(container.textContent).toContain(copy.calendarNull);
    expect(container.textContent).not.toContain(copy.calendarFalse);
    expect(container.textContent).not.toContain(copy.calendarTrue);
    expect(container.textContent).toContain(copy.calendar);
  },
);

it("names the examined window even without a Free Hit row", () => {
  const { squad, envelope } = fixture();
  const view = render(
    <LanguageProvider initialLanguage="en">
      <ChipForecastCard published={envelope} squad={squad} />
    </LanguageProvider>,
  );
  expect(view.container.textContent).toContain(
    `${CHIP_FORECAST_COPY.en.calendarFalse}: ${squad.gameweek + 1} to 19`,
  );
  view.rerender(
    <LanguageProvider initialLanguage="en">
      <ChipForecastCard published={{ ...envelope, calendar_has_structure: true }} squad={squad} />
    </LanguageProvider>,
  );
  expect(view.container.textContent).toContain(CHIP_FORECAST_COPY.en.calendarTrue);
  expect(view.container.textContent).not.toContain(CHIP_FORECAST_COPY.en.calendarFalse);
});
