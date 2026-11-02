import { createHash } from "node:crypto";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { chipPath } from "../src/features/league/advice/chipChoice";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import {
  mockEntryAdviceChipEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

// The whole device path in a real browser: the published inputs, the worker, the wasm
// solver served from the site's own assets, and the plan drawn on the page. The
// instance is the parity fixture's, so the answer on screen is the server's.
const ENTRY = 35249001;
const member = fixture.members[2]!;

/**
 * One JSON line on stdout after each test, every one of which finishes a device run (#981
 * step 4): the run's `device:*` measures from the page, an empty list where it kept none,
 * and the wasm's fetch from the worker's own timeline, or null where no worker can be read.
 * It asserts nothing.
 */
async function printDeviceTimings(page: Page, testInfo: TestInfo): Promise<void> {
  const measures = await page
    .evaluate(() =>
      performance
        .getEntriesByType("measure")
        .filter((entry) => entry.name.startsWith("device:"))
        .map(({ name, startTime, duration }) => ({ name, startTime, duration })),
    )
    .catch(() => []);
  let wasm: Record<string, number> | null = null;
  for (const worker of page.workers()) {
    wasm ??= await worker
      .evaluate(() => {
        const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
        const entry = resources.find((resource) => resource.name.endsWith(".wasm"));
        if (!entry) return null;
        const { transferSize, encodedBodySize, decodedBodySize, duration } = entry;
        return { transferSize, encodedBodySize, decodedBodySize, duration };
      })
      .catch(() => null);
  }
  const { project, title, retry } = testInfo;
  console.log(JSON.stringify({ project: project.name, title, retry, measures, wasm }));
}

test.afterEach(async ({ page }, testInfo) => {
  await printDeviceTimings(page, testInfo);
});

test("a member's plan is solved on the device and drawn as a computation result", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  const squad = mockEntrySquadEnvelopes[ENTRY]!;
  const withInputs = {
    ...squad,
    payload: {
      ...squad.payload,
      source_snapshot_id: fixture.document.source_snapshot_id,
      device_plan: member.entry,
    },
  };
  await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(withInputs),
    }),
  );
  await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        // The synthetic instances name league 1; the producer writes the league's own id.
        payload: { ...fixture.document, league_id: squad.payload.league_id },
      }),
    }),
  );
  const wasm: string[] = [];
  // Every request made from the press onward; the page's own opening read of the
  // service's capabilities (mocked and refused by the league mocks) is before it.
  const requested: string[] = [];
  let pressed = false;
  page.on("request", (request) => {
    if (pressed) requested.push(request.url());
  });
  page.on("response", (response) => {
    if (response.url().endsWith(".wasm")) wasm.push(`${response.status()} ${response.url()}`);
  });

  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  pressed = true;
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
  // The progress card stood over the page while the run counted, and is gone now it is done.
  await expect(page.locator("[data-device-progress]")).toHaveCount(0, { timeout: 30_000 });
  // The transfers the server's reference names, by the names the document gives them.
  const names = new Map(fixture.document.players.map((p) => [p.id, p.name]));
  for (const move of member.reference.moves) {
    await expect(page.getByText(names.get(move.in!)!).first()).toBeVisible();
  }
  expect(wasm.some((line) => line.startsWith("200 ") && line.includes("/assets/"))).toBe(true);
  // Nothing left the site: from the press on, every request went to the site's own origin.
  expect(requested.length).toBeGreaterThan(0);
  const foreign = requested.filter((url) => !url.startsWith("http://127.0.0.1:4173/"));
  expect(foreign).toEqual([]);
});

for (const publishedChip of [true, false]) {
  test(`a held chip is solved on the device with ${publishedChip ? "a published answer" : "no advice index"}`, async ({
    page,
  }) => {
    await installLeagueMocks(page);
    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    const withInputs = {
      ...squad,
      payload: {
        ...squad.payload,
        source_snapshot_id: fixture.document.source_snapshot_id,
        device_plan: member.entry,
      },
    };
    await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(withInputs),
      }),
    );
    // With no advice index, the entry's own chip states must still offer the chip.
    const index = mockEntryAdviceIndex(ENTRY);
    await page.route(/\/data\/league\/advice\/35249001\/index\.json(?:\?.*)?$/, (route) =>
      !publishedChip
        ? route.fulfill({ status: 404, body: "" })
        : route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              ...index,
              payload: {
                ...index.payload,
                chips: {
                  available: true,
                  paths: { "3xc": chipPath(ENTRY, "3xc") },
                  unavailable: [],
                  held: ["3xc"],
                },
              },
            }),
          }),
    );
    await page.route(
      /\/data\/league\/advice\/35249001\/saf-puan\/1\/chip-3xc\.json(?:\?.*)?$/,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockEntryAdviceChipEnvelope(ENTRY, "3xc")),
        }),
    );
    await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          contract_version: "provisional_league_ui_v1",
          generated_at_utc: "2026-10-03T00:00:00Z",
          source_kind: "live",
          // The synthetic instances name league 1; the producer writes the league's own id.
          payload: { ...fixture.document, league_id: squad.payload.league_id },
        }),
      }),
    );

    const chipReads: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("chip-3xc.json")) chipReads.push(request.url());
    });
    await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1&chip=3xc`);
    await expect(page.locator('input[name="chip"][value="3xc"]')).toBeChecked();
    if (publishedChip)
      await expect(page.locator("main")).toContainText("Triple Captain bu hafta oynanıyor");
    const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
    await expect(button).toBeVisible();
    await button.click();
    await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Hesap sonucu")).toBeVisible();
    // The captain tripled: the reference's captain scores once more than the plain plan,
    // and the chip section states the gain the device measured against that plan.
    const names = new Map(fixture.document.players.map((p) => [p.id, p.name]));
    await expect(page.getByText(names.get(member.reference.captain)!).first()).toBeVisible();
    await expect(page.locator("main")).toContainText(/Çipsiz kendi planına göre bu hafta ~\+/);
    if (!publishedChip) expect(chipReads).toEqual([]);
  });
}

for (const weight of [0, 50]) {
  test(`a rival strategy is solved on the device against the rival's published eleven at weight ${weight}`, async ({
    page,
  }) => {
    // The fixture's rival world: the member's block and the rival's eleven are the ones the
    // advice service answered for, so the device's answer on screen is the service's.
    const world = fixture.rivals;
    const RIVAL = 35249002;
    const memberBlock = world.members["101"]!;
    const rivalEleven = world.rivals["202"]!;
    await installLeagueMocks(page);
    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    const rivalSquad = mockEntrySquadEnvelopes[RIVAL]!;
    const names = new Map(world.document.players.map((p) => [p.id, p]));
    const asPlayer = (id: number, index: number) => ({
      ...rivalSquad.payload.starting_xi[index]!,
      player_id: id,
      name: names.get(id)!.name,
      short_name: names.get(id)!.short_name,
      position: names.get(id)!.position,
      team: names.get(id)!.team,
      is_captain: id === rivalEleven.captain,
      is_vice_captain: false,
    });
    const documents: Record<number, unknown> = {
      [ENTRY]: {
        ...squad,
        payload: {
          ...squad.payload,
          source_snapshot_id: world.document.source_snapshot_id,
          device_plan: memberBlock,
        },
      },
      [RIVAL]: {
        ...rivalSquad,
        payload: {
          ...rivalSquad.payload,
          source_snapshot_id: world.document.source_snapshot_id,
          starting_xi: rivalEleven.starting_xi.map(asPlayer),
        },
      },
    };
    await page.route(/\/data\/league\/entries\/(\d+)\.json(?:\?.*)?$/, (route) => {
      const id = Number(/entries\/(\d+)\.json/.exec(route.request().url())![1]);
      const document = documents[id];
      return document
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(document),
          })
        : route.fulfill({ status: 404, body: "" });
    });
    await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          contract_version: "provisional_league_ui_v1",
          generated_at_utc: "2026-10-03T00:00:00Z",
          source_kind: "live",
          payload: world.document,
        }),
      }),
    );

    await page.goto(
      `/league/352490/members/${ENTRY}?mode=fark-yarat&window=1&rival=${RIVAL}&top100=${weight}`,
    );
    const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
    await expect(button).toBeVisible();
    await button.click();
    await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Hesap sonucu")).toBeVisible();
    // The band's account, as the service publishes it: the overlap, the cap and the price.
    const cases =
      weight === 0 ? world.cases : world.weighted_cases.filter((c) => c.weight === weight);
    const reference = cases.find(
      (c) => c.entry_id === 101 && c.rival_entry_id === 202 && c.strategy === "fark-yarat",
    )!.reference;
    await expect(page.locator("main")).toContainText(
      `rakibin on birinden ${reference.overlap_count} tanesi senin on beşinde`,
    );
    await expect(page.locator("main")).toContainText(
      `istenen ortak oyuncu sınırı ${reference.overlap_target}`,
    );
    if (weight !== 0) {
      await expect(page.locator("main")).toContainText(`Ayar: ${weight} (senin seçimin).`);
      await expect(page.locator("main")).toContainText(
        `~${reference.expected_points_cost!.toFixed(1).replace(".", ",")} beklenen puan`,
      );
    }
  });
}

test("a Top 100 weight is solved on the device and priced on the base points", async ({ page }) => {
  // The fixture's rival world carries the weighted points; the case at 50 is the one
  // whose decision the weight moves, so the price sentence states a figure.
  const world = fixture.rivals;
  const memberBlock = world.members["102"]!;
  await installLeagueMocks(page);
  const squad = mockEntrySquadEnvelopes[ENTRY]!;
  await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...squad,
        payload: {
          ...squad.payload,
          source_snapshot_id: world.document.source_snapshot_id,
          device_plan: memberBlock,
        },
      }),
    }),
  );
  await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        payload: world.document,
      }),
    }),
  );

  await page.goto(`/league/members/${ENTRY}?mode=saf-puan&window=1&top100=50`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
  const reference = world.top100_cases.find(
    (c) => c.entry_id === 102 && c.weight === 50,
  )!.reference;
  expect(reference.changed).toBe(true);
  await expect(page.locator("main")).toContainText("Ayar: 50 (senin seçimin).");
  // The price on base points, in the sentence the setting documents print it in.
  await expect(page.locator("main")).toContainText(
    `~${reference.expected_points_cost.toFixed(1).replace(".", ",")} beklenen puan`,
  );
});

// The capture's own table (#981 step 2): the directory line names it under `data/device/`
// with the sha256 of its bytes, and the page reads it at that digest before the tree's copy.
const CAPTURE = fixture.document.source_snapshot_id;
const TABLE_PATH = `device/${CAPTURE}/device-plan.json`;

/** The table as the run publishes it: the copy without its league, four fields more. */
function tableBytes(): string {
  const { league_id: _league, ...shared } = fixture.document;
  const payload = {
    ...shared,
    contract_version: "league_device_plan_v2",
    rules: { ...shared.rules, chips: [], transfers_cap: null },
    players: shared.players.map((player, index) => ({
      ...player,
      element_id: index + 1,
      start_tenths: player.buy_tenths,
    })),
  };
  const envelope = {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-03T00:00:00Z",
    source_kind: "live",
    payload,
  };
  return `${JSON.stringify(envelope, null, 2)}\n`;
}

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/**
 * The member's page under a directory whose line names the capture's table with `digest`,
 * the table served as `bytes` and the tree's copy beside it. Returns every read of either,
 * as path and query, in the order the page asked.
 */
async function withCaptureTable(page: Page, digest: string, bytes: string): Promise<string[]> {
  await installLeagueMocks(page);
  const { league_id, league_name, season, gameweek } = mockLeagueMembersEnvelope.payload;
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "league_directory_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: {
          leagues: [
            {
              league_id,
              league_name,
              season,
              gameweek,
              path: "league",
              device_plan: TABLE_PATH,
              device_plan_sha256: digest,
            },
          ],
        },
      }),
    }),
  );
  const squad = mockEntrySquadEnvelopes[ENTRY]!;
  await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...squad,
        payload: { ...squad.payload, source_snapshot_id: CAPTURE, device_plan: member.entry },
      }),
    }),
  );
  const reads: string[] = [];
  const local = (url: string) => {
    const { pathname, search } = new URL(url);
    return `${pathname}${search}`;
  };
  await page.route(/\/data\/device\//, (route) => {
    reads.push(local(route.request().url()));
    return route.fulfill({ status: 200, contentType: "application/json", body: bytes });
  });
  await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) => {
    reads.push(local(route.request().url()));
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        payload: { ...fixture.document, league_id: squad.payload.league_id },
      }),
    });
  });
  return reads;
}

/** Press compute, wait for the plan, and return every request made from the press on. */
async function solveOnDevice(page: Page): Promise<string[]> {
  const requested: string[] = [];
  let pressed = false;
  page.on("request", (request) => {
    if (pressed) requested.push(request.url());
  });
  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  pressed = true;
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
  const names = new Map(fixture.document.players.map((p) => [p.id, p.name]));
  for (const move of member.reference.moves) {
    await expect(page.getByText(names.get(move.in!)!).first()).toBeVisible();
  }
  return requested;
}

test("the capture's table its directory line names is read at its digest, and the copy is not", async ({
  page,
}) => {
  const bytes = tableBytes();
  const digest = sha256(bytes);
  const reads = await withCaptureTable(page, digest, bytes);
  const requested = await solveOnDevice(page);
  // One read of the table, at its digest as the version; the tree's copy is never asked for.
  expect(reads).toEqual([`/data/${TABLE_PATH}?v=${digest}`]);
  // Nothing left the site: from the press on, every request went to the site's own origin.
  const origin = new URL(page.url()).origin;
  expect(requested.length).toBeGreaterThan(0);
  expect(requested.filter((url) => new URL(url).origin !== origin)).toEqual([]);
});

test("a table whose bytes are not the ones its line names falls back to the tree's copy", async ({
  page,
}) => {
  const bytes = tableBytes();
  // The line names the digest of other bytes: the table was replaced since it was written.
  const digest = sha256(`${bytes} `);
  const reads = await withCaptureTable(page, digest, bytes);
  const requested = await solveOnDevice(page);
  expect(reads).toEqual([`/data/${TABLE_PATH}?v=${digest}`, "/data/league/device-plan.json"]);
  const origin = new URL(page.url()).origin;
  expect(requested.filter((url) => new URL(url).origin !== origin)).toEqual([]);
});
