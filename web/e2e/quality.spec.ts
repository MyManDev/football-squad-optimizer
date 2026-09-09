import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";

const PAGES = [
  { heading: "Ligini bul", path: "/" },
  { heading: "Lig Üyeleri", path: "/league/members" },
  { heading: /Oyun haftası/, path: "/gw/2026-27/1" },
  { heading: "Önerilen Hamleler", path: "/moves" },
  { heading: "Rakip Analizi", path: "/rivals" },
  { heading: "Lig Analizi", path: "/league" },
  { heading: "Analiz Merkezi", path: "/analysis" },
] as const;

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("visitor navigation reaches league entry and analysis without browser errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  for (const destination of [
    { link: "Lig", heading: "Ligini bul", path: "/" },
    { link: "Analiz", heading: "Analiz Merkezi", path: "/analysis" },
  ]) {
    await page.getByRole("link", { name: destination.link, exact: true }).click();
    await expect(page).toHaveURL(destination.path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
  }

  expect(errors).toEqual([]);
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
    expect(
      await page
        .locator("header nav a, footer a")
        .evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
    ).toEqual(["/", "/analysis", "/status"]);
    await expect(
      page.locator(
        'a[href="/league"], a[href^="/gw/"], a[href^="/moves"], a[href^="/rivals"], a[href="/league/members/squadopt"]',
      ),
    ).toHaveCount(0);
    expect(systemDataRequests).toEqual([]);
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`${theme} theme applies its complete root palette`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.theme", value), theme);
    await page.goto("/");

    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const palette = await page.locator("body").evaluate((body) => {
      const style = getComputedStyle(body);
      return { background: style.backgroundColor, color: style.color };
    });
    expect(palette).toEqual(
      theme === "dark"
        ? { background: "rgb(14, 31, 24)", color: "rgb(238, 244, 239)" }
        : { background: "rgb(244, 246, 242)", color: "rgb(18, 36, 28)" },
    );
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
    { heading: "Oyun haftası 1", path: "/league/members/squadopt" },
  ] as const) {
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
