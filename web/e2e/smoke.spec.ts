import { expect, test } from "@playwright/test";

test("this week shows the latest decision", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Gameweek/);
  await expect(page.getByRole("list", { name: "Starting eleven by position" })).toBeVisible();
  await expect(page.getByText(/What these numbers do not say/)).toBeVisible();
});

test("history lists the ledger and draws the cumulative chart", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("History");
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("img", { name: /Cumulative projected/ })).toBeVisible();
});

test("why shows the ranked pool with the squad marked", async ({ page }) => {
  await page.goto("/why/2026-27/1");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Why these players");
  await expect(page.getByRole("table", { name: /Projected pool, FWD/ })).toBeVisible();
  await expect(page.getByText("XI").first()).toBeVisible();
});

test("status shows what the tick would do", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Status");
});
