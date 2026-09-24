import { expect, test } from "@playwright/test";

import indexFixture from "../public/data/index.json" with { type: "json" };
import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";

const PAGES = [
  { heading: "Ligini bul", path: "/" },
  { heading: "Lig Üyeleri", path: "/league/members" },
  { heading: /Oyun haftası/, path: "/gw/2026-27/1" },
  { heading: "Önerilen Hamleler", path: "/moves" },
  { heading: "Rakip Analizi", path: "/rivals" },
  { heading: "Lig Analizi", path: "/league" },
  { heading: "Yönetim", path: "/admin" },
] as const;

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("visitor navigation reaches league entry without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  // 'Lig' is the member list; the league entry page stays reachable as 'Bu hafta' while no
  // member is in context.
  const navigation = page.getByRole("navigation");
  await navigation.getByRole("link", { name: "Lig", exact: true }).click();
  await expect(page).toHaveURL("/league/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Üyeleri");
  await navigation.getByRole("link", { name: "Bu hafta", exact: true }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");

  expect(errors).toEqual([]);
});

for (const language of ["tr", "en"] as const) {
  test(`the unlisted ${language} admin page does not link to the archive or fetch system data`, async ({
    page,
  }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    const systemDataRequests: string[] = [];
    page.on("request", (request) => {
      // The shell's fixture list is the game's schedule, not a view of the system squad.
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/data/") && path !== "/data/fixtures.json") {
        systemDataRequests.push(request.url());
      }
    });

    await page.goto("/admin");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      language === "tr" ? "Yönetim" : "Admin",
    );
    await expect(page.locator('#sidebar a[href="/admin"], header a[href="/admin"]')).toHaveCount(0);
    await expect(page.locator('a[href="/league"]')).toHaveCount(0);
    expect(systemDataRequests).toEqual([]);

    // The measurement archive is not served from the member origin: its documents are the
    // laboratory's record, in the laboratory's vocabulary, and they were reachable here.
    await expect(
      page.getByRole("link", { name: language === "tr" ? "Ölçüm arşivi" : "Measurement archive" }),
    ).toHaveCount(0);
  });

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
    await expect(page.getByLabel(language === "tr" ? "Lig numarası" : "League ID")).toHaveValue("");
    await page.getByLabel(language === "tr" ? "Lig numarası" : "League ID").fill("352490");
    await page
      .getByRole("button", { name: language === "tr" ? "Ligi bul" : "Find league" })
      .click();

    await expect(page).toHaveURL("/league/members");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      language === "tr" ? "Lig Üyeleri" : "League Members",
    );
    await expect(page.getByRole("link", { name: "Deniz Aral" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", language);
    expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
    // The sidebar's navigation and its operations link are the whole chrome.
    expect(
      await page
        .locator("#sidebar a")
        .evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
    ).toEqual(["/", "/league/members", "/fixtures", "/contribute", "/status"]);
    await expect(
      page.locator(
        'a[href="/league"], a[href^="/gw/"], a[href^="/moves"], a[href^="/rivals"], a[href="/league/members/squadopt"]',
      ),
    ).toHaveCount(0);
    expect(systemDataRequests).toEqual([]);
  });
}

test("the page applies its one light palette", async ({ page }) => {
  await page.goto("/");

  const palette = await page.locator("body").evaluate((body) => {
    const style = getComputedStyle(body);
    return { background: style.backgroundColor, color: style.color };
  });
  // Page #ECF3E6, ink #10261A.
  expect(palette).toEqual({ background: "rgb(236, 243, 230)", color: "rgb(16, 38, 26)" });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(
    "light",
  );
});

for (const scheme of ["dark", "light"] as const) {
  test(`a stored theme and a ${scheme} system preference leave the light palette in place`, async ({
    page,
  }) => {
    // An older visit may have stored a dark choice; the site has no dark theme any more.
    await page.emulateMedia({ colorScheme: scheme });
    await page.addInitScript(() => localStorage.setItem("squadopt.theme", "dark"));
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");

    await expect(page.locator("html")).not.toHaveAttribute("data-theme");
    const palette = await page.locator("body").evaluate((body) => {
      const style = getComputedStyle(body);
      return { background: style.backgroundColor, color: style.color };
    });
    expect(palette).toEqual({ background: "rgb(236, 243, 230)", color: "rgb(16, 38, 26)" });
    // The stale value is removed on load, so nothing reads it later, and no control
    // offers a theme.
    expect(await page.evaluate(() => localStorage.getItem("squadopt.theme"))).toBeNull();
    await expect(page.getByRole("button", { name: /temaya geç|theme/i })).toHaveCount(0);
  });
}

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

  for (const destination of PAGES) {
    await page.goto(destination.path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth, `${destination.path} overflows at 390px`).toBeLessThanOrEqual(
      dimensions.clientWidth,
    );
  }

  for (const destination of [
    { heading: "Lig Üyeleri", path: "/league/members" },
    { heading: "North Stand Notes", path: "/league/members/35249001?mode=agresif&window=3" },
    // The virtual member shows the week the shipped index names.
    {
      heading: `Oyun haftası ${indexFixture.payload.latest.gameweek}`,
      path: "/league/members/squadopt",
    },
  ]) {
    await page.goto(destination.path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth, `${destination.path} overflows at 390px`).toBeLessThanOrEqual(
      dimensions.clientWidth,
    );
  }
});
