import { expect, it } from "vitest";
import {
  isOfficialInjuryFacts,
  OFFICIAL_INJURY_LIMIT,
  type OfficialInjuryFacts,
} from "./officialInjuryFacts";

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

it("accepts the producer's public facts", () => {
  expect(isOfficialInjuryFacts(data)).toBe(true);
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
