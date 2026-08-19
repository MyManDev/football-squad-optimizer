import { expect, test } from "@playwright/test";

test("this week shows the latest decision", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Gameweek/);
  await expect(page.getByRole("list", { name: "Starting eleven by position" })).toBeVisible();
  await expect(page.getByText(/What these numbers do not say/)).toBeVisible();
});

test("history lists the ledger", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("History");
  await expect(page.getByRole("table")).toBeVisible();
});

test("status shows what the tick would do", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Status");
});
