import { expect, test } from "@playwright/test";

import fixtures from "../public/data/fixtures.json" with { type: "json" };
import indexFixture from "../public/data/index.json" with { type: "json" };
import { claimMember, shippedClaim } from "./identity";
import { CLUB_COLOURS } from "../src/lib/clubs";

// The gameweek page stands behind the league number and "Sen kimsin?"; this visitor has
// taken both, as the published league's first member.
test.beforeEach(async ({ page }) => {
  await claimMember(page, shippedClaim());
});

// The fixtures page reads whatever week the shipped fixture list names, which moves with every
// publish.
const current = Number(fixtures.payload.current_gameweek);
const season = indexFixture.payload.latest.season;

const scrollsSideways = () =>
  document.documentElement.scrollWidth > document.documentElement.clientWidth;

/** The upcoming pair's two weeks against the main column's content box. */
const upcomingEdges = () => {
  const main = document.querySelector("main")!;
  const box = main.getBoundingClientRect();
  const style = getComputedStyle(main);
  const [current, next] = [
    ...document.querySelectorAll('[data-mark="upcoming-weeks"] > section'),
  ].map((section) => section.getBoundingClientRect());
  return {
    left: box.left + parseFloat(style.paddingLeft),
    right: box.right - parseFloat(style.paddingRight),
    current: { left: current!.left, right: current!.right, top: current!.top },
    next: { left: next!.left, right: next!.right, top: next!.top, bottom: next!.bottom },
    currentBottom: current!.bottom,
  };
};

/** A colour from CLUB_COLOURS as the browser computes it. */
const rgb = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  return `rgb(${r}, ${g}, ${b})`;
};

/**
 * Every day heading's bottom rule and every fixture side's two-colour mark: the code printed
 * beside it and the colours the browser actually paints.
 */
const dayRulesAndMarks = () => {
  const rows = [...document.querySelectorAll("main li")];
  return {
    rules: [...document.querySelectorAll('main [class*="_day_"]')].map(
      (day) => getComputedStyle(day).borderBottomStyle,
    ),
    marks: rows.map((row) =>
      [...row.querySelectorAll<HTMLElement>("[aria-hidden='true']")]
        .filter(
          (mark) =>
            mark.style.getPropertyValue("--club-primary") !== "" &&
            mark.style.getPropertyValue("--club-secondary") !== "" &&
            mark.getBoundingClientRect().width === 10,
        )
        .map((mark) => ({
          code: mark.parentElement!.textContent!.trim(),
          painted: getComputedStyle(mark).backgroundImage.match(/rgba?\([^)]*\)/g) ?? [],
        })),
    ),
  };
};

for (const width of [1280, 1600])
  test(`a ${width}px screen keeps the page beside the sidebar, with no league-wide rail`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
    await page.goto(`/gw/${season}/1`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Oyun haftası/);

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
    const weeks = page.getByRole("main").getByRole("heading", { level: 2 });
    await expect(weeks.first()).toHaveText(`Oynanacak hafta · Oyun haftası ${current}`);
    // The upcoming week carries every fixture the shipped list names for it.
    const upcoming = page.getByRole("main").locator("section", {
      has: page.getByRole("heading", { name: `Oynanacak hafta · Oyun haftası ${current}` }),
    });
    await expect(upcoming.getByRole("listitem")).toHaveCount(
      fixtures.payload.gameweeks[current - 1]!.fixtures.length,
    );
    await expect(weeks.nth(3)).toHaveText(`Oyun haftası ${current - 1}`);

    // This week and the following one share the row: the first starts at the column's left
    // edge and the second ends at its right edge.
    const edges = await page.evaluate(upcomingEdges);
    expect(Math.abs(edges.current.left - edges.left)).toBeLessThanOrEqual(1);
    expect(Math.abs(edges.next.right - edges.right)).toBeLessThanOrEqual(1);
    expect(edges.next.top).toBe(edges.current.top);
    expect(edges.next.left).toBeGreaterThan(edges.current.right);

    // No rule between the days, no deadline and no capture time, and every club in every
    // fixture carries its two colours.
    const drawn = await page.evaluate(dayRulesAndMarks);
    expect(drawn.rules.length).toBeGreaterThan(0);
    expect(new Set(drawn.rules)).toEqual(new Set(["none"]));
    expect(drawn.marks.length).toBeGreaterThan(0);
    expect(new Set(drawn.marks.map((row) => row.length))).toEqual(new Set([2]));
    // Each mark paints the club's two colours, the primary first, and never one colour twice.
    for (const { code, painted } of drawn.marks.flat()) {
      const colours = CLUB_COLOURS[code];
      expect(colours, code).toBeDefined();
      expect(painted, code).toEqual([rgb(colours!.primary), rgb(colours!.secondary)]);
      expect(painted[0], code).not.toBe(painted[1]);
    }
    await expect(page.getByRole("main")).not.toContainText(/Son tarih|tarihli kayda göre/);
    await expect(
      page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }),
    ).toHaveAttribute("aria-current", "page");
  });

test("a phone reaches the fixture list from its bar and never scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 400, height: 800 });
  await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
  await page.goto(`/gw/${season}/1`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Oyun haftası/);
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
    page.getByRole("main").getByRole("heading", {
      level: 2,
      name: `Gelecek hafta · Oyun haftası ${current + 1}`,
    }),
  ).toBeVisible();
  expect(await page.evaluate(scrollsSideways)).toBe(false);
  // On a phone the following week stands under this week, at the same left edge.
  const edges = await page.evaluate(upcomingEdges);
  expect(edges.next.left).toBe(edges.current.left);
  expect(edges.next.top).toBeGreaterThanOrEqual(edges.currentBottom);

  // The bar stays at the top while the page scrolls under it.
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  expect((await bar.boundingBox())!.y).toBe(0);
});
