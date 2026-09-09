import { expect, test } from "@playwright/test";
import {
  mockEntryAdviceIndex,
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
} from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

const ENTRY = 35249001;
const index = mockEntryAdviceIndex(ENTRY);

for (const language of ["tr", "en"] as const) {
  test(`no index cannot cause a guessed advice request or infinite loading in ${language}`, async ({
    page,
  }) => {
    const copy = MESSAGES[language].leagueMembers;
    const reads: string[] = [];
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await installLeagueMocks(page);
    await page.route(`**/data/league/advice/${ENTRY}/index.json`, (route) =>
      route.fulfill({ status: 404, body: "{}" }),
    );
    page.on("request", (request) => {
      if (
        /data\/league\/advice\/.*\.json/.test(request.url()) &&
        !request.url().endsWith("index.json")
      )
        reads.push(request.url());
    });
    await page.goto(`/league/members/${ENTRY}`);
    await expect(page.getByText(copy.publicationStates["index-missing"].title)).toBeVisible();
    await expect(page.getByRole("button", { name: copy.computeButton })).toBeDisabled();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(reads).toEqual([]);
  });

  test(`only the selected indexed rival is fetched and named in ${language}`, async ({ page }) => {
    const copy = MESSAGES[language].leagueMembers;
    const row = index.payload.computed[0]!;
    const reads: string[] = [];
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await installLeagueMocks(page);
    page.on("request", (request) => {
      if (/data\/league\/(advice|entries)\//.test(request.url()))
        reads.push(new URL(request.url()).pathname);
    });
    await page.goto(`/league/members/${ENTRY}?mode=${row.strategy}&rival=${row.rival_entry_id}`);
    const region = page.getByRole("region", { name: copy.rivalPlayersTitle });
    await expect(region.getByText(copy.rivalPlayerGroups.shared)).toBeVisible();
    await expect(region.getByText(copy.rivalPlayersBasis)).toBeVisible();
    const plan = mockEntryAdviceEnvelope(ENTRY, "ortak-koru", 1, row.rival_entry_id).payload;
    const rival = mockEntrySquadEnvelopes[row.rival_entry_id]!.payload;
    const held = new Set(rival.starting_xi.map((player) => player.player_id));
    const names = [...plan.starting_xi!, ...plan.bench!]
      .filter((player) => held.has(player.player_id))
      .map((player) => player.name)
      .join(", ");
    await expect(
      region.getByText(names || copy.rivalPlayersNone, { exact: true }).first(),
    ).toBeVisible();
    expect(reads).toContain(`/data/league/${row.path}`);
    expect(reads.filter((url) => url.includes("/entries/")).sort()).toEqual(
      [
        `/data/league/entries/${ENTRY}.json`,
        `/data/league/entries/${row.rival_entry_id}.json`,
      ].sort(),
    );
  });
}

test("an unsupported saved template and direct URL cannot fetch an unlisted pair", async ({
  page,
}) => {
  const reads: string[] = [];
  await page.addInitScript(() =>
    localStorage.setItem(
      "squadopt.templates",
      JSON.stringify([
        {
          id: "own:bad",
          name: "Unavailable saved plan",
          strategy: "fark-yarat",
          window: 5,
          rival: 99999999,
        },
      ]),
    ),
  );
  await installLeagueMocks(page);
  page.on("request", (request) => {
    if (
      /data\/league\/advice\/.*\.json/.test(request.url()) &&
      !request.url().endsWith("index.json")
    )
      reads.push(request.url());
  });
  await page.goto(`/league/members/${ENTRY}?mode=fark-yarat&window=5&rival=99999999`);
  await expect(
    page.getByText(MESSAGES.tr.leagueMembers.publicationStates["not-listed"].title),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^Unavailable saved plan Fark yarat/ }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: "Hesapla" })).toBeDisabled();
  expect(reads).toEqual([]);
});

for (const [state, language] of (["tr", "en"] as const).flatMap((language) =>
  (["index-error", "empty", "declared", "wrong-path"] as const).map(
    (state) => [state, language] as const,
  ),
)) {
  test(`publication ${state} keeps the squad without a guessed advice read in ${language}`, async ({
    page,
  }) => {
    const reads: string[] = [];
    const pair = index.payload.computed[0]!;
    const copy = MESSAGES[language].leagueMembers;
    await page.addInitScript(
      (language) => localStorage.setItem("squadopt.language", language),
      language,
    );
    await installLeagueMocks(page);
    const payload =
      state === "empty"
        ? { ...index.payload, strategies: [], windows: {}, computed: [] }
        : state === "declared"
          ? {
              ...index.payload,
              computed: [],
              unavailable: [
                {
                  strategy: pair.strategy,
                  rival_entry_id: pair.rival_entry_id,
                  reason: "Raw producer diagnostic: probability 97% chance",
                },
              ],
            }
          : state === "wrong-path"
            ? {
                ...index.payload,
                computed: [{ ...pair, path: "advice/999/fark-yarat/1/vs-999.json" }],
              }
            : index.payload;
    await page.route(`**/data/league/advice/${ENTRY}/index.json`, (route) =>
      route.fulfill({
        status: state === "index-error" ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify({ ...index, payload }),
      }),
    );
    page.on("request", (request) => {
      if (
        /data\/league\/advice\/.*\.json/.test(request.url()) &&
        !request.url().endsWith("index.json")
      )
        reads.push(request.url());
    });
    await page.goto(`/league/members/${ENTRY}?mode=${pair.strategy}&rival=${pair.rival_entry_id}`);
    const issue =
      state === "index-error"
        ? "index-error"
        : state === "declared"
          ? "declared-unavailable"
          : "not-listed";
    await expect(page.getByText(copy.publicationStates[issue].title)).toBeVisible();
    await expect(page.getByRole("button", { name: copy.computeButton })).toBeDisabled();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (state === "declared") {
      await expect(
        page.getByText(copy.publicationStates["declared-unavailable"].body),
      ).toBeVisible();
      await expect(page.getByText("Raw producer diagnostic: probability 97% chance")).toHaveCount(
        0,
      );
    }
    expect(reads).toEqual([]);
  });
}
