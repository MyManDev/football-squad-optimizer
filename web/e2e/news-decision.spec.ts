import { expect, test } from "@playwright/test";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { isAdvicePayload } from "../src/features/league/advice/adviceShape";
import { installLeagueMocks } from "./leagueMocks";

// Deterministic transport fixtures, not a claim of live provider or predictive success.
for (const [window, top100, width] of [
  [3, 0, 320],
  [5, 20, 390],
] as const) {
  test(`news is visible and recalculation stays explicit: ${window} weeks, Top100 ${top100}`, async ({
    page,
  }) => {
    test.skip(!process.env.VITE_ADVICE_API_ORIGIN, "API build required");
    await page.setViewportSize({ width, height: 844 });
    await installLeagueMocks(page);
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;
    const answer = mockEntryAdviceEnvelope(35249001, "saf-puan", window);
    const player = answer.payload.starting_xi![0]!;
    const latest = {
      version: "football_decision_information_v1" as const,
      revision: "b".repeat(64),
      source_snapshot_id: squad.source_snapshot_id,
      observed_at: "2026-10-02T00:00:00Z",
      coach_news_bound: true,
      minute_components_bound: true,
    };
    answer.payload = {
      ...answer.payload,
      source_snapshot_id: squad.source_snapshot_id,
      prediction_model: {
        id: "football",
        version: "football_team_share_v1",
        experimental: true,
        fingerprint: "a".repeat(64),
      },
      selection_top100_weight: top100,
      official_information: {
        version: "fpl_information_v1",
        season: squad.season,
        gameweek: squad.gameweek,
        source_snapshot_id: squad.source_snapshot_id,
        observed_at: latest.observed_at,
        revision: "c".repeat(64),
        source_url: "https://fantasy.premierleague.com/",
        player_count: 667,
        team_count: 20,
        declared_team_count: 20,
        players: [
          {
            player_id: player.player_id,
            name: player.name,
            team_name: player.team,
            status: "d",
            source_chance_percent: 75,
            source_added_at: "2026-10-01T16:00:00Z",
            news_state: "present",
          },
        ],
      },
      decision_information: { ...latest, revision: "d".repeat(64), coach_news_bound: false },
      participation_evidence: {
        version: "football_participation_evidence_v1",
        as_of: latest.observed_at,
        gameweek: squad.gameweek,
        applied_player_count: 0,
        unapplied_statement_count: 0,
        captured_percentage_count: 1,
        manager_statement_count: 0,
        assumptions: ["no_external_calibration"],
        statement_outcomes: [],
      },
    };
    expect(isAdvicePayload(answer.payload)).toBe(true);
    let submitted = 0;
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const headers = {
        "access-control-allow-origin": new URL(page.url()).origin,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type, idempotency-key",
      };
      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers });
        return;
      }
      if (request.method() === "POST") {
        submitted++;
        expect(request.postDataJSON()).toMatchObject({
          strategy: "saf-puan",
          window,
          model: "football",
        });
        if (top100) expect(request.postDataJSON()).toMatchObject({ top100_weight: top100 });
        answer.payload.decision_information = latest;
        answer.payload.participation_evidence = {
          ...answer.payload.participation_evidence!,
          applied_player_count: 1,
          manager_statement_count: 2,
          unapplied_statement_count: 1,
          statement_outcomes: [
            {
              player_id: player.player_id,
              disposition: "stated_full_match_unavailable",
              applied: true,
              reason: "explicit_full_match_restriction",
              source_url: "https://www.liverpoolfc.com/news/team-update",
              source_published_at: "2026-10-01T18:00:00Z",
            },
            {
              player_id: player.player_id,
              disposition: "stated_minutes_managed",
              applied: false,
              reason: "upcoming_league_scope_unverified",
              source_url: null,
              source_published_at: null,
            },
          ],
        };
        expect(isAdvicePayload(answer.payload)).toBe(true);
      }
      const body = request.url().endsWith("/capabilities")
        ? {
            contract_version: "league_capabilities_v1",
            league_id: squad.league_id,
            season: squad.season,
            gameweek: squad.gameweek,
            capture_snapshot_id: squad.source_snapshot_id,
            strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
            models: ["current", "football"],
            top100: { available: true, weights: [0, 20] },
            managers_word: { available: false },
            decision_information: latest,
          }
        : answer;
      await route.fulfill({
        status: 200,
        headers,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
    await page.goto(
      `/league/members/35249001?mode=saf-puan&window=${window}&top100=${top100}&model=football`,
    );
    await expect(page.getByTestId("new-information-notice")).toContainText(
      "kendiliğinden değiştirilmedi",
    );
    const facts = page.getByTestId("official-information");
    await facts.locator(":scope > summary").click();
    await expect(facts).toContainText("20/20");
    await expect(facts).toContainText("75/100");
    await expect(facts.locator("time")).toHaveCount(2);
    expect(submitted).toBe(0);
    const evidence = page.getByTestId("participation-evidence");
    await evidence.locator(":scope > summary").click();
    await expect(evidence).toContainText("Bu tahmine uygulanmış hoca açıklaması yok");
    await page.getByRole("button", { name: "Hesapla", exact: true }).click();
    await expect(page.getByTestId("new-information-notice")).toHaveCount(0);
    await expect(page.getByTestId("statement-outcomes")).toContainText(
      "Tam maç süresi kısıtı uygulandı",
    );
    await expect(page.getByTestId("statement-outcomes")).toContainText(
      "Haberin bu lig maçına ait olduğu doğrulanamadı",
    );
    expect(submitted).toBe(1);
    await expect(
      page.getByRole("region", { name: `${window} haftalık pencere`, exact: true }),
    ).toBeVisible();
    await expect(facts).toContainText("75/100");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}
