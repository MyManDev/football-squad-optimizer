import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";

// #1135 part 3: the squad card is drawn on the device from the plan on screen and saved as a
// PNG; making it sends no request.
test("the squad card is drawn on the device and saved as an image", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await installLeagueMocks(page);
  await page.goto("/league/352490/members/35249001");

  const tool = page.locator("main details").filter({
    has: page.locator("summary", { hasText: "Kadro kartı" }),
  });
  await tool.locator(":scope > summary").click();
  await tool.getByRole("checkbox", { name: "Beklenen puan" }).check();
  await tool.getByRole("checkbox", { name: "Takım ve menajer" }).uncheck();

  const requests: string[] = [];
  page.on("request", (request) => {
    if (/^https?:/.test(request.url())) requests.push(request.url());
  });
  await tool.getByRole("button", { name: "Kartı oluştur" }).click();

  // The card takes the focus when it is ready, and the tool says so.
  const preview = tool.getByRole("img", { name: /hafta kadro kartı$/ });
  await expect(preview).toBeVisible();
  await expect(preview).toBeFocused();
  await expect(tool.getByRole("status")).toHaveText("Kart hazır.");
  const size = await preview.evaluate((image: HTMLImageElement) => ({
    width: image.naturalWidth,
    height: image.naturalHeight,
  }));
  expect(size.width).toBe(1080);
  expect(size.height).toBeGreaterThan(400);

  const download = page.waitForEvent("download");
  await tool.getByRole("link", { name: "Kaydet" }).click();
  expect((await download).suggestedFilename()).toMatch(/^squadopt-gw\d+\.png$/);

  expect(requests).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
