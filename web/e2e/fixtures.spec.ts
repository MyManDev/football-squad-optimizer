import { expect, test } from "@playwright/test";

import fixtures from "../public/data/fixtures.json" with { type: "json" };
import { claimMember, shippedClaim } from "./identity";
import { contrastRatio } from "../src/design/contrastRatio";
import { FIXTURES_COPY } from "../src/features/fixtures/fixturesCopy";
import type { FixturesPayload } from "../src/features/fixtures/types";
import {
  clubWeeksAhead,
  fixtureClubs,
  generalWeeks,
  weeksAhead,
} from "../src/features/fixtures/weeks";
import { MESSAGES } from "../src/i18n/messages";
import { CLUB_COLOURS } from "../src/lib/clubs";

// The league's page stands behind the league number and "Sen kimsin?"; this visitor has
// taken both, as the published league's first member.
test.beforeEach(async ({ page }) => {
  await claimMember(page, shippedClaim());
});

const LEAGUE_PAGE = `/league/${shippedClaim().leagueId}`;

// The fixtures page reads whatever weeks the shipped fixture list has ahead, which move with
// every publish. It never reads the list earlier than its capture, so this clock fixes only the
// rest of the site.
const CLOCK = "2026-09-18T10:00:00Z";
const calendar = fixtures.payload as unknown as FixturesPayload;
const run = generalWeeks(weeksAhead(calendar, Date.parse(CLOCK)));

/** The shell clips what overflows it, so the main column is read as well as the document. */
const scrollsSideways = () => {
  const main = document.querySelector("main")!;
  return (
    document.documentElement.scrollWidth > document.documentElement.clientWidth ||
    main.scrollWidth > main.clientWidth
  );
};

/** The gameweek of each cell a club's grid prints, one for a week it does not play. */
const clubCells = (code: string) =>
  clubWeeksAhead(calendar, code, Date.parse(CLOCK)).flatMap(({ gameweek, matches }) =>
    matches.length === 0 ? [gameweek] : matches.map(() => gameweek),
  );

/** Every cell of the matrix or the grid that does not hold what it prints. */
const clippedCells = () =>
  [...document.querySelectorAll("main td, main td > span, main li, main li > span")]
    .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
    .map((cell) => cell.textContent);

/** Every choice whose printed words do not keep clear of the focus ring, 4 px inside its cell. */
const crossedLabels = () =>
  [...document.querySelectorAll("main label")]
    .filter((label) => {
      const printed = [...label.querySelector("span")!.childNodes].filter(
        (node) => !(node instanceof Element && node.classList.contains("visually-hidden")),
      );
      const words = document.createRange();
      words.setStartBefore(printed[0]!);
      words.setEndAfter(printed.at(-1)!);
      const text = words.getBoundingClientRect();
      const box = label.getBoundingClientRect();
      return text.left < box.left + 3.5 || text.right > box.right - 3.5;
    })
    .map((label) => label.textContent);

/** A computed colour as the hex `contrastRatio` reads. */
const hexOf = (rgb: string) =>
  `#${rgb
    .match(/\d+/g)!
    .slice(0, 3)
    .map((part) => Number(part).toString(16).padStart(2, "0"))
    .join("")}`;

/** A colour from CLUB_COLOURS as the browser computes it. */
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

/** Every cell's two-colour mark: the code printed beside it and the colours the browser paints. */
const cellMarks = () =>
  [...document.querySelectorAll("main td [data-venue]")].map((match) => ({
    code: match.querySelector('[class*="_opponent_"]')!.textContent,
    painted:
      getComputedStyle(match.querySelector("[aria-hidden='true']")!).backgroundImage.match(
        /rgba?\([^)]*\)/g,
      ) ?? [],
  }));

for (const width of [1280, 1600])
  test(`a ${width}px screen keeps the page beside the sidebar, with no league-wide rail`, async ({
    page,
  }) => {
    test.skip(run.length === 0, "The shipped season is over: the page lists no week.");
    await page.setViewportSize({ width, height: 900 });
    await page.clock.setFixedTime(new Date(CLOCK));
    await page.goto(LEAGUE_PAGE);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");

    // The two margin rails and the closed list under the page are gone: a member's page
    // carries its own fixtures, and /fixtures carries the whole list.
    await expect(page.getByRole("complementary", { name: "Oynanacak hafta" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Gelecek hafta" })).toHaveCount(0);
    await expect(
      page.locator("details", { hasText: "Fikstür: bu hafta ve gelecek hafta" }),
    ).toHaveCount(0);

    const sidebar = (await page.locator("#sidebar").boundingBox())!;
    const main = (await page.getByRole("main").boundingBox())!;
    expect(sidebar.x).toBe(0);
    expect(sidebar.width).toBe(264);
    expect(main.x).toBeGreaterThanOrEqual(sidebar.x + sidebar.width);
    expect(main.x + main.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(scrollsSideways)).toBe(false);

    await page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }).click();
    await expect(page).toHaveURL("/fixtures");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fikstür");
    // A line for each club and a column for each week ahead.
    const matrix = page.getByRole("main").getByRole("table", { name: "Genel fikstür" });
    await expect(matrix.getByRole("columnheader")).toHaveText([
      "Takım",
      ...run.map((week) => `OH${week.gameweek}`),
    ]);
    await expect(matrix.getByRole("rowheader")).toHaveCount(fixtureClubs(calendar).length);
    expect(await page.evaluate(scrollsSideways)).toBe(false);

    // Every fixture of the window has its two sides in it, and each mark paints the opponent's
    // two colours, the primary first, and never one colour twice.
    const marks = await page.evaluate(cellMarks);
    expect(marks).toHaveLength(run.reduce((sides, week) => sides + 2 * week.fixtures.length, 0));
    for (const { code, painted } of marks) {
      const colours = CLUB_COLOURS[code!];
      expect(colours, code!).toBeDefined();
      expect(painted, code!).toEqual([rgb(colours!.primary), rgb(colours!.secondary)]);
      expect(painted[0], code!).not.toBe(painted[1]);
    }
    // No deadline and no capture time.
    await expect(page.getByRole("main")).not.toContainText(/Son tarih|tarihli kayda göre/);
    await expect(
      page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }),
    ).toHaveAttribute("aria-current", "page");
  });

test("a phone reaches the fixture list from its bar and never scrolls sideways", async ({
  page,
}) => {
  test.skip(run.length === 0, "The shipped season is over: the page lists no week.");
  await page.setViewportSize({ width: 400, height: 800 });
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto(LEAGUE_PAGE);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");
  await expect(page.getByRole("complementary", { name: "Oynanacak hafta" })).toHaveCount(0);
  await expect(
    page.locator("details", { hasText: "Fikstür: bu hafta ve gelecek hafta" }),
  ).toHaveCount(0);
  expect(await page.evaluate(scrollsSideways)).toBe(false);

  const bar = page.getByRole("banner");
  await expect(bar).toBeVisible();
  expect((await bar.boundingBox())!.height).toBe(56);
  // No page offers a fixture sheet here, so the bar's 'Fikstür' is a link to the list.
  await bar.getByRole("link", { name: "Fikstür", exact: true }).click();
  await expect(page).toHaveURL("/fixtures");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fikstür");
  await expect(
    page.getByRole("main").getByRole("table", { name: "Genel fikstür" }).getByRole("rowheader"),
  ).toHaveCount(fixtureClubs(calendar).length);
  expect(await page.evaluate(scrollsSideways)).toBe(false);

  // The bar stays at the top while the page scrolls under it.
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  expect((await bar.boundingBox())!.y).toBe(0);
});

for (const language of ["tr", "en"] as const)
  for (const [width, height] of [
    [1440, 600],
    [820, 1180],
    [390, 844],
    [320, 640],
  ] as const)
    test(`at ${width}px in ${language} a visitor reads the matrix and a club, with nothing cut`, async ({
      page,
    }) => {
      test.skip(run.length === 0, "The shipped season is over: the page lists no week.");
      await page.setViewportSize({ width, height });
      await page.clock.setFixedTime(new Date(CLOCK));
      await page.addInitScript(
        (chosen) => localStorage.setItem("squadopt.language", chosen),
        language,
      );
      await page.goto("/fixtures");
      const copy = FIXTURES_COPY[language];
      const common = MESSAGES[language].common;
      const main = page.getByRole("main");
      const settled = () => page.evaluate(() => document.fonts.ready.then(() => undefined));
      const everyTargetFits = async () => {
        for (const option of await main.locator("label:has(input[type=radio])").all()) {
          const box = (await option.boundingBox())!;
          expect(box.height).toBeGreaterThanOrEqual(44);
          expect(box.width).toBeGreaterThanOrEqual(44);
        }
      };
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.pageTitle);

      // The matrix, with no choice of weeks.
      const matrix = main.getByRole("table", { name: copy.generalView });
      await expect(matrix.getByRole("rowheader")).toHaveCount(fixtureClubs(calendar).length);
      await expect(matrix.getByRole("columnheader")).toHaveText([
        copy.clubLegend,
        ...run.map((week) => common.gameweekShort(week.gameweek)),
      ]);
      await expect(main.getByRole("radio")).toHaveCount(2);
      await expect(main).not.toContainText(
        language === "tr" ? "Geçmiş haftalar" : "Past gameweeks",
      );
      await settled();
      expect(await page.evaluate(scrollsSideways)).toBe(false);
      expect(await page.evaluate(clippedCells)).toEqual([]);
      expect(await page.evaluate(crossedLabels)).toEqual([]);
      await everyTargetFits();

      // The other view, by its name, and a club of it.
      await main.getByRole("radio", { name: copy.teamView, exact: true }).click();
      await expect(page).toHaveURL(/view=team/);
      await main.getByRole("radio", { name: /^TOT / }).click();
      await expect(page).toHaveURL(/team=TOT/);
      await expect(main.getByRole("heading", { level: 2 })).toHaveText("Spurs");
      const cells = clubCells("TOT");
      await expect(main.getByRole("listitem")).toHaveCount(cells.length);
      await expect(main.getByRole("listitem").first()).toContainText(
        common.gameweekShort(cells[0]!),
      );
      await settled();
      expect(await page.evaluate(scrollsSideways)).toBe(false);
      expect(await page.evaluate(clippedCells)).toEqual([]);
      expect(await page.evaluate(crossedLabels)).toEqual([]);
      await everyTargetFits();

      // A further choice leaves the page where it is, on a screen short enough to scroll.
      await page.setViewportSize({ width, height: 400 });
      await page.evaluate(() => window.scrollTo(0, 100));
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(100);
      await main.getByRole("radio", { name: /^ARS / }).click();
      await expect(main.getByRole("heading", { level: 2 })).toHaveText("Arsenal");
      expect(await page.evaluate(() => window.scrollY)).toBe(100);

      // The address opens the same view again.
      await page.reload();
      await expect(main.getByRole("radio", { name: /^ARS / })).toBeChecked();
      await expect(main.getByRole("heading", { level: 2 })).toHaveText("Arsenal");
    });

for (const [width, top] of [
  [1440, 0],
  [820, 0],
  [390, 56],
] as const)
  test(`at ${width}px the week numbers stay in view while the matrix scrolls under them`, async ({
    page,
  }) => {
    test.skip(run.length === 0, "The shipped season is over: there is no matrix to scroll.");
    await page.setViewportSize({ width, height: 420 });
    await page.clock.setFixedTime(new Date(CLOCK));
    await page.goto("/fixtures");
    const head = page.getByRole("main").getByRole("columnheader").nth(1);
    await expect(head).toBeVisible();
    await page.evaluate(() => {
      const table = document.querySelector("main table")!;
      window.scrollTo(0, table.getBoundingClientRect().top + window.scrollY + 200);
    });
    await expect.poll(async () => (await head.boundingBox())!.y).toBe(top);
  });

test("the chosen club stands apart from the others, by day, at night and in high contrast", async ({
  page,
}) => {
  test.skip(run.length === 0, "The shipped season is over: the page offers no club.");
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto("/fixtures?view=team&team=LIV");
  const fill = (state: "checked" | "not(:checked)") =>
    page
      .locator(`main label:has(input[name="fixture-club"]:${state})`)
      .first()
      .evaluate((label) => getComputedStyle(label).backgroundColor);
  await expect(page.getByRole("main").getByRole("heading", { level: 2 })).toHaveText("Liverpool");

  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    const ratio = contrastRatio(hexOf(await fill("checked")), hexOf(await fill("not(:checked)")));
    expect(ratio, colorScheme).toBeGreaterThanOrEqual(3);
  }

  await page.emulateMedia({ forcedColors: "active" });
  expect(await fill("checked")).not.toBe(await fill("not(:checked)"));
});

test("the keyboard moves through the choices and stays on them, and Back leaves the page", async ({
  page,
}) => {
  test.skip(run.length === 0, "The shipped season is over: the page offers no choice.");
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto(LEAGUE_PAGE);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");
  await page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }).click();
  await expect(page).toHaveURL("/fixtures");
  const main = page.getByRole("main");

  await main.getByRole("radio", { name: "Genel fikstür", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  const team = main.getByRole("radio", { name: "Takım fikstürü", exact: true });
  await expect(team).toBeChecked();
  await expect(team).toBeFocused();
  await expect(page).toHaveURL("/fixtures?view=team");

  await page.goBack();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");
});
