import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { atRest } from "./atRest";
import { expect, test as base, type Locator, type Page } from "@playwright/test";

import { shippedClaim } from "./identity";
import { installLeagueMocks, openCalendar } from "./leagueMocks";
import { FIXTURES_COPY } from "../src/features/fixtures/fixturesCopy";
import deviceInstances from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { shippedTrees } from "../src/testSupport/shippedTrees";

const DAY = ["day", "light"] as const;
const NIGHT = ["night", "dark"] as const;

/**
 * The site has two palettes (tokens.css) and every colour axe reads changes between them, so
 * a test here that runs axe runs in both unless it names its own; one that never runs axe
 * calls `base` and stays in the day. The night comes from the system's preference, as it does
 * for a visitor who has chosen neither.
 */
function test(
  title: string,
  check: (fixtures: { page: Page }) => Promise<void>,
  palettes: readonly (typeof DAY | typeof NIGHT)[] = [DAY, NIGHT],
) {
  for (const [palette, colorScheme] of palettes) {
    base(`${title} (${palette})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await check({ page });
    });
  }
}

const ROUTES = [
  "/",
  "/league/352490",
  "/league/352490/members",
  "/league/352490/members/35249001?mode=saf-puan&window=3",
] as const;
const BLOCKING_IMPACTS = new Set(["critical", "serious"]);

async function waitForPage(page: import("@playwright/test").Page) {
  await expect(page.locator("main")).not.toContainText(/Yükleniyor|Loading/);
}

/** The ids of axe's critical and serious findings on the page as it stands. */
async function blockingViolations(page: import("@playwright/test").Page) {
  await atRest(page);
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => BLOCKING_IMPACTS.has(violation.impact ?? ""))
    .map((violation) => violation.id);
}

/** axe's critical and serious findings with the first nodes of each, so a failure says where. */
async function blockingSummary(page: import("@playwright/test").Page) {
  await atRest(page);
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => BLOCKING_IMPACTS.has(violation.impact ?? ""))
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.length,
      targets: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
    }));
}

const club = (team_id: number, name: string, short_name: string) => ({ team_id, name, short_name });
const ARS = club(1, "Arsenal", "ARS");
const AVL = club(2, "Aston Villa", "AVL");
const BRE = club(3, "Brentford", "BRE");
const CHE = club(4, "Chelsea", "CHE");
const EVE = club(5, "Everton", "EVE");
const FUL = club(6, "Fulham", "FUL");

function fixture(
  fixture_id: number,
  home: ReturnType<typeof club>,
  away: ReturnType<typeof club>,
  kickoff_utc: string | null,
  score: readonly [number, number] | null = null,
) {
  return {
    fixture_id,
    kickoff_utc,
    home,
    away,
    finished: score !== null,
    home_score: score?.[0] ?? null,
    away_score: score?.[1] ?? null,
  };
}

/**
 * The open calendar every league spec uses, filled so /fixtures draws each thing it can: the
 * open week with a match played, kickoff times and a fixture with no date yet, the week after
 * it, and the note about a postponed fixture. The mocked league's week
 * stays the open one, with its deadline far in the future, so nothing moves with the clock.
 */
function fixturesCalendar() {
  const calendar = openCalendar();
  const open = calendar.payload.gameweeks[0]!;
  return {
    ...calendar,
    payload: {
      ...calendar.payload,
      unscheduled_count: 1,
      gameweeks: [
        {
          ...open,
          fixtures: [
            fixture(1, ARS, AVL, "2026-08-22T11:30:00Z", [2, 1]),
            fixture(4, AVL, BRE, "2999-01-02T12:30:00Z"),
            fixture(5, CHE, EVE, "2999-01-02T15:00:00Z"),
            fixture(6, FUL, ARS, null),
          ],
        },
        {
          gameweek: open.gameweek + 1,
          deadline_utc: "2999-01-08T18:30:00Z",
          fixtures: [
            fixture(7, ARS, CHE, "2999-01-09T15:00:00Z"),
            fixture(8, BRE, FUL, "2999-01-10T16:30:00Z"),
          ],
        },
      ],
    },
  };
}

// Every route is checked in both languages, and the night in Turkish alone: it changes the
// colours and not the words. The mocked visitor has said who they are, so the league and system
// pages are drawn; the picker in front of them is checked on its own.
for (const language of ["tr", "en"] as const) {
  const palettes = language === "tr" ? [DAY, NIGHT] : [DAY];

  test(
    `axe has no critical or serious violations in ${language}`,
    async ({ page }) => {
      base.setTimeout(60_000);
      await installLeagueMocks(page);
      await page.addInitScript((selectedLanguage) => {
        localStorage.setItem("squadopt.language", selectedLanguage);
      }, language);

      for (const route of ROUTES) {
        await page.goto(route);
        await waitForPage(page);
        if (route.includes("mode=saf-puan&window=3")) {
          await expect(page.locator('[aria-labelledby="entry-advice-title"]')).toBeVisible();
          const plan = page.getByRole("region", {
            name: MESSAGES[language].leagueMembers.windowTitle(3),
          });
          await expect(plan).toBeVisible();
          await expect(plan.locator("tbody tr")).toHaveCount(3);
        }
        expect(await blockingSummary(page), `${language} ${route}`).toEqual([]);
      }
    },
    palettes,
  );

  test(
    `axe has no critical or serious violations on the member picker in ${language}`,
    async ({ page }) => {
      await installLeagueMocks(page, { claim: null });
      await page.addInitScript((selectedLanguage) => {
        localStorage.setItem("squadopt.language", selectedLanguage);
      }, language);
      await page.goto("/league/352490/members");
      await expect(
        page.getByRole("group", { name: MESSAGES[language].memberPicker.legend }),
      ).toBeVisible();
      expect(await blockingSummary(page), `${language} picker`).toEqual([]);
      await page.locator("[data-member-picker] li button").first().focus();
      expect(await blockingSummary(page), `${language} picker with a name in focus`).toEqual([]);
      await page.locator("[data-member-picker] li button").nth(1).hover();
      expect(
        await blockingSummary(page),
        `${language} picker with a name under the pointer`,
      ).toEqual([]);
    },
    palettes,
  );

  test(
    `axe has no critical or serious violations on /fixtures in ${language}`,
    async ({ page }) => {
      await installLeagueMocks(page);
      // Routes registered later win, so this calendar replaces the empty open one.
      await page.route("**/data/fixtures.json", (route) =>
        route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(fixturesCalendar()),
        }),
      );
      await page.addInitScript((selectedLanguage) => {
        localStorage.setItem("squadopt.language", selectedLanguage);
      }, language);
      await page.goto("/fixtures");

      const copy = FIXTURES_COPY[language];
      const main = page.getByRole("main");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.pageTitle);
      // The matrix, with the postponed-fixture note under it.
      await expect(main.getByRole("table", { name: copy.generalView })).toBeVisible();
      await expect(main.getByRole("rowheader")).toHaveCount(6);
      await expect(main.getByText(copy.unscheduledCount(1), { exact: false })).toBeVisible();
      const fillOf = (cell: string) =>
        main
          .locator(`td ${cell}`)
          .first()
          .evaluate((match) => getComputedStyle(match).backgroundColor);
      const none = "rgba(0, 0, 0, 0)";
      expect(await fillOf('[data-venue="away"]:not([data-behind])')).toBe(none);
      expect(await fillOf('[data-venue="home"]:not([data-behind])')).not.toBe(none);
      expect(await fillOf('[data-venue="home"][data-behind]')).toBe(none);
      expect(await blockingSummary(page), `${language} /fixtures`).toEqual([]);

      // A club's grid with a match at home and one away, one with no date, and a blank week.
      await main.getByRole("radio", { name: copy.teamView, exact: true }).click();
      await main.getByRole("radio", { name: /^BRE / }).click();
      await expect(main.locator("[data-venue='home']")).toHaveCount(1);
      await expect(main.locator("[data-venue='away']")).toHaveCount(1);
      await expect(main.locator("time")).toHaveCount(2);
      expect(await blockingSummary(page), `${language} /fixtures, a club`).toEqual([]);
      await main.getByRole("radio", { name: /^FUL / }).click();
      await expect(main.getByText(copy.unscheduled, { exact: true })).toBeVisible();
      expect(await blockingSummary(page), `${language} /fixtures, no date`).toEqual([]);
      await main.getByRole("radio", { name: /^EVE / }).click();
      await expect(main.getByText(MESSAGES[language].leagueMembers.fixtureNone)).toBeVisible();
      expect(await blockingSummary(page), `${language} /fixtures, a blank week`).toEqual([]);
    },
    palettes,
  );
}

const ENTRY = 35249001;
const COPY = MESSAGES.tr.leagueMembers;

/**
 * The example member's week with the parity fixture's inputs, so the device really solves it.
 * The inputs are held back until `released` settles, and the run's cover stands until then.
 */
async function serveDeviceInputs(page: Page, released: Promise<void> = Promise.resolve()) {
  const squad = mockEntrySquadEnvelopes[ENTRY]!;
  await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...squad,
        payload: {
          ...squad.payload,
          source_snapshot_id: deviceInstances.document.source_snapshot_id,
          device_plan: deviceInstances.members[2]!.entry,
        },
      }),
    }),
  );
  await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, async (route) => {
    await released;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        payload: { ...deviceInstances.document, league_id: squad.payload.league_id },
      }),
    });
  });
}

/** A control on the mark is ringed in the mark's ink: at night the focus colour is the mark's. */
async function expectRingInItsInk(control: Locator) {
  await control.focus();
  // Reached from the keyboard, whatever the page was last touched with.
  await control.page().keyboard.press("Shift+Tab");
  await control.page().keyboard.press("Tab");
  await expect(control).toBeFocused();
  await expect(control).toHaveCSS("outline-style", "solid");
  const ink = await control.evaluate((element) => getComputedStyle(element).color);
  await expect(control).toHaveCSS("outline-color", ink);
}

// The shipped league, whose scoreboard draws the race, so the viewer has a row of their own in
// the table and in the points-gap list. At 320 px the chart and its table scroll sideways.
for (const width of [320, 1280]) {
  test(`axe has no critical or serious violations on the viewer's own rows at ${width} px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await installLeagueMocks(page, { claim: shippedClaim() });
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ path: join(shippedTrees()[0]!.root, "members.json") }),
    );
    await page.goto("/league/352490/members");
    const row = page.locator("tbody tr[aria-current]");
    await expect(row).toBeVisible();
    await expect(page.locator("ol li[aria-current]")).toBeVisible();
    expect(await blockingSummary(page)).toEqual([]);
    await expectRingInItsInk(row.getByRole("link"));
  });
}

test("axe has no critical or serious violations on a changed row of the what-if squad", async ({
  page,
}) => {
  await installLeagueMocks(page);
  await serveDeviceInputs(page);
  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  await page.getByRole("button", { name: COPY.deviceButton }).click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("[data-device-progress]")).toHaveCount(0, { timeout: 30_000 });

  // The what-if is a page of its own; the sidebar's link keeps the plan the device solved.
  await page
    .locator("#sidebar nav")
    .getByRole("link", { name: MESSAGES.tr.shell.whatIf, exact: true })
    .click();
  const tool = page.getByRole("region", { name: COPY.whatIfTitle });
  await tool.getByRole("button", { name: COPY.whatIfStart }).click();
  const points = tool.locator("dt", { hasText: COPY.whatIfPoints }).locator("xpath=../dd");
  await expect(points).not.toHaveText(/^-/, { timeout: 30_000 });
  // One out and another in: the newcomer's row carries the mark.
  await tool.getByRole("button", { name: COPY.whatIfRemove }).first().click();
  await tool.getByLabel(COPY.whatIfAdd).selectOption({ index: 1 });
  await tool.getByRole("button", { name: COPY.whatIfAddButton, exact: true }).click();
  const row = tool.locator("li[data-changed]");
  await expect(row).toHaveCount(1);
  expect(await blockingSummary(page)).toEqual([]);
  await expectRingInItsInk(row.getByRole("button"));
});

for (const width of [390, 1440]) {
  test(`the device solve's cover keeps focus and gives it back at ${width} px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await installLeagueMocks(page);
    let release = () => {};
    await serveDeviceInputs(
      page,
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
    const button = page.getByRole("button", { name: COPY.deviceButton });
    await button.focus();
    await page.keyboard.press("Enter");

    // Over the page, all of it inert, a phone's fixture sheet with it; Tab stays in the card.
    await expect(page.getByRole("region", { name: COPY.deviceSolving })).toBeFocused();
    await expect(page.locator("#root")).toHaveAttribute("inert", "");
    await expect(page.locator("body > :not([inert], [data-device-progress])")).toHaveCount(0);
    for (let step = 0; step < 6; step += 1) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => {
        const active = document.activeElement;
        return active === document.body || !!active?.closest("[data-device-progress]");
      });
      expect(inside, `focus after ${step + 1} tabs`).toBe(true);
    }
    expect(await blockingSummary(page)).toEqual([]);

    release();
    await expect(page.locator("[data-device-progress]")).toHaveCount(0, { timeout: 60_000 });
    await expect(page.locator("body > [inert]")).toHaveCount(0);
    await expect(button).toBeFocused();
    // The state line is a live region, and the button that takes focus back says how it ended.
    await expect(page.getByRole("status").filter({ hasText: COPY.computeDone })).toBeVisible();
    await expect(button).toHaveAccessibleDescription(new RegExp(COPY.computeDone));
  });
}

// A page that holds only a state still has a heading, the state's title. axe rates its absence
// below the impacts the checks above fail on, so this asks for that one rule by name.
const STATE_PAGES: { path: string; unpublished?: string }[] = [
  { path: "/moves" },
  { path: "/status" },
  { path: "/admin" },
  { path: "/gw/2026-27/5" },
  { path: "/rivals" },
  { path: "/rivals/2026-27/38" },
  { path: "/league/352490/members/not-a-member" },
  { path: "/league/352490/members/35249001/not-a-tool" },
  { path: "/league/352490/members/not-a-member/history" },
  { path: "/league/352490/members/1" },
  { path: "/league/352490/members/1/history" },
  { path: "/fixtures", unpublished: "**/data/fixtures.json" },
];

for (const { path, unpublished } of STATE_PAGES) {
  base(`${path} has its heading when it holds only a state`, async ({ page }) => {
    await installLeagueMocks(page);
    if (unpublished)
      await page.route(unpublished, (route) =>
        route.fulfill({ status: 404, contentType: "application/json", body: "{}" }),
      );
    await page.goto(path);
    const state = page.getByRole("main").getByRole("status");
    await expect(state.getByRole("heading", { level: 1 })).toBeVisible();
    const results = await new AxeBuilder({ page }).withRules(["page-has-heading-one"]).analyze();
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
}

base("language controls satisfy label-in-name and remain keyboard operable", async ({ page }) => {
  await page.goto("/");
  const turkish = page.getByRole("button", { name: /^TR/ });
  const english = page.getByRole("button", { name: /^EN/ });

  await expect(turkish).toHaveText("TR");
  await expect(english).toHaveText("EN");
  await english.focus();
  await page.keyboard.press("Enter");
  await expect(english).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

base("language buttons are 44 px touch targets below 1180 px wide", async ({ page }) => {
  // Desktop keeps D's compact 30 px control; every narrower width is treated as touch.
  // On a phone the switch lives in the sidebar drawer, so the menu is opened first; the
  // tablet's icon rail stacks TR over EN.
  for (const [width, minHeight, minWidth] of [
    [390, 44, 44],
    [1179, 44, 44],
    [1440, 28, 40],
  ] as const) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    if (width < 600) {
      await page.getByRole("button", { name: "Menüyü aç" }).click();
      // Measure once the drawer has finished sliding in, not part way through it.
      await expect(page.locator("#sidebar")).toHaveCSS("transform", "none");
    }
    for (const name of [/^TR/, /^EN/]) {
      const box = await page.getByRole("button", { name }).boundingBox();
      expect(box, `${String(name)} at ${width}`).not.toBeNull();
      expect(box!.height, `${String(name)} height at ${width}`).toBeGreaterThanOrEqual(minHeight);
      expect(box!.width, `${String(name)} width at ${width}`).toBeGreaterThanOrEqual(minWidth);
    }
  }
});

base("skip link and the sidebar's controls take keyboard focus in order", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "İçeriğe geç" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await expect(skip).toHaveCSS("outline-style", "solid");

  // Then the sidebar, in the order it stands: its collapse button, the navigation and
  // the language switch. Before the visitor says who they are, the navigation is 'Ligini
  // bul' and the open pages.
  const sidebar = page.locator("#sidebar");
  const navigation = page.getByRole("navigation");
  const order = [
    sidebar.getByRole("button", { name: "Kenar çubuğunu kapat" }),
    navigation.getByRole("link", { name: "Ligini bul", exact: true }),
    navigation.getByRole("link", { name: "Fikstür", exact: true }),
    ...(process.env.VITE_ADVICE_API_ORIGIN
      ? [navigation.getByRole("link", { name: "Katkıda bulun", exact: true })]
      : []),
    sidebar.getByRole("button", { name: /^TR/ }),
    sidebar.getByRole("button", { name: /^EN/ }),
  ];
  for (const control of order) {
    await page.keyboard.press("Tab");
    await expect(control).toBeFocused();
    await expect(control).toHaveCSS("outline-style", "solid");
  }
});

base(
  "once the visitor has said who they are, Değiştir comes before the league's links",
  async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page);
    await page.goto("/fixtures");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "İçeriğe geç" })).toBeFocused();
    const sidebar = page.locator("#sidebar");
    const navigation = page.getByRole("navigation");
    const order = [
      sidebar.getByRole("button", { name: "Kenar çubuğunu kapat" }),
      sidebar.getByRole("button", { name: "Değiştir" }),
      navigation.getByRole("link", { name: "VS SQUADOPT", exact: true }),
      navigation.getByRole("link", { name: "Bu hafta", exact: true }),
      navigation.getByRole("link", { name: "Lig", exact: true }),
      ...[
        "Şu anki kadron",
        "Kadroyu kendin dene",
        "Rakiple yan yana",
        "Çipler ve transferler",
        "Kadro kartı",
        "Haftalık geçmiş",
      ].map((name) => navigation.getByRole("link", { name, exact: true })),
      navigation.getByRole("link", { name: "Fikstür", exact: true }),
      ...(process.env.VITE_ADVICE_API_ORIGIN
        ? [navigation.getByRole("link", { name: "Katkıda bulun", exact: true })]
        : []),
      sidebar.getByRole("button", { name: /^TR/ }),
      sidebar.getByRole("button", { name: /^EN/ }),
    ];
    for (const control of order) {
      await page.keyboard.press("Tab");
      await expect(control).toBeFocused();
      await expect(control).toHaveCSS("outline-style", "solid");
    }
  },
);

test("the phone menu is a modal drawer that keeps focus and gives it back", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");
  // The sidebar is off the screen until the menu opens.
  await expect(page.getByRole("navigation")).toBeHidden();

  const menu = page.getByRole("banner").getByRole("button", { name: "Menüyü aç" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  const drawer = page.getByRole("dialog", { name: "Menü" });
  await expect(drawer).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  const close = drawer.getByRole("button", { name: "Menüyü kapat" });
  await expect(close).toBeFocused();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe(
    "hidden",
  );

  // Tab never leaves the drawer for the page behind it.
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const active = document.activeElement;
      return active === document.body || !!active?.closest("#sidebar");
    });
    expect(inside, `focus after ${step + 1} tabs`).toBe(true);
  }

  expect(await blockingViolations(page)).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(menu).toBeFocused();
  await expect(page.getByRole("navigation")).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).not.toBe(
    "hidden",
  );
});

test("the tablet rail names every icon and opens the sidebar over the page", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/");
  const navigation = page.getByRole("navigation");
  const names = ["Ligini bul", "Fikstür"];
  if (process.env.VITE_ADVICE_API_ORIGIN) {
    names.push("Katkıda bulun");
  } else {
    await expect(page.locator('#sidebar a[href="/contribute"]')).toHaveCount(0);
  }
  for (const name of names) {
    const link = navigation.getByRole("link", { name, exact: true });
    await expect(link).toBeVisible();
    const box = (await link.boundingBox())!;
    expect(box.width, name).toBeGreaterThanOrEqual(44);
    expect(box.height, name).toBeGreaterThanOrEqual(44);
  }
  const rail = (await page.locator("#sidebar").boundingBox())!;
  expect(rail.width).toBe(72);

  const expand = page.getByRole("button", { name: "Kenar çubuğunu aç" });
  // The rail's other control is a touch target too.
  for (const control of [expand]) {
    const box = (await control.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  expect(await blockingViolations(page)).toEqual([]);

  await expand.click();
  const drawer = page.getByRole("dialog", { name: "Menü" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Menüyü kapat" })).toBeFocused();
  // The page column does not move under the drawer.
  expect((await page.getByRole("main").boundingBox())!.x).toBeGreaterThanOrEqual(72);
  expect(await blockingViolations(page)).toEqual([]);
  await page.locator("[class*=scrim]").click({ position: { x: 700, y: 400 } });
  await expect(drawer).toHaveCount(0);
});

test("the tablet rail keeps who you are and Değiştir, opening the sidebar on it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await installLeagueMocks(page);
  await page.goto("/fixtures");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const sidebar = page.locator("#sidebar");
  await expect(sidebar).toHaveAttribute("data-mode", "rail");
  const icon = sidebar.getByRole("button", { name: "Değiştir", exact: true });
  await expect(icon).toBeVisible();
  await expect(icon).toHaveAccessibleDescription(/Deniz Aral/);
  const box = (await icon.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(await blockingViolations(page)).toEqual([]);

  await icon.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Menü" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Deniz Aral")).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Değiştir", exact: true })).toBeFocused();
  expect(await blockingViolations(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(sidebar.getByRole("button", { name: "Değiştir", exact: true })).toBeFocused();
});

test("the collapsed desktop rail opens the sidebar on Değiştir", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.setItem("squadopt.sidebar", "collapsed"));
  await installLeagueMocks(page);
  await page.goto("/fixtures");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const sidebar = page.locator("#sidebar");
  await expect(sidebar).toHaveAttribute("data-mode", "rail");
  const icon = sidebar.getByRole("button", { name: "Değiştir", exact: true });
  await expect(icon).toBeVisible();
  await expect(icon).toHaveAccessibleDescription(/Deniz Aral/);
  expect(await blockingViolations(page)).toEqual([]);

  await icon.click();
  await expect(sidebar).toHaveAttribute("data-mode", "open");
  await expect(sidebar).toHaveCSS("width", "264px");
  await expect(sidebar.getByText("Deniz Aral")).toBeVisible();
  await expect(sidebar.getByRole("button", { name: "Değiştir", exact: true })).toBeFocused();
});

test("the desktop sidebar collapses to the rail and stays so after a reload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const sidebar = page.locator("#sidebar");
  expect((await sidebar.boundingBox())!.width).toBe(264);

  await page.getByRole("button", { name: "Kenar çubuğunu kapat" }).click();
  await expect(page.getByRole("button", { name: "Kenar çubuğunu aç" })).toBeFocused();
  await expect(sidebar).toHaveCSS("width", "72px");
  await page.reload();
  await expect(page.getByRole("button", { name: "Kenar çubuğunu aç" })).toBeVisible();
  expect((await sidebar.boundingBox())!.width).toBe(72);
  expect((await page.getByRole("main").boundingBox())!.x).toBeGreaterThanOrEqual(72);
  // The rail keeps every destination by name.
  await expect(
    page.getByRole("navigation").getByRole("link", { name: "Ligini bul", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("squadopt.sidebar"))).toBe("collapsed");
  expect(await blockingViolations(page)).toEqual([]);
});
