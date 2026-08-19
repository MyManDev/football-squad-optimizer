import { expect, test } from "@playwright/test";

test("squad shows the latest decision", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Gameweek/);
  await expect(page.getByRole("list", { name: "Starting eleven by position" })).toBeVisible();
  await expect(page.getByText(/What these numbers do not say/)).toBeVisible();
});

test("suggested moves states the opening week honestly", async ({ page }) => {
  await page.goto("/moves");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Suggested moves");
  await expect(page.getByText(/Opening squad — no transfers to make/)).toBeVisible();
});

test("rivals shows the projections and says why there is no rival yet", async ({ page }) => {
  await page.goto("/rivals");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Rival analysis");
  await expect(page.getByRole("table", { name: /Projected pool, FWD/ })).toBeVisible();
  await expect(page.getByText(/No rival was scored against this decision/)).toBeVisible();
});

test("league shows the season and the cumulative chart", async ({ page }) => {
  await page.goto("/league");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("League analysis");
  // One decision so far: the chart states why it is not drawn yet.
  await expect(page.getByText(/One gameweek is a point, not a line/)).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
});

test("status is reachable from the footer", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Operations status" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Status");
});
