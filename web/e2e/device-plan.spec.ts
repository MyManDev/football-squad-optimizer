import { expect, test } from "@playwright/test";

import { chipPath } from "../src/features/league/advice/chipChoice";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import {
  mockEntryAdviceChipEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

// The whole device path in a real browser: the published inputs, the worker, the wasm
// solver served from the site's own assets, and the plan drawn on the page. The
// instance is the parity fixture's, so the answer on screen is the server's.
const ENTRY = 35249001;
const member = fixture.members[2]!;

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
        payload: fixture.document,
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

  await page.goto(`/league/members/${ENTRY}?mode=saf-puan&window=1`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  pressed = true;
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
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

test("a chip the member holds is solved on the device with its gain against the plain plan", async ({
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
  // The publish lists the chip, so the page offers it; its document is the publisher's.
  const index = mockEntryAdviceIndex(ENTRY);
  await page.route(/\/data\/league\/advice\/35249001\/index\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
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
        payload: fixture.document,
      }),
    }),
  );

  await page.goto(`/league/members/${ENTRY}?mode=saf-puan&window=1&chip=3xc`);
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
});

test("a rival strategy is solved on the device against the rival's published eleven", async ({
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

  await page.goto(`/league/members/${ENTRY}?mode=fark-yarat&window=1&rival=${RIVAL}`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
  // The band's account, as the service publishes it: the overlap, the cap and the price.
  const reference = world.cases.find(
    (c) => c.entry_id === 101 && c.rival_entry_id === 202 && c.strategy === "fark-yarat",
  )!.reference;
  await expect(page.locator("main")).toContainText(
    `rakibin on birinden ${reference.overlap_count} tanesi senin on beşinde`,
  );
  await expect(page.locator("main")).toContainText(
    `istenen ortak oyuncu sınırı ${reference.overlap_target}`,
  );
});
