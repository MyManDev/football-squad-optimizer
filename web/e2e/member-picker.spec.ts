import { expect, test, type Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { EXAMPLE_CLAIM, exampleMember, pickMember } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { NO_LEAGUE, rememberedLeague } from "./leagueState";

/**
 * "Ligini bul", then "Sen kimsin?": nothing of a league opens before both steps, the
 * picker shows names only, Onayla opens the page asked for or the visitor's own page, and
 * the sidebar's Değiştir is the one way to be someone else.
 */

const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const MEMBERS = `/league/${LEAGUE}/members`;
const own = (entryId: number) => `${MEMBERS}/${entryId}`;
const CONTRIBUTE = process.env.VITE_ADVICE_API_ORIGIN ? ["/contribute"] : [];
const TR = MESSAGES.tr;
const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);

const sidebarLinks = (page: Page) =>
  page.locator("#sidebar a").evaluateAll((links) => links.map((link) => link.getAttribute("href")));

const pickerHeading = (page: Page, language: "tr" | "en" = "tr") =>
  page.getByRole("heading", { level: 1, name: MESSAGES[language].memberPicker.title });

async function focusedText(page: Page) {
  return page.evaluate(() => {
    const active = document.activeElement;
    return { tag: active?.tagName ?? null, text: active?.textContent ?? null };
  });
}

test.describe("the sidebar before and after the two steps", () => {
  test.describe("with no league entered", () => {
    test.use({ storageState: NO_LEAGUE });

    test("offers 'Ligini bul' and the open pages only", async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await installLeagueMocks(page, { claim: null });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(TR.leagueEntry.title);
      expect(await sidebarLinks(page)).toEqual(["/", "/fixtures", ...CONTRIBUTE]);
      const sidebar = page.locator("#sidebar");
      for (const name of [TR.shell.thisWeek, TR.shell.squad, TR.shell.league]) {
        await expect(sidebar.getByRole("link", { name, exact: true })).toHaveCount(0);
      }
      await expect(sidebar.getByRole("button", { name: TR.shell.changeMember })).toHaveCount(0);
      const buttons = sidebar.getByRole("button");
      await expect(buttons).toHaveCount(3);
      await expect(buttons.nth(0)).toHaveAccessibleName(TR.shell.collapseSidebar);
      await expect(buttons.nth(1)).toHaveAccessibleName(/^TR/);
      await expect(buttons.nth(2)).toHaveAccessibleName(/^EN/);
    });
  });

  test("with a league entered and nobody claimed, 'Ligini bul' opens that league's step", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page, { claim: null });
    for (const path of ["/", MEMBERS]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await sidebarLinks(page)).toEqual([MEMBERS, "/fixtures", ...CONTRIBUTE]);
      const find = page.locator("#sidebar").getByRole("link", {
        name: TR.shell.findLeague,
        exact: true,
      });
      if (path === MEMBERS) await expect(find).toHaveAttribute("aria-current", "page");
      else await expect(find).not.toHaveAttribute("aria-current");
      for (const name of [TR.shell.squad, TR.shell.league]) {
        await expect(page.locator("#sidebar").getByRole("link", { name, exact: true })).toHaveCount(
          0,
        );
      }
      await expect(
        page.locator("#sidebar").getByRole("button", { name: TR.shell.changeMember }),
      ).toHaveCount(0);
    }
  });

  test("with the member claimed, the league part opens with the identity block", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page);
    await page.goto("/fixtures");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await sidebarLinks(page)).toEqual([
      own(EXAMPLE_CLAIM.entryId),
      `${own(EXAMPLE_CLAIM.entryId)}#kadro`,
      MEMBERS,
      "/fixtures",
      ...CONTRIBUTE,
    ]);
    const sidebar = page.locator("#sidebar");
    await expect(sidebar).toContainText(EXAMPLE_CLAIM.leagueName!);
    await expect(sidebar).toContainText("Deniz Aral");
    await expect(sidebar.getByRole("button", { name: TR.shell.changeMember })).toBeVisible();
  });
});

test.describe("before the visitor says who they are", () => {
  test("every league page shows the picker in place, with names only and nothing else read", async ({
    page,
  }) => {
    await installLeagueMocks(page, { claim: null });
    const reads: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/data/")) reads.push(path);
    });
    const addresses: [string, string][] = [
      [`/league/${LEAGUE}`, `/league/${LEAGUE}`],
      [MEMBERS, MEMBERS],
      [own(35249002), own(35249002)],
      [`${own(35249002)}/history`, `${own(35249002)}/history`],
      ["/league/members/35249002", own(35249002)],
    ];
    for (const [address, shown] of addresses) {
      await page.goto(address);
      await expect(pickerHeading(page)).toBeVisible();
      await expect(page).toHaveURL(shown);
      await expect(page.locator("main table")).toHaveCount(0);
      await expect(page.locator('[data-mark="decision"]')).toHaveCount(0);
      const options = page.locator("[data-member-picker] label");
      await expect(options).toHaveCount(humans.length);
      const texts = await options.allTextContents();
      expect(new Set(texts)).toEqual(
        new Set(
          humans.map(
            (member) =>
              `${member.manager_name ?? TR.leagueMembers.unknownMember}, ${
                member.team_name ?? TR.leagueMembers.unknownTeam
              }`,
          ),
        ),
      );
      // No member's entry number reaches the picker's markup either, in any attribute.
      const attributes = await page
        .locator("[data-member-picker]")
        .evaluate((root) =>
          [root, ...root.querySelectorAll("*")].flatMap((element) =>
            [...element.attributes].map((attribute) => `${attribute.name}=${attribute.value}`),
          ),
        );
      const numbers = humans.map((member) => String(member.entry_id));
      expect(
        attributes.filter((attribute) => numbers.some((number) => attribute.includes(number))),
      ).toEqual([]);
    }
    const allowed = new Set([
      "/data/leagues.json",
      "/data/league/members.json",
      "/data/fixtures.json",
    ]);
    expect(reads.filter((path) => !allowed.has(path))).toEqual([]);
    expect(
      reads.filter((path) =>
        /entries\/|advice\/|history\/|scoreboard\.json|index\.json|ledger|\/data\/\d{4}-\d{2}\/gw/.test(
          path,
        ),
      ),
    ).toEqual([]);
  });

  test("lists every member by name, none of them the system, and is used by keyboard alone", async ({
    page,
  }) => {
    await installLeagueMocks(page, { claim: null });
    await page.goto(MEMBERS);
    const group = page.getByRole("group", { name: TR.memberPicker.legend });
    await expect(group).toBeVisible();
    const radios = group.getByRole("radio");
    await expect(radios).toHaveCount(humans.length);
    await expect(group.getByRole("radio", { name: /SquadOpt/ })).toHaveCount(0);
    const names = (await page.locator("[data-member-picker] label").allTextContents()).map(
      (text) => text.split(", ")[0]!,
    );
    const named = names.filter((name) => name !== TR.leagueMembers.unknownMember);
    expect(named).toEqual(
      [...named].sort(new Intl.Collator("tr", { sensitivity: "base" }).compare),
    );
    expect(names.at(-1)).toBe(TR.leagueMembers.unknownMember);

    const confirm = page.getByRole("button", { name: TR.memberPicker.confirm, exact: true });
    await expect(confirm).toBeDisabled();
    await pickerHeading(page).focus();
    await page.keyboard.press("Tab");
    await expect(radios.nth(0)).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(radios.nth(1)).toBeFocused();
    await page.keyboard.press("Space");
    await expect(radios.nth(1)).toBeChecked();
    await expect(confirm).toBeEnabled();
    await page.keyboard.press("Tab");
    await expect(confirm).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#league-member-list")).toBeVisible();
    await expect(page).toHaveURL(MEMBERS);
  });

  test("is shut while the member list cannot be read, and opens when it can", async ({ page }) => {
    await installLeagueMocks(page, { claim: null });
    // The legacy site reads its member list as the directory first; the member step's own
    // read of it is the one that fails.
    let served = 0;
    await page.route("**/data/league/members.json", (route) => {
      served += 1;
      if (served === 2) return route.fulfill({ status: 503, body: "" });
      return route.fulfill({ json: mockLeagueMembersEnvelope });
    });
    await page.goto(MEMBERS);
    await expect(page.getByText(TR.leagueMembers.membersUnreadable)).toBeVisible();
    await expect(page.locator("main table")).toHaveCount(0);
    await expect(page.getByRole("group", { name: TR.memberPicker.legend })).toHaveCount(0);
    await page.getByRole("button", { name: TR.leagueEntry.retry, exact: true }).click();
    await expect(page.getByRole("group", { name: TR.memberPicker.legend })).toBeVisible();
  });
});

test.describe("from the league number to the visitor's own page", () => {
  test.use({ storageState: NO_LEAGUE });

  test("asks the number, then who you are, then opens your page without the table between", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page, { claim: null });
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ json: { ...mockLeagueMembersEnvelope, source_kind: "live" } }),
    );
    await page.goto("/");
    await page.getByLabel(TR.leagueEntry.label).fill(String(LEAGUE));
    await page.getByRole("button", { name: TR.leagueEntry.submit, exact: true }).click();
    await expect(page).toHaveURL(MEMBERS);
    await expect(pickerHeading(page)).toBeFocused();

    await page.evaluate(() => {
      const seen = { table: false };
      (window as unknown as { tableSeen: typeof seen }).tableSeen = seen;
      new MutationObserver(() => {
        if (document.querySelector("main #league-member-list")) seen.table = true;
      }).observe(document.body, { childList: true, subtree: true });
    });
    await pickMember(page, exampleMember(35249002));
    await expect(page).toHaveURL(own(35249002));
    const team = humans.find((member) => member.entry_id === 35249002)!.team_name!;
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(team);
    expect(
      await page.evaluate(
        () => (window as unknown as { tableSeen: { table: boolean } }).tableSeen.table,
      ),
    ).toBe(false);
    await expect(
      page.locator("#sidebar").getByRole("link", { name: TR.shell.thisWeek, exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect.poll(() => focusedText(page)).toEqual({ tag: "H1", text: team });
  });
});

test.describe("a deep link behind the step", () => {
  test("keeps the address asked for, opens it after the step, and scrolls to the squad", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page, { claim: null });
    const address = `${own(35249003)}?mode=agresif&window=3#kadro`;
    await page.goto(address);
    await expect(pickerHeading(page)).toBeVisible();
    // The shell's own wait for #kadro runs out while the picker is up.
    await page.waitForTimeout(6_000);
    await pickMember(page, EXAMPLE_CLAIM);
    await expect(page).toHaveURL(address);
    const team = humans.find((member) => member.entry_id === 35249003)!.team_name!;
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(team);
    await expect
      .poll(() =>
        page.evaluate(() => {
          const squad = document.getElementById("kadro");
          if (!squad) return false;
          const box = squad.getBoundingClientRect();
          return box.top >= 0 && box.top < window.innerHeight;
        }),
      )
      .toBe(true);
    const thisWeek = page
      .locator("#sidebar")
      .getByRole("link", { name: TR.shell.thisWeek, exact: true });
    await expect(thisWeek).toHaveAttribute("href", own(EXAMPLE_CLAIM.entryId));
    await expect(thisWeek).not.toHaveAttribute("aria-current");
  });
});

test.describe("how long the step holds", () => {
  test("a reload in the same tab keeps it, in this tab's storage only", async ({ page }) => {
    await installLeagueMocks(page, { claim: null });
    await page.goto(MEMBERS);
    await pickMember(page, exampleMember(35249002));
    await expect(page.locator("#league-member-list")).toBeVisible();
    await page.reload();
    await expect(page.locator("#league-member-list")).toBeVisible();
    await expect(page.locator("[data-member-picker]")).toHaveCount(0);
    expect(await page.evaluate(() => sessionStorage.getItem("squadopt.member"))).not.toBeNull();
    expect(
      await page.evaluate(() => [
        localStorage.getItem("squadopt.viewer"),
        localStorage.getItem("squadopt.member"),
      ]),
    ).toEqual([null, null]);
  });

  test("a new tab and a new visit ask again", async ({ page, browser, baseURL }) => {
    await installLeagueMocks(page, { claim: null });
    await page.goto(MEMBERS);
    await pickMember(page, exampleMember(35249002));
    await expect(page.locator("#league-member-list")).toBeVisible();

    const tab = await page.context().newPage();
    await installLeagueMocks(tab, { claim: null });
    await tab.goto(MEMBERS);
    await expect(pickerHeading(tab)).toBeVisible();
    expect(await tab.evaluate(() => sessionStorage.getItem("squadopt.member"))).toBeNull();
    await tab.close();

    const visit = await browser.newContext({ storageState: rememberedLeague(baseURL!) });
    const fresh = await visit.newPage();
    await installLeagueMocks(fresh, { claim: null });
    await fresh.goto(MEMBERS);
    await expect(pickerHeading(fresh)).toBeVisible();
    expect(await fresh.evaluate(() => sessionStorage.getItem("squadopt.member"))).toBeNull();
    await visit.close();
  });
});

test.describe("Değiştir", () => {
  test("returns to the step for the same league and opens the next member's own page", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installLeagueMocks(page);
    await page.goto(own(EXAMPLE_CLAIM.entryId));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(EXAMPLE_CLAIM.teamName!);
    await page.locator("#sidebar").getByRole("button", { name: TR.shell.changeMember }).click();
    await expect(page).toHaveURL(MEMBERS);
    await expect(pickerHeading(page)).toBeFocused();
    await expect(
      page.locator("#sidebar").getByRole("link", { name: TR.shell.findLeague, exact: true }),
    ).toBeVisible();
    await pickMember(page, exampleMember(35249004));
    await expect(page).toHaveURL(own(35249004));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      humans.find((member) => member.entry_id === 35249004)!.team_name!,
    );
  });

  for (const width of [390, 360]) {
    test(`on a ${width} px phone closes the menu, focuses the question and keeps 44 px targets`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 800 });
      await installLeagueMocks(page);
      await page.goto(own(EXAMPLE_CLAIM.entryId));
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(EXAMPLE_CLAIM.teamName!);
      await page.getByRole("banner").getByRole("button", { name: TR.shell.openMenu }).click();
      await expect(page.locator("#sidebar")).toHaveCSS("transform", "none");
      const change = page.locator("#sidebar").getByRole("button", { name: TR.shell.changeMember });
      expect((await change.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      expect((await change.boundingBox())!.width).toBeGreaterThanOrEqual(44);
      await change.click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(pickerHeading(page)).toBeVisible();
      await expect(pickerHeading(page)).toBeFocused();

      for (const control of [
        ...(await page.locator("[data-member-picker] label").all()),
        page.getByRole("button", { name: TR.memberPicker.confirm, exact: true }),
        page.getByRole("link", { name: TR.memberPicker.otherLeague }),
      ]) {
        const box = (await control.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    });
  }

  test("the retry of an unreadable member list is a 44 px target", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await installLeagueMocks(page, { claim: null });
    let served = 0;
    await page.route("**/data/league/members.json", (route) => {
      served += 1;
      if (served >= 2) return route.fulfill({ status: 503, body: "" });
      return route.fulfill({ json: mockLeagueMembersEnvelope });
    });
    await page.goto(MEMBERS);
    const retry = page.getByRole("button", { name: TR.leagueEntry.retry, exact: true });
    await expect(retry).toBeVisible();
    expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
});

test.describe("after the step", () => {
  test("the system team's old address draws no squad", async ({ page }) => {
    await installLeagueMocks(page);
    await page.goto(`${MEMBERS}/squadopt`);
    await expect(page.getByText(TR.leagueMembers.invalidEntry)).toBeVisible();
    await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toHaveCount(0);
    await expect(page.getByText("SquadOpt da oynuyor")).toHaveCount(0);
  });

  for (const language of ["tr", "en"] as const) {
    test(`the members page carries no self-claim, record or count in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await installLeagueMocks(page);
      await page.goto(MEMBERS);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        mockLeagueMembersEnvelope.payload.league_name,
      );
      const main = page.locator("main");
      await expect(main.locator('[data-mark="karne"]')).toHaveCount(0);
      const text = (await main.textContent()) ?? "";
      expect(text).not.toMatch(/Hangisi sensin\?|Which one is you\?/);
      expect(text).not.toMatch(/\d+ üye|\d+ members/);
      expect(text).not.toMatch(/hafta sonunda|after gameweek/);
      expect(text).not.toMatch(/Bu benim|This is me/);
      const name = MESSAGES[language].shell.changeMember;
      await expect(page.getByRole("button", { name, exact: true })).toHaveCount(1);
      await expect(page.locator("#sidebar").getByRole("button", { name, exact: true })).toHaveCount(
        1,
      );
    });
  }
});

test("with reduced motion the picker and the drawer do not move", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page, { claim: null });
  await page.goto(MEMBERS);
  await expect(page.getByRole("group", { name: TR.memberPicker.legend })).toBeVisible();
  const durations = (selector: string) =>
    page
      .locator(selector)
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return { animation: style.animationDuration, transition: style.transitionDuration };
      });
  for (const selector of [
    "[data-member-picker]",
    "[data-member-picker] label",
    "[data-member-picker] button[type=submit]",
  ]) {
    expect(await durations(selector), selector).toEqual({ animation: "0s", transition: "0s" });
  }
  await page.getByRole("banner").getByRole("button", { name: TR.shell.openMenu }).click();
  const drawer = await page.locator("#sidebar").evaluate((element) => {
    const style = getComputedStyle(element);
    return style.transitionDuration.split(",").every((value) => Number.parseFloat(value) === 0);
  });
  expect(drawer).toBe(true);
});

test.describe("the system's own pages behind the same two steps", () => {
  test.describe("with no league entered", () => {
    test.use({ storageState: NO_LEAGUE });

    test("the moves page asks for the number, then who you are, in place", async ({ page }) => {
      await installLeagueMocks(page, { claim: null });
      await page.route("**/data/league/members.json", (route) =>
        route.fulfill({ json: { ...mockLeagueMembersEnvelope, source_kind: "live" } }),
      );
      await page.goto("/moves");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(TR.leagueEntry.title);
      await page.getByLabel(TR.leagueEntry.label).fill(String(LEAGUE));
      await page.getByRole("button", { name: TR.leagueEntry.submit, exact: true }).click();
      await expect(page).toHaveURL("/moves");
      await expect(pickerHeading(page)).toBeFocused();
      await pickMember(page, exampleMember(35249002));
      await expect(page).toHaveURL("/moves");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(TR.moves.title);
    });

    for (const [address, numbered] of [
      ["/league", `/league/${LEAGUE}`],
      ["/league/members", MEMBERS],
      ["/league/members/35249002", own(35249002)],
    ] as const) {
      test(`an address from before the number (${address}) puts focus on who you are`, async ({
        page,
      }) => {
        await installLeagueMocks(page, { claim: null });
        await page.route("**/data/league/members.json", (route) =>
          route.fulfill({ json: { ...mockLeagueMembersEnvelope, source_kind: "live" } }),
        );
        await page.goto(address);
        await expect(page.getByRole("heading", { level: 1 })).toHaveText(TR.leagueEntry.title);
        await page.getByLabel(TR.leagueEntry.label).fill(String(LEAGUE));
        await page.getByLabel(TR.leagueEntry.label).press("Enter");
        await expect(page).toHaveURL(numbered);
        await expect(pickerHeading(page)).toBeFocused();
      });
    }
  });

  test("the rivals page and the gameweek page ask who you are before reading anything", async ({
    page,
  }) => {
    await installLeagueMocks(page, { claim: null });
    const reads: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (/^\/data\/\d{4}-\d{2}\//.test(path)) reads.push(path);
    });
    for (const address of ["/rivals", "/gw/2026-27/1"]) {
      await page.goto(address);
      await expect(pickerHeading(page)).toBeVisible();
      await expect(page).toHaveURL(address);
    }
    expect(reads).toEqual([]);
  });
});
