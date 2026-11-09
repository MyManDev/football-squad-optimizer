import { expect, test, type Page } from "@playwright/test";

import { claimMember, EXAMPLE_CLAIM } from "./identity";

// iPhone Safari zooms the page in when a text control smaller than 16px takes focus, and the
// page stays zoomed once the control is left. Every control a phone visitor types into or
// chooses from is therefore at least 16px at phone width (tokens.css and the rules that set a
// control's font themselves).
test.use({ viewport: { width: 390, height: 844 } });

const SKIPPED_TYPES = new Set(["checkbox", "radio", "range", "file", "hidden", "submit", "button"]);

async function controlSizes(page: Page) {
  return page.evaluate(
    (skipped) => {
      return [...document.querySelectorAll("input, select, textarea")]
        .filter((el) => !skipped.includes((el.getAttribute("type") ?? "text").toLowerCase()))
        .map((el) => ({
          name: el.getAttribute("aria-label") ?? el.getAttribute("placeholder") ?? el.id,
          size: parseFloat(getComputedStyle(el).fontSize),
        }));
    },
    [...SKIPPED_TYPES],
  );
}

async function settled(page: Page) {
  await expect(page.locator("main")).not.toContainText(/Yükleniyor|Loading/);
}

test("the member picker's team number field is at least 16px on a phone", async ({ page }) => {
  await page.goto("/league/352490/members");
  await settled(page);
  const controls = await controlSizes(page);
  expect(controls.map((c) => c.name)).toContain("Takım ID");
  for (const control of controls)
    expect(control, control.name ?? "").toHaveProperty("size", expect.any(Number));
  expect(controls.every((c) => c.size >= 16)).toBe(true);
});

test("the contribution form's controls are at least 16px on a phone", async ({ page }) => {
  test.skip(!process.env.VITE_ADVICE_API_ORIGIN, "An origin-less build has no contribution page");
  await page.goto("/contribute");
  await settled(page);
  const controls = await controlSizes(page);
  expect(controls.length).toBeGreaterThan(0);
  expect(controls.filter((c) => c.size < 16)).toEqual([]);
});

test("a claimed member's league and history pages have no control under 16px on a phone", async ({
  page,
}) => {
  await claimMember(page, EXAMPLE_CLAIM);
  for (const address of [
    `/league/${EXAMPLE_CLAIM.leagueId}/members`,
    `/league/${EXAMPLE_CLAIM.leagueId}/members/${EXAMPLE_CLAIM.entryId}/history`,
  ]) {
    await page.goto(address);
    await settled(page);
    const controls = await controlSizes(page);
    expect(
      controls.filter((c) => c.size < 16),
      address,
    ).toEqual([]);
  }
});
