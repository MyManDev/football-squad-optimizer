import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { atRest } from "./atRest";
import { installLeagueMocks } from "./leagueMocks";

const ENTRY = 35249001;
const copy = MESSAGES.tr;
const member = copy.leagueMembers;

/** The phone bar's lower edge, and the strip's under it (PageShell and the page's styles). */
const PHONE_BAR = 56;
const BOTH_BARS = PHONE_BAR + 40;

async function open(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  // The wheel turns over the page, not the phone bar.
  await page.mouse.move(width / 2, height / 2);
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await page.goto(`/league/352490/members/${ENTRY}`);
  await expect(page.getByRole("heading", { name: member.squadAfterTitle })).toBeVisible();
  await page.evaluate(async () => {
    await Promise.allSettled([...document.fonts].map((face) => face.load()));
    await document.fonts.ready;
  });
}

// Hidden ones too, so a strip that stands aside is told apart from one that is not there.
const strip = (page: Page) =>
  page.getByRole("navigation", { name: member.sectionsLabel, includeHidden: true });
const link = (page: Page, name: string) =>
  strip(page).getByRole("link", { name, exact: true, includeHidden: true });

/** Waits until the page has stopped scrolling: a jump from the strip may glide. */
async function settled(page: Page) {
  await page.waitForFunction(
    () =>
      new Promise<boolean>((resolve) => {
        const start = scrollY;
        requestAnimationFrame(() =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve(scrollY === start))),
        );
      }),
  );
}

/** The top of an element, and whether it is what the screen shows at its first line. */
async function landing(locator: Locator) {
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + Math.min(box.width / 2, 40), box.top + 2);
    return { top: Math.round(box.top), seen: hit !== null && element.contains(hit) };
  });
}

/** axe's critical and serious findings on the page as it stands, at rest. */
async function blocking(page: Page) {
  await atRest(page);
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))
    .map((violation) => violation.id);
}

test("at 390x844 the strip takes no room, then sticks under the phone bar once the decision is read past", async ({
  page,
}) => {
  await open(page, 390, 844);
  // The first screen is the page's own: the strip waits, hidden and taking no room.
  await expect(strip(page)).toBeAttached();
  await expect(strip(page)).toBeHidden();
  expect(await blocking(page)).toEqual([]);
  expect(
    await strip(page).evaluate((nav) => nav.parentElement!.getBoundingClientRect().height),
  ).toBe(0);

  // Scrolled past the decision's heading, it is drawn right under the phone bar and stays
  // there however far the page scrolls.
  for (const distance of [700, 900, 1400]) {
    await page.mouse.wheel(0, distance);
    await settled(page);
    await expect(strip(page)).toBeVisible();
    await expect
      .poll(async () => {
        const box = (await strip(page).boundingBox())!;
        return [Math.round(box.y), Math.round(box.height)];
      })
      .toEqual([PHONE_BAR, 40]);
  }
  // Each link is a 44 px target.
  for (const name of [member.sectionMove, member.sectionSquad, member.sectionTools]) {
    const box = (await link(page, name).boundingBox())!;
    expect(box.height, name).toBeGreaterThanOrEqual(44);
    expect(box.width, name).toBeGreaterThanOrEqual(44);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("at 390x844 each link lands its section under both bars and marks it as current", async ({
  page,
}) => {
  await open(page, 390, 844);
  await page.mouse.wheel(0, 900);
  await settled(page);
  await expect(strip(page)).toBeVisible();

  await link(page, member.sectionSquad).click();
  await expect(page).toHaveURL(/#kadro$/);
  await settled(page);
  const squad = page.getByRole("heading", { name: member.squadAfterTitle });
  const atSquad = await landing(squad);
  expect(atSquad.top).toBeGreaterThanOrEqual(BOTH_BARS);
  expect(atSquad.top).toBeLessThan(BOTH_BARS + 48);
  expect(atSquad.seen).toBe(true);
  await expect(link(page, member.sectionSquad)).toHaveAttribute("aria-current", "location");
  await expect(strip(page).locator('[aria-current="location"]')).toHaveCount(1);
  expect(await blocking(page)).toEqual([]);

  await link(page, member.sectionTools).click();
  await expect(page).toHaveURL(/#member-tools$/);
  await settled(page);
  // The tools have no heading of their own: the first section's summary heads them.
  const tools = page.locator("#member-tools > details > summary").first();
  const atTools = await landing(tools);
  expect(atTools.top).toBeGreaterThanOrEqual(BOTH_BARS);
  expect(atTools.seen).toBe(true);
  await expect(link(page, member.sectionTools)).toHaveAttribute("aria-current", "location");

  // Back at the decision the strip stands aside, so its heading is under the phone bar alone.
  await link(page, member.sectionMove).click();
  await expect(page).toHaveURL(/#entry-advice-title$/);
  await settled(page);
  await expect(strip(page)).toBeHidden();
  const decision = page.locator("#entry-advice-title");
  const atDecision = await landing(decision);
  expect(atDecision.top).toBeGreaterThanOrEqual(PHONE_BAR);
  expect(atDecision.top).toBeLessThan(BOTH_BARS);
  expect(atDecision.seen).toBe(true);
  await expect(link(page, member.sectionMove)).toHaveAttribute("aria-current", "location");
});

test("at 390x844 a jump from the strip glides only where motion is allowed", async ({ page }) => {
  await open(page, 390, 844);
  await page.mouse.wheel(0, 900);
  await settled(page);
  const behaviour = () =>
    page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior);
  // Any other jump is instant, the decision's 'Planı gör' among them.
  expect(await behaviour()).toBe("auto");
  // Reached by the keyboard, the strip holds still: a link in it, pinned inside the page's
  // scroll padding, is not scrolled clear of it.
  const at = await page.evaluate(() => scrollY);
  await link(page, member.sectionSquad).focus();
  await page.keyboard.press("Tab");
  await expect(link(page, member.sectionTools)).toBeFocused();
  await settled(page);
  expect(await page.evaluate(() => scrollY)).toBe(at);
  await expect(strip(page)).toBeVisible();
  expect(await behaviour()).toBe("smooth");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await behaviour()).toBe("auto");
  await link(page, member.sectionTools).click();
  // Under reduced motion the jump has landed by the time the click returns.
  const before = await page.evaluate(() => scrollY);
  await settled(page);
  expect(await page.evaluate(() => scrollY)).toBe(before);
});

for (const [width, height] of [
  [600, 900],
  [1024, 768],
] as const)
  test(`the strip is not in the page at ${width}x${height}`, async ({ page }) => {
    await open(page, width, height);
    await expect(strip(page)).toHaveCount(0);
    await expect(page.locator("#member-tools")).toHaveCount(1);
  });
