import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { OfficialInformationCard, NewInformationNotice } from "./OfficialInformationCard";
import {
  isOfficialInformation,
  type OfficialInformation,
  type DecisionInformation,
} from "./informationFacts";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);
const information: OfficialInformation = {
  version: "fpl_information_v1",
  season: "2026-27",
  gameweek: 6,
  source_snapshot_id: "held-capture",
  observed_at: "2026-10-02T00:00:00Z",
  revision: "a".repeat(64),
  source_url: "https://fantasy.premierleague.com/",
  player_count: 667,
  team_count: 20,
  declared_team_count: 20,
  players: [
    {
      player_id: 118748,
      name: "Bukayo Saka",
      team_name: "Arsenal",
      status: "d",
      source_chance_percent: 75,
      source_added_at: "2026-10-01T16:00:00Z",
      news_state: "present",
    },
  ],
};
const decision: DecisionInformation = {
  version: "football_decision_information_v1",
  revision: "b".repeat(64),
  source_snapshot_id: "held-capture",
  observed_at: information.observed_at,
  coach_news_bound: false,
  minute_components_bound: true,
};
const view = {
  ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
  source_snapshot_id: "held-capture",
  prediction_model: {
    id: "football" as const,
    version: "football_team_share_v1" as const,
    experimental: true as const,
    fingerprint: "c".repeat(64),
  },
  official_information: information,
  decision_information: decision,
};

it.each(["tr", "en"] as const)("shows source date separately from check time in %s", (language) => {
  render(
    <LanguageProvider initialLanguage={language}>
      <OfficialInformationCard view={view} />
    </LanguageProvider>,
  );
  const card = screen.getByTestId("official-information");
  expect(card).toHaveTextContent("20/20");
  expect(card).toHaveTextContent("75/100");
  expect(card).toHaveTextContent("Bukayo Saka");
  expect(card.querySelectorAll("time")).toHaveLength(2);
  expect(card.querySelector("a")).toHaveAttribute("href", information.source_url);
  expect(card).toHaveTextContent(
    language === "tr" ? "ilk 11’de başlama garantisi" : "do not guarantee a start",
  );
  expect(isAdvicePayload(view)).toBe(true);
});

it("accepts zero and missing source value separately, rejects invalid and leaking payloads", () => {
  const change = (patch: object) => ({
    ...information,
    players: [{ ...information.players[0], ...patch }],
  });
  expect(isOfficialInformation(change({ source_chance_percent: 0 }))).toBe(true);
  expect(isOfficialInformation(change({ source_chance_percent: null }))).toBe(true);
  expect(isOfficialInformation(change({ source_chance_percent: 101 }))).toBe(false);
  expect(isOfficialInformation(change({ source_chance_percent: true }))).toBe(false);
  expect(isOfficialInformation(change({ raw_news: "private" }))).toBe(false);
  expect(isOfficialInformation({ ...information, source_url: "javascript:alert(1)" })).toBe(false);
  expect(
    isOfficialInformation({
      ...information,
      players: [...information.players, ...information.players],
    }),
  ).toBe(false);
});

it("announces changed decision information without replacing the shown plan or computing", () => {
  render(
    <LanguageProvider initialLanguage="tr">
      <NewInformationNotice view={view} latest={{ ...decision, revision: "d".repeat(64) }} />
    </LanguageProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Hesapla");
  expect(screen.getByRole("status")).toHaveTextContent("kendiliğinden değiştirilmedi");
});

it("does not announce unchanged information or another capture as this plan's update", () => {
  const { rerender } = render(
    <LanguageProvider initialLanguage="tr">
      <NewInformationNotice view={view} latest={decision} />
    </LanguageProvider>,
  );
  expect(screen.queryByRole("status")).toBeNull();
  rerender(
    <LanguageProvider initialLanguage="tr">
      <NewInformationNotice view={view} latest={{ ...decision, source_snapshot_id: "other" }} />
    </LanguageProvider>,
  );
  expect(screen.queryByRole("status")).toBeNull();
});

it.each(["tr", "en"] as const)(
  "compares actual source bindings without changing or recalculating the displayed plan in %s",
  (language) => {
    const original = JSON.stringify(view);
    const latest: DecisionInformation = {
      ...decision,
      revision: "d".repeat(64),
      observed_at: "2026-10-02T01:00:00Z",
      coach_news_bound: true,
      minute_components_bound: false,
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <NewInformationNotice view={view} latest={latest} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("information-binding-differences");
    expect(detail).not.toHaveAttribute("open");
    fireEvent.click(detail.querySelector("summary")!);
    expect(detail).toHaveAttribute("open");
    const rows = within(detail).getAllByRole("row");
    expect(
      within(rows[2]!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(language === "tr" ? ["Bağlı değil", "Bağlı"] : ["Not bound", "Bound"]);
    expect(
      within(rows[3]!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(language === "tr" ? ["Bağlı", "Bağlı değil"] : ["Bound", "Not bound"]);
    expect([...detail.querySelectorAll("time")].map((node) => node.dateTime)).toEqual([
      decision.observed_at,
      latest.observed_at,
    ]);
    expect(detail).toHaveTextContent(
      language === "tr"
        ? "bir açıklamanın uygulandığı veya puanların değiştiği anlamına gelmez"
        : "does not mean a statement was applied or points changed",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "gösterilen plan korunur" : "displayed plan is retained",
    );
    expect(detail).not.toHaveTextContent(decision.revision);
    expect(detail).not.toHaveTextContent(latest.revision);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(JSON.stringify(view)).toBe(original);
  },
);

it("does not invent a visible source change from a revision change alone", () => {
  render(
    <LanguageProvider initialLanguage="en">
      <NewInformationNotice view={view} latest={{ ...decision, revision: "d".repeat(64) }} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("information-binding-differences")).toHaveTextContent(
    "these summary fields are unchanged",
  );
});

it("keeps an absent previous revision and missing check time distinct from an unbound source", () => {
  const legacy = { ...view };
  delete (legacy as { decision_information?: DecisionInformation }).decision_information;
  render(
    <LanguageProvider initialLanguage="en">
      <NewInformationNotice view={legacy} latest={{ ...decision, observed_at: null }} />
    </LanguageProvider>,
  );
  const detail = screen.getByTestId("information-binding-differences");
  fireEvent.click(detail.querySelector("summary")!);
  const rows = within(detail).getAllByRole("row");
  expect(
    within(rows[1]!)
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ).toEqual(["Not recorded", "Not recorded"]);
  expect(
    within(rows[2]!)
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ).toEqual(["Not recorded", "Not bound"]);
  expect(detail.querySelector("time")).toBeNull();
});
