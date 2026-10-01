import { expect, test } from "@playwright/test";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { mockInformationReview } from "../src/fixtures/information";
import { installLeagueMocks } from "./leagueMocks";

for (const window of [3, 5] as const) {
  test(`conditional football plan preserves ${window} weeks and Top100 on a phone`, async ({
    page,
  }, info) => {
    test.skip(!process.env.VITE_ADVICE_API_ORIGIN, "API build required");
    await page.setViewportSize({ width: 390, height: 844 });
    await installLeagueMocks(page);
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;
    const answer = mockEntryAdviceEnvelope(35249001, "saf-puan", window);
    answer.payload = {
      ...answer.payload,
      prediction_model: {
        id: "football",
        version: "football_team_share_v1",
        experimental: true,
        fingerprint: "a".repeat(64),
      },
      selection_top100_weight: 20,
      information_review: mockInformationReview(window),
    };
    const reads: string[] = [];
    await page.route("**/api/v1/**", async (route) => {
      const url = route.request().url();
      const headers = {
        "access-control-allow-origin": new URL(page.url()).origin,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type, idempotency-key",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers });
        return;
      }
      if (url.includes("/advice?")) reads.push(url);
      const body = url.endsWith("/capabilities")
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
      `/league/members/35249001?mode=saf-puan&window=${window}&top100=20&model=football`,
    );
    const region = page.getByTestId("information-review");
    await expect(region).toBeVisible();
    await expect(region).toContainText("kesin gelecek transfer tahmini değildir");
    await expect(region).toContainText("Top100 ağırlığı puan kazancı değildir");
    await region.getByText("Oynayamaz bilgisi gelirse", { exact: true }).click();
    await expect(
      region.getByText("Old Player → New Player", { exact: false }).last(),
    ).toBeVisible();
    expect(
      reads.some((url) => {
        const query = new URL(url).searchParams;
        return (
          query.get("window") === String(window) &&
          query.get("top100_weight") === "20" &&
          query.get("model") === "football"
        );
      }),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await region.screenshot({ path: info.outputPath(`information-window${window}.png`) });
  });
}
