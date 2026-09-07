import { cp } from "node:fs/promises";
import { expect, test } from "@playwright/test";

import type { EntryAdvice, LeagueViewEnvelope } from "../src/features/league/types";

const context = JSON.parse(process.env.SQUADOPT_BROWSER_CONTEXT ?? "null");

test("a browser computes through the worker, then reads the same answer from cache", async ({
  page,
}) => {
  // These are the Python fixture's captured squad and member documents. No route,
  // including the API, is intercepted; Chromium enforces the cross-origin request.
  await cp(context.siteRoot, `node_modules/.cache/${context.buildName}/data`, {
    recursive: true,
  });
  const route =
    `${context.apiOrigin}/api/v1/leagues/${context.leagueId}` +
    `/entries/${context.entryId}/advice`;
  const absent = await page.request.get(
    `${context.webOrigin}/data/league/advice/${context.entryId}/saf-puan/1.json`,
  );
  expect(await absent.text()).not.toContain('"contract_version"');

  await page.goto(`/league/members/${context.entryId}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Browser smoke team");
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(page.getByText("Bu mod ve ufuk bu yayın için hesaplanmadı.")).toBeVisible();
  const compute = page.getByRole("button", { name: "Hesapla", exact: true });
  const accepted = page.waitForResponse(
    (response) => response.url().startsWith(route) && response.request().method() === "POST",
  );
  const served = page.waitForResponse(
    (response) =>
      response.url().startsWith(route) &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
  await compute.click();
  const post = await accepted;
  expect(post.status()).toBe(202);
  expect(post.request().postDataJSON()).toEqual({
    strategy: "saf-puan",
    window: 1,
    rival_entry_id: null,
  });
  expect(post.headers()["access-control-allow-origin"]).toBe(context.webOrigin);
  const { job_id: jobId } = await post.json();
  expect(jobId).toBeTruthy();
  await expect(compute).toBeDisabled();

  const answer = (await (await served).json()) as LeagueViewEnvelope<EntryAdvice>;
  expect(answer.payload).toMatchObject({
    entry_id: context.entryId,
    league_id: context.leagueId,
    season: context.season,
    gameweek: context.gameweek,
    mode: "saf-puan",
    window: 1,
    source_snapshot_id: context.snapshotId,
  });
  const job = await page.request.get(`${context.apiOrigin}/api/v1/advice-jobs/${jobId}`);
  expect(await job.json()).toMatchObject({ job_id: jobId, status: "completed" });
  await expect(page.getByText("Plan hazır", { exact: true })).toBeVisible();
  await expect(page.getByText("Hesap sonucu", { exact: true })).toBeVisible();
  await expect(page.getByText(context.snapshotId, { exact: false })).toBeVisible();
  const advice = page.locator('[aria-labelledby="entry-advice-title"]');
  expect(["OPTIMAL", "FEASIBLE"]).toContain(answer.payload.solver_status);
  for (const move of answer.payload.moves) {
    if (move.player_in) await expect(advice).toContainText(move.player_in.name);
    if (move.player_out) await expect(advice).toContainText(move.player_out.name);
  }

  // The one-job worker exits after its first solve. A reload and another request
  // must still succeed from the stored answer, without another queued computation.
  await page.reload();
  const hit = page.waitForResponse(
    (response) => response.url().startsWith(route) && response.request().method() === "POST",
  );
  await compute.click();
  const cached = await hit;
  expect(cached.status()).toBe(200);
  expect(await cached.json()).toEqual(answer);
  await expect(page.getByText("Hesap sonucu", { exact: true })).toBeVisible();
});
