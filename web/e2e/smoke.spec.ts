import { expect, test } from "@playwright/test";

test("squad shows the latest decision", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Oyun haftası/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(page.getByText(/Bu sayılar neyi söylemiyor/)).toBeVisible();
});

test("suggested moves states the opening week honestly", async ({ page }) => {
  await page.goto("/moves");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Önerilen Hamleler");
  await expect(page.getByText(/Açılış kadrosu — yapılacak transfer yok/)).toBeVisible();
});

test("rivals shows the projections and says why there is no rival yet", async ({ page }) => {
  await page.goto("/rivals");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Rakip Analizi");
  await expect(page.getByRole("table", { name: /Projeksiyon havuzu, FWD/ })).toBeVisible();
  await expect(page.getByText(/Bu karara karşı puanlanmış bir rakip yok/)).toBeVisible();
});

test("league shows the season and the cumulative chart", async ({ page }) => {
  await page.goto("/league");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");
  // One decision so far: the chart states why it is not drawn yet.
  await expect(page.getByText(/Tek oyun haftası bir noktadır, çizgi değildir/)).toBeVisible();
  // The league comparison is real data from the capture, with nothing scored yet.
  await expect(page.getByText(/No gameweek has been scored yet/)).toBeVisible();
  await expect(page.getByText(/Bu kadronun ne kadarı şablon/)).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
});

test("status is reachable from the footer", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Operasyon Durumu" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Durum");
});

test("language selection switches the full frame and persists across routes", async ({ page }) => {
  await page.goto("/moves?mode=garantici&window=3");
  await page.getByRole("button", { name: /EN.*English/ }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Suggested Moves");
  await expect(page.getByRole("radio", { name: /3 weeks/ })).toBeChecked();
  await expect(page).toHaveURL(/mode=garantici&window=3/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  await page.getByRole("link", { name: "Analysis" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Analysis Center");
  await page.reload();
  await expect(page.getByRole("link", { name: "Suggested Moves" })).toBeVisible();
});
