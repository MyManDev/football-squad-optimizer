import { cp } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

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

  await page.goto("/");
  const leagueRequests: string[] = [];
  page.on("request", (request) => {
    // The shell reads the fixture list on every page, whenever its chunk lands; it is not
    // a league lookup, and counting it made this assertion depend on timing.
    if (request.url().endsWith("/data/fixtures.json")) return;
    if (["fetch", "xhr"].includes(request.resourceType())) leagueRequests.push(request.url());
  });
  const leagueField = page.getByLabel("Lig numarası");
  const findLeague = page.getByRole("button", { name: "Ligi bul", exact: true });
  await leagueField.fill("123");
  await findLeague.click();
  await expect(page.getByRole("status")).toHaveText(
    "Şimdilik yalnız 352490 numaralı lig destekleniyor.",
  );
  expect(leagueRequests).toEqual([]);
  await leagueField.fill(String(context.leagueId));
  await findLeague.click();
  await expect(page).toHaveURL("/league/members");
  // The member page asks the service what it computes, once, and says about how long.
  const capabilities = page.waitForResponse(
    (response) =>
      response.url() === `${context.apiOrigin}/api/v1/leagues/${context.leagueId}/capabilities`,
  );
  await page.getByRole("button", { name: "Bu benim", exact: true }).click();
  expect(await (await capabilities).json()).toMatchObject({
    contract_version: "league_capabilities_v1",
    capture_snapshot_id: context.snapshotId,
  });
  await expect(page.getByText("Bir haftalık planın hesabı birkaç saniye sürer.")).toBeVisible();
  await expect(page).toHaveURL(`/league/members/${context.entryId}`);
  expect(await page.evaluate(() => localStorage.getItem("squadopt.viewer"))).toBeNull();
  await expect(page.getByRole("button", { name: "Seçimi Kaldır" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Browser smoke team");
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(page.getByText("Listelenen öneri dosyası bulunamadı.")).toBeVisible();
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
  expect(post.request().headers()["idempotency-key"]).toMatch(
    /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/,
  );
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
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
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

test("a bundle built with an origin is the static page when the service is down", async ({
  page,
}) => {
  await cp(context.siteRoot, `node_modules/.cache/${context.buildName}/data`, {
    recursive: true,
  });
  // The service is unreachable for this page only: every call to its origin fails.
  await page.route(`${context.apiOrigin}/**`, (route) => route.abort("connectionrefused"));
  await page.goto(`/league/members/${context.entryId}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Browser smoke team");
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(
    page.getByText(
      "Hesaplama servisine şu an ulaşılamıyor. Yayınlanmış planlar her zamanki gibi aşağıda.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Hesapla", exact: true }).click();
  await expect(
    page.getByText(
      "Hesaplama servisine ulaşılamadı. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    ),
  ).toBeVisible();
});
