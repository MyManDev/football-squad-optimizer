import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
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

it.each(["tr", "en"] as const)("shows the flagged player and the news date in %s", (language) => {
  render(
    <LanguageProvider initialLanguage={language}>
      <OfficialInformationCard view={view} />
    </LanguageProvider>,
  );
  const card = screen.getByTestId("official-information");
  expect(card).toHaveTextContent("75/100");
  expect(card).toHaveTextContent("Bukayo Saka");
  expect(card).toHaveTextContent(language === "tr" ? "Arsenal · Şüpheli" : "Arsenal · Doubtful");
  expect(card).toHaveTextContent(language === "tr" ? "Haberin tarihi:" : "News Date:");
  expect(card.querySelectorAll("time")).toHaveLength(1);
  expect(card.querySelector("time")).toHaveAttribute("datetime", "2026-10-01T16:00:00Z");
  expect(card.querySelector("a")).toBeNull();
  expect(card).not.toHaveTextContent("20/20");
  expect(card).not.toHaveTextContent(
    language === "tr" ? "Bu değerler FPL kaydından gelir." : "These values come from FPL.",
  );
  expect(card).not.toHaveTextContent(
    language === "tr" ? "ilk 11’de başlama garantisi" : "do not guarantee a start",
  );
  expect(card).not.toHaveTextContent(
    language === "tr" ? "Sunucunun çalışıyor olması" : "A healthy server",
  );
  expect(isAdvicePayload(view)).toBe(true);
});

it("leaves out what the source did not state, and the note about a cleared story", () => {
  const silent = {
    ...view,
    official_information: {
      ...information,
      players: [
        {
          ...information.players[0]!,
          status: "x",
          source_chance_percent: null,
          source_added_at: null,
          news_state: "cleared" as const,
        },
      ],
    },
  };
  render(
    <LanguageProvider initialLanguage="tr">
      <OfficialInformationCard view={silent} />
    </LanguageProvider>,
  );
  const row = screen.getByTestId("official-information").querySelector("li")!;
  expect(row).toHaveTextContent(/^Bukayo Saka · Arsenal$/);
  expect(row.querySelector("time")).toBeNull();
});

it("says there is nothing to flag when no player in the plan is flagged", () => {
  const clear = { ...view, official_information: { ...information, players: [] } };
  render(
    <LanguageProvider initialLanguage="tr">
      <OfficialInformationCard view={clear} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("official-information")).toHaveTextContent(
    "Bu plandaki oyuncular için gösterilecek FPL uyarısı yok.",
  );
});

it("does not list a fit player for a story that has been cleared", () => {
  const cleared = {
    ...view,
    official_information: {
      ...information,
      players: [
        {
          ...information.players[0]!,
          status: "a",
          source_chance_percent: 100,
          news_state: "cleared" as const,
        },
      ],
    },
  };
  render(
    <LanguageProvider initialLanguage="tr">
      <OfficialInformationCard view={cleared} />
    </LanguageProvider>,
  );
  const card = screen.getByTestId("official-information");
  expect(card).not.toHaveTextContent("Bukayo Saka");
  expect(card).toHaveTextContent("Bu plandaki oyuncular için gösterilecek FPL uyarısı yok.");
});

it("keeps a fit player while FPL still has a story on them", () => {
  const present = {
    ...view,
    official_information: {
      ...information,
      players: [{ ...information.players[0]!, status: "a", source_chance_percent: 100 }],
    },
  };
  render(
    <LanguageProvider initialLanguage="tr">
      <OfficialInformationCard view={present} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("official-information")).toHaveTextContent("Bukayo Saka");
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

it.each(["tr", "en"] as const)(
  "announces changed decision information in one sentence, without changing or computing the plan, in %s",
  (language) => {
    const original = JSON.stringify(view);
    render(
      <LanguageProvider initialLanguage={language}>
        <NewInformationNotice view={view} latest={{ ...decision, revision: "d".repeat(64) }} />
      </LanguageProvider>,
    );
    const status = screen.getByRole("status");
    // The button the sentence sends the member to, by the name it has on the page.
    expect(status).toHaveTextContent(MESSAGES[language].leagueMembers.computeButton);
    expect(status).not.toHaveTextContent(language === "tr" ? "karar girdileri" : "Decision inputs");
    expect(status).not.toHaveTextContent("kendiliğinden değiştirilmedi");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(JSON.stringify(view)).toBe(original);
  },
);

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

it("says the same sentence for a plan that carries no information revision", () => {
  const legacy = { ...view };
  delete (legacy as { decision_information?: DecisionInformation }).decision_information;
  render(
    <LanguageProvider initialLanguage="tr">
      <NewInformationNotice view={legacy} latest={decision} />
    </LanguageProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    /^Yeni bilgilerle hesaplamak için Hesapla düğmesini kullanabilirsin\.$/,
  );
});
