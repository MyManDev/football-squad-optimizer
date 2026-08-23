import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";

const PAGES = [
  { link: "Kadro", heading: /Oyun haftası/, path: "/" },
  { link: "Önerilen hamleler", heading: "Önerilen hamleler", path: "/moves" },
  { link: "Rakipler", heading: "Rakip analizi", path: "/rivals" },
  { link: "Lig", heading: "Lig analizi", path: "/league" },
  { link: "Analiz", heading: "Analiz Merkezi", path: "/analysis" },
] as const;

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("the five primary pages are navigable without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  for (const destination of PAGES) {
    await page.getByRole("link", { name: destination.link, exact: true }).click();
    await expect(page).toHaveURL(destination.path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(destination.heading);
  }

  expect(errors).toEqual([]);
});

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
    { heading: "Lig üyeleri", path: "/league/members" },
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
