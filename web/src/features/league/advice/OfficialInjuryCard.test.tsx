import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { OfficialInjuryCard } from "./OfficialInjuryCard";
import {
  isOfficialInjuryFacts,
  OFFICIAL_INJURY_LIMIT,
  type OfficialInjuryFacts,
} from "./officialInjuryFacts";

afterEach(cleanup);
const data: OfficialInjuryFacts = {
  contract_version: "official_pl_injuries_v1",
  season: "2026-27",
  source_url: "https://www.premierleague.com/en/latest-player-injuries",
  source_updated_at: "2026-10-01T15:50:00Z",
  observed_at: "2026-10-02T10:00:00Z",
  roster_clubs: ["Liverpool", "Man Utd"],
  received_clubs: ["Liverpool"],
  missing_clubs: ["Man Utd"],
  incomplete_clubs: ["Liverpool"],
  unknown_source_clubs: ["Unknown source club"],
  listed_rows: 3,
  mapped_rows: 2,
  facts: [
    {
      player_id: 10,
      club: "Liverpool",
      injury: "Ankle",
      source_date: "2026-09-20T10:00:00Z",
      details_urls: ["https://www.liverpoolfc.com/news/held-update"],
    },
  ],
  limit: OFFICIAL_INJURY_LIMIT,
};

it.each(["tr", "en"] as const)(
  "shows coverage and source clocks without caveats in %s",
  (language) => {
    expect(isOfficialInjuryFacts(data)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <OfficialInjuryCard data={data} playerNames={{ 10: "Player Alpha" }} />
      </LanguageProvider>,
    );
    const card = screen.getByTestId("official-injuries");
    expect(card).not.toHaveAttribute("open");
    expect(card).toHaveTextContent("1/2");
    expect(card).toHaveTextContent("Player Alpha");
    expect(card).toHaveTextContent("Man Utd");
    expect(card).toHaveTextContent(
      language === "tr" ? "Eksik okunmuş bölümler" : "Incomplete sections",
    );
    expect(card).not.toHaveTextContent(
      language === "tr" ? "sağlıklı veya kesin oynayacak" : "healthy or certain to play",
    );
    expect(card).not.toHaveTextContent(
      language === "tr" ? "yayın zamanı değildir" : "not the source news publication time",
    );
    expect(card).not.toHaveTextContent(language === "tr" ? "olmayabilir" : "may not be the record");
    expect([...card.querySelectorAll("time")].map((node) => node.getAttribute("datetime"))).toEqual(
      [data.source_updated_at, data.observed_at, data.facts[0].source_date],
    );
    expect(card.querySelector("a")).toHaveAttribute("href", data.source_url);
    expect(card.querySelectorAll("a")).toHaveLength(2);
  },
);

it("omits unnamed facts and says nothing about an empty selection", () => {
  render(
    <LanguageProvider initialLanguage="en">
      <OfficialInjuryCard data={data} />
    </LanguageProvider>,
  );
  const card = screen.getByTestId("official-injuries");
  expect(card).toHaveTextContent("No source records to display");
  expect(card).not.toHaveTextContent("does not mean a player is healthy");
  expect(card).not.toHaveTextContent("Ankle");
  expect(card).not.toHaveTextContent("#10");
});

it("renders editorial text safely and does not impute noninstant source dates", () => {
  const changed = {
    ...data,
    source_updated_at: null,
    facts: [
      {
        ...data.facts[0],
        injury: '<img src=x onerror="alert(1)">',
        source_date: "September 2026",
        details_urls: ["javascript:alert(1)", "https://user:secret@example.com/news"],
      },
    ],
  };
  render(
    <LanguageProvider initialLanguage="en">
      <OfficialInjuryCard data={changed} playerNames={{ 10: "Player Alpha" }} />
    </LanguageProvider>,
  );
  const card = screen.getByTestId("official-injuries");
  expect(card).toHaveTextContent('<img src=x onerror="alert(1)">');
  expect(card.querySelector("img")).toBeNull();
  expect(card.querySelectorAll("a")).toHaveLength(1);
  expect(card).toHaveTextContent("September 2026");
  expect(card.querySelectorAll("time")).toHaveLength(1);
  expect(card).toHaveTextContent("Date not reported");
});

it("does not render absent optional evidence", () => {
  const { container } = render(
    <LanguageProvider initialLanguage="en">
      <OfficialInjuryCard />
    </LanguageProvider>,
  );
  expect(container).toBeEmptyDOMElement();
});

it.each([
  { source_url: "javascript:alert(1)" },
  { raw_quote: "private" },
  { received_clubs: ["Liverpool", "Not on roster"] },
  { missing_clubs: [] },
  { incomplete_clubs: ["Man Utd"] },
  { mapped_rows: 4 },
  { listed_rows: true },
  { source_updated_at: "not a date" },
  { facts: [{ ...data.facts[0], source_span: "private" }] },
  { facts: [{ ...data.facts[0], details_urls: ["https://user:secret@example.com/news"] }] },
])("rejects malformed or leaking public facts: %s", (patch) => {
  expect(isOfficialInjuryFacts({ ...data, ...patch })).toBe(false);
});

it("accepts an editorial date without inventing a precise timestamp", () => {
  expect(
    isOfficialInjuryFacts({
      ...data,
      facts: [{ ...data.facts[0], source_date: "September 2026" }],
    }),
  ).toBe(true);
});
