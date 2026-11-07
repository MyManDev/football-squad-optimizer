import { expect, test, type Page } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";

const LEAGUE_NAME = mockLeagueMembersEnvelope.payload.league_name;
const CONTRIBUTE = process.env.VITE_ADVICE_API_ORIGIN ? ["/contribute"] : [];

const PAGES = [
  { heading: "Ligini bul", path: "/" },
  { heading: LEAGUE_NAME, path: "/league/352490/members" },
  { heading: "Lig Analizi", path: "/league/352490" },
] as const;

test.describe("a visitor who has said who they are", () => {
  test.beforeEach(async ({ page }) => {
    await installLeagueMocks(page);
  });

  test("visitor navigation reaches the league and their own page without browser errors", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      // The league directory is optional: a site from before it answers 404 for
      // `data/leagues.json`, which the browser logs as a failed resource, and the page reads
      // its one league from the legacy tree. No other error is expected.
      if (message.type() === "error" && !message.location().url.endsWith("/data/leagues.json"))
        errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto("/");
    // 'Lig' is the member list and 'Bu hafta' the visitor's own page.
    const navigation = page.getByRole("navigation");
    await navigation.getByRole("link", { name: "Lig", exact: true }).click();
    await expect(page).toHaveURL("/league/352490/members");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(LEAGUE_NAME);
    expect(errors).toEqual([]);

    // The member page asks the refused compute service and optional documents the mocks do
    // not serve, so the error count above stops at the league; here the link alone is held.
    await navigation.getByRole("link", { name: "Bu hafta", exact: true }).click();
    await expect(page).toHaveURL("/league/352490/members/35249001");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("North Stand Notes");
  });

  test("a member page's sidebar opens the league part for the claimed member", async ({ page }) => {
    await page.goto("/league/352490/members/35249001");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("North Stand Notes");
    // The identity block carries Değiştir, a button; the links are the member's week, squad
    // and league, the member's tools and history, then the open pages.
    expect(
      await page
        .locator("#sidebar a")
        .evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
    ).toEqual([
      "/league/352490/members/35249001/vs",
      "/league/352490/members/35249001",
      "/league/352490/members",
      "/league/352490/members/35249001/current-squad",
      "/league/352490/members/35249001/what-if",
      "/league/352490/members/35249001/duel",
      "/league/352490/members/35249001/chips",
      "/league/352490/members/35249001/card",
      "/league/352490/members/35249001/history",
      "/fixtures",
      ...CONTRIBUTE,
    ]);
    await expect(
      page.locator(
        'a[href="/league/352490"], a[href^="/gw/"], a[href^="/moves"], a[href^="/rivals"], a[href="/league/352490/members/squadopt"]',
      ),
    ).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
  });

  // Day: page #FFFFFF, ink #10261A. Night: page #0D1320, ink #E7ECF5.
  const DAY = { background: "rgb(255, 255, 255)", color: "rgb(16, 38, 26)", scheme: "light" };
  const NIGHT = { background: "rgb(13, 19, 32)", color: "rgb(231, 236, 245)", scheme: "dark" };
  const palette = (page: Page) =>
    page.locator("body").evaluate((body) => {
      const style = getComputedStyle(body);
      return {
        background: style.backgroundColor,
        color: style.color,
        scheme: getComputedStyle(document.documentElement).colorScheme,
      };
    });

  for (const [system, expected] of [
    ["light", DAY],
    ["dark", NIGHT],
  ] as const) {
    test(`a ${system} system preference opens the ${expected.scheme === "dark" ? "night" : "day"} palette`, async ({
      page,
    }) => {
      // An older visit may have stored a choice under the retired key; it means nothing now.
      await page.emulateMedia({ colorScheme: system });
      await page.addInitScript(() => localStorage.setItem("squadopt.theme", "dark"));
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");

      await expect(page.locator("html")).not.toHaveAttribute("data-theme");
      expect(await palette(page)).toEqual(expected);
      expect(await page.evaluate(() => localStorage.getItem("squadopt.theme"))).toBeNull();
      expect(await page.evaluate(() => localStorage.getItem("squadopt.scheme"))).toBeNull();
    });
  }

  test("the viewer's choice holds against the system and across a reload", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/");
    const colours = page.getByRole("group", { name: "Renkler" });
    await expect(colours.getByRole("button", { name: "Gece" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await colours.getByRole("button", { name: "Gündüz" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    expect(await palette(page)).toEqual(DAY);

    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");
    expect(await palette(page)).toEqual(DAY);

    await page.emulateMedia({ colorScheme: "light" });
    await page
      .getByRole("group", { name: "Renkler" })
      .getByRole("button", { name: "Gece" })
      .click();
    expect(await palette(page)).toEqual(NIGHT);
    expect(await page.evaluate(() => localStorage.getItem("squadopt.scheme"))).toBe("dark");
  });

  test("reduced-motion preference disables animation and transitions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const probe = page.locator("body").evaluate(() => {
      const element = document.createElement("div");
      element.dataset.testid = "motion-probe";
      element.style.animationDuration = "10s";
      element.style.transitionDuration = "10s";
      document.body.append(element);
    });
    await probe;

    const motion = await page.getByTestId("motion-probe").evaluate((element) => {
      const style = getComputedStyle(element);
      return { animation: style.animationDuration, transition: style.transitionDuration };
    });
    expect(motion).toEqual({ animation: "0s", transition: "0s" });
  });

  test("long Turkish content does not overflow a 390px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));

    // The shell clips what overflows it, so the main column is read as well as the document.
    for (const destination of PAGES) {
      await page.goto(destination.path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: Math.max(
          document.documentElement.scrollWidth,
          document.querySelector("main")!.scrollWidth,
        ),
      }));
      expect(dimensions.scrollWidth, `${destination.path} overflows at 390px`).toBeLessThanOrEqual(
        dimensions.clientWidth,
      );
    }

    for (const destination of [
      { heading: LEAGUE_NAME, path: "/league/352490/members" },
      {
        heading: "North Stand Notes",
        path: "/league/352490/members/35249001?mode=agresif&window=3",
      },
    ]) {
      await page.goto(destination.path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: Math.max(
          document.documentElement.scrollWidth,
          document.querySelector("main")!.scrollWidth,
        ),
      }));
      expect(dimensions.scrollWidth, `${destination.path} overflows at 390px`).toBeLessThanOrEqual(
        dimensions.clientWidth,
      );
    }
  });
});

test.describe("a visitor who has not said who they are", () => {
  test.beforeEach(async ({ page }) => {
    await installLeagueMocks(page, { claim: null });
  });

  for (const language of ["tr", "en"] as const) {
    test(`a cold ${language} visitor finds the published member list without system-squad links`, async ({
      page,
    }) => {
      await page.addInitScript((value) => {
        localStorage.clear();
        localStorage.setItem("squadopt.language", value);
      }, language);
      const systemDataRequests: string[] = [];
      page.on("request", (request) => {
        if (/\/data\/[^/]+\/gw\d+\//.test(new URL(request.url()).pathname)) {
          systemDataRequests.push(request.url());
        }
      });

      await page.route("**/data/league/members.json", (route) =>
        route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ ...mockLeagueMembersEnvelope, source_kind: "live" }),
        }),
      );
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        language === "tr" ? "Ligini bul" : "Find your league",
      );
      await expect(page.getByLabel(language === "tr" ? "Lig numarası" : "League ID")).toHaveValue(
        "",
      );
      await page.getByLabel(language === "tr" ? "Lig numarası" : "League ID").fill("352490");
      await page
        .getByRole("button", { name: language === "tr" ? "Ligi bul" : "Find league" })
        .click();

      // After the number comes "Sen kimsin?", in place of the table, by name only.
      await expect(page).toHaveURL("/league/352490/members");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        language === "tr" ? "Sen kimsin?" : "Who are you?",
      );
      await expect(page.getByRole("button", { name: /Deniz Aral/ })).toBeVisible();
      await expect(page.locator("#league-member-list")).toHaveCount(0);
      await expect(page.locator("html")).toHaveAttribute("lang", language);
      expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
      // Until then the sidebar offers that league's step, and the open pages.
      expect(
        await page
          .locator("#sidebar a")
          .evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
      ).toEqual(["/league/352490/members", "/fixtures", ...CONTRIBUTE]);
      await expect(
        page.locator(
          'a[href="/league/352490"], a[href^="/gw/"], a[href^="/moves"], a[href^="/rivals"], a[href="/league/352490/members/squadopt"]',
        ),
      ).toHaveCount(0);
      expect(systemDataRequests).toEqual([]);
    });
  }

  test("the picker does not overflow a 390px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/league/352490/members");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sen kimsin?");
    await expect(page.getByRole("group", { name: "Adını seç" })).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  });
});
