import { expect, test, type Page } from "@playwright/test";

import { claimMember, shippedClaim } from "./identity";

// On a phone every control in the page's own content is at least 36px tall and wide where a
// thumb lands (the comparison's week strip is 36px wide and over 100px tall): the week buttons of the history's overview and the "back to the member" links
// were 31px and 18px tall on the live site.
test.use({ viewport: { width: 390, height: 844 } });

async function smallTargets(page: Page) {
  await expect(page.locator("main")).not.toContainText(/Yükleniyor|Loading/);
  return page.evaluate(() =>
    [...document.querySelectorAll("main a[href], main button")]
      .map((el) => ({ el, box: el.getBoundingClientRect() }))
      .filter(
        ({ el, box }) =>
          box.width > 0 && box.height > 0 && !el.classList.contains("visually-hidden"),
      )
      .filter(({ box }) => box.width < 36 || box.height < 36)
      .map(({ el, box }) => ({
        text: (el.textContent ?? "").trim().slice(0, 30),
        w: Math.round(box.width),
        h: Math.round(box.height),
      })),
  );
}

test("the history and comparison pages have no small control on a phone", async ({ page }) => {
  const claim = shippedClaim();
  await claimMember(page, claim);
  for (const tool of ["history", "vs"]) {
    const address = `/league/${claim.leagueId}/members/${claim.entryId}/${tool}`;
    await page.goto(address);
    await expect(page.getByRole("link", { name: /üyeye dön|back to the member/i })).toBeVisible();
    expect(await smallTargets(page), address).toEqual([]);
  }
});
