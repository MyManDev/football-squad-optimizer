import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("member list links to point-labelled advice and preserves its URL state", async ({ page }) => {
  await page.goto("/league/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Üyeleri");
  await expect(page.getByText("örnek veri")).toBeVisible();
  await expect(page.getByText("SquadOpt · sistem takımı")).toHaveCount(0);

  await page.getByRole("link", { name: "Deniz Aral" }).click();
  await expect(page).toHaveURL(/\/league\/members\/35249001$/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();

  // Pure points is published at three and five weeks; the window's limits are stated.
  await expect(page.getByRole("radio", { name: /3 hafta/ })).toBeEnabled();
  await page.getByRole("radio", { name: /3 hafta/ }).click();
  await expect(page).toHaveURL(/window=3/);
  await expect(page.getByRole("region", { name: "3 haftalık pencere" })).toBeVisible();
  await expect(page.getByText(/Bu pencerenin varsaydıkları/)).toBeVisible();
  await page.getByRole("radio", { name: /1 hafta/ }).click();
  // A rival strategy stays at one week: the longer windows are shown disabled.
  await page.getByRole("radio", { name: /^Ortak çekirdeği koru/ }).click();
  await expect(page).toHaveURL(/mode=ortak-koru/);
  await expect(page.getByRole("radio", { name: /3 hafta/ })).toBeDisabled();
  const rival = page.getByRole("combobox", { name: "Karşısında oynadığın üye" });
  await expect(rival).toBeVisible();
  await rival.selectOption({ index: 1 });
  await expect(page).toHaveURL(/rival=\d+/);
  await expect(page.getByText(/beklenen puan maliyeti/).first()).toBeVisible();
  await expect(page.getByText(/yalnızca senin kadrondan/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kaydedilen puan farkı" })).toHaveCount(0);
  await expect(page.getByText(/rakibe karşı beklenen fark/)).toBeVisible();
  await expect(page.locator('[aria-labelledby="entry-advice-title"]')).not.toContainText("%");

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Ortak çekirdeği koru/ })).toBeChecked();
  await expect(page).toHaveURL(/rival=\d+/);
});

test("the virtual SquadOpt member remains available by direct URL without probability claims", async ({
  page,
}) => {
  await page.goto("/league/members/squadopt");

  await expect(page).toHaveURL(/\/league\/members\/squadopt$/);
  await expect(page.getByText("SquadOpt da oynuyor")).toBeVisible();
  await expect(page.getByText(/Sistemin kendi takımı bu hesaba girmez/)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Oyun haftası 1/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(page.getByText("SquadOpt da oynuyor").locator("..")).not.toContainText("%");
});

test("member navigation is keyboard operable with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/league/members");

  const memberLink = page.getByRole("link", { name: "Deniz Aral" });
  await memberLink.focus();
  await expect(memberLink).toBeFocused();
  await expect(memberLink).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/league\/members\/35249001$/);

  const mode = page.getByRole("radio", { name: /^Fark yarat/ });
  await mode.focus();
  await page.keyboard.press("Space");
  await expect(mode).toBeChecked();

  const motion = await page.locator("main").evaluate((main) => {
    const probe = document.createElement("div");
    probe.style.animationDuration = "10s";
    probe.style.transitionDuration = "10s";
    main.append(probe);
    const style = getComputedStyle(probe);
    return { animation: style.animationDuration, transition: style.transitionDuration };
  });
  expect(motion).toEqual({ animation: "0s", transition: "0s" });
});

const humanMembers = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
const firstMember = humanMembers[0]!;
const secondMember = humanMembers[1]!;

for (const language of ["tr", "en"] as const) {
  test(`member selection survives reload, switches and clears in ${language}`, async ({ page }) => {
    const copy = MESSAGES[language].leagueMembers;
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await page.goto("/league/members");
    const firstRow = page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: firstMember.manager_name! }) });
    await firstRow.getByRole("button", { name: copy.viewerSelect }).click();
    await expect(page).toHaveURL(`/league/members/${firstMember.entry_id}`);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("squadopt.viewer")!))).toEqual(
      { entryId: firstMember.entry_id },
    );
    await page.reload();
    await expect(page.getByText(copy.viewerSelected(firstMember.manager_name!))).toBeVisible();
    await expect(page.getByText(copy.viewerBody)).toBeVisible();

    await page.getByRole("link", { name: copy.viewerChange }).click();
    await page.getByRole("link", { name: secondMember.manager_name! }).click();
    await expect(page).toHaveURL(`/league/members/${secondMember.entry_id}`);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("squadopt.viewer")!))).toEqual(
      { entryId: firstMember.entry_id },
    );

    await page.getByRole("link", { name: copy.viewerChange }).click();
    const secondRow = page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: secondMember.manager_name! }) });
    await secondRow.getByRole("button", { name: copy.viewerSelect }).click();
    await expect(page).toHaveURL(`/league/members/${secondMember.entry_id}`);
    await expect(page.getByText(copy.viewerSelected(secondMember.manager_name!))).toBeVisible();
    await page.getByRole("button", { name: copy.viewerClear }).click();
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
    await page.reload();
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();

    await page.getByRole("link", { name: copy.backToMembers }).click();
    await page.getByRole("link", { name: firstMember.manager_name! }).click();
    await expect(page).toHaveURL(`/league/members/${firstMember.entry_id}`);
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
  });

  test(`a stale saved selection can be cleared from the list in ${language}`, async ({ page }) => {
    const copy = MESSAGES[language].leagueMembers;
    await page.addInitScript((value) => {
      localStorage.setItem("squadopt.language", value);
      localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: 99999999 }));
    }, language);
    await page.goto("/league/members");
    await expect(page.getByText(copy.viewerMissing)).toBeVisible();
    await expect(page.getByRole("link", { name: copy.viewerChange })).toHaveAttribute(
      "href",
      "#league-member-list",
    );
    await page.getByRole("button", { name: copy.viewerClear }).click();
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
    await expect(page.getByText(copy.viewerMissing)).toHaveCount(0);
  });
}
