import { execFileSync } from "node:child_process";
import { cp, readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import type { EntryAdvice, LeagueViewEnvelope } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";

const context = JSON.parse(process.env.SQUADOPT_BROWSER_CONTEXT ?? "null");

test("member selections compute, reload uses cache, and a stopped backend leaves the published plan", async ({
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
  await page
    .getByRole("row")
    .filter({ has: page.locator(`a[href="/league/members/${context.entryId}"]`) })
    .getByRole("button", { name: "Bu benim", exact: true })
    .click();
  expect(await (await capabilities).json()).toMatchObject({
    contract_version: "league_capabilities_v1",
    capture_snapshot_id: context.snapshotId,
  });
  await expect(
    page.getByText("Bir haftalık planın hesabı birkaç saniye ile yarım dakika arasında sürer"),
  ).toBeVisible();
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

  // Reload reads the stored answer without another job. Explicit POST is also a hit.
  const postsAfterReload: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(route) && request.method() === "POST") {
      postsAfterReload.push(request.url());
    }
  });
  const hit = page.waitForResponse(
    (response) => response.url().startsWith(route) && response.request().method() === "GET",
  );
  await page.reload();
  const cached = await hit;
  expect(cached.status()).toBe(200);
  expect(await cached.json()).toEqual(answer);
  await expect(page.getByText("Hesap sonucu", { exact: true })).toBeVisible();
  expect(postsAfterReload).toEqual([]);
  const postedCache = page.waitForResponse(
    (response) => response.url().startsWith(route) && response.request().method() === "POST",
  );
  await compute.click();
  const postedAnswer = await postedCache;
  expect(postedAnswer.status()).toBe(200);
  expect(await postedAnswer.json()).toEqual(answer);

  expect(context.rivalId).not.toBe(context.defaultRivalId);
  const jobs = new Set([jobId]);
  for (const selection of [
    {
      query: "top100=20",
      body: { strategy: "saf-puan", window: 1, rival_entry_id: null, top100_weight: 20 },
      payload: { mode: "saf-puan", top100: { weight: 20 } },
    },
    {
      query: `mode=ortak-koru&rival=${context.rivalId}`,
      body: { strategy: "ortak-koru", window: 1, rival_entry_id: context.rivalId },
      payload: { mode: "ortak-koru", rival_entry_id: context.rivalId },
    },
    {
      query: "chip=bboost",
      body: { strategy: "saf-puan", window: 1, rival_entry_id: null, chip: "bboost" },
      payload: { mode: "saf-puan", chip_choice: { chip: "bboost" } },
    },
  ]) {
    await page.goto(`/league/members/${context.entryId}?${selection.query}`);
    await expect(compute).toBeEnabled();
    const queued = page.waitForResponse(
      (response) => response.url().startsWith(route) && response.request().method() === "POST",
    );
    const completed = page.waitForResponse(
      (response) =>
        response.url().startsWith(route) &&
        response.request().method() === "GET" &&
        response.status() === 200,
    );
    await compute.click();
    const submitted = await queued;
    expect(submitted.request().postDataJSON()).toEqual(selection.body);
    expect(submitted.status()).toBe(202);
    const selectedJob = (await submitted.json()).job_id;
    expect(jobs.has(selectedJob)).toBe(false);
    jobs.add(selectedJob);
    const selectedAnswer = (await (await completed).json()) as LeagueViewEnvelope<EntryAdvice>;
    expect(selectedAnswer.payload).toMatchObject({
      ...selection.payload,
      entry_id: context.entryId,
      source_snapshot_id: context.snapshotId,
      window: 1,
    });
    await expect(page.getByText("Hesap sonucu", { exact: true })).toBeVisible();
    await expect(advice).toBeVisible();
    for (const move of selectedAnswer.payload.moves) {
      if (move.player_in) await expect(advice).toContainText(move.player_in.name);
    }
  }
  expect(jobs.size).toBe(4);

  // Last step only: restore the real published plan, then stop this fixture's API tree.
  const baseline = JSON.parse(await readFile(context.baselineCopy, "utf8"));
  await cp(
    context.baselineCopy,
    `node_modules/.cache/${context.buildName}/data/league/advice/${context.entryId}/saf-puan/1.json`,
  );
  const origin = new URL(context.apiOrigin);
  expect(origin.hostname).toBe("127.0.0.1");
  expect(Number(origin.port)).toBeGreaterThan(0);
  expect(Number(origin.port)).not.toBe(8000);
  for (const pid of [context.apiPid, context.fixturePid]) {
    expect(Number.isSafeInteger(pid) && pid > 0).toBe(true);
  }
  const parent =
    process.platform === "win32"
      ? execFileSync(
          "powershell.exe",
          [
            "-NoProfile",
            "-Command",
            `(Get-CimInstance Win32_Process -Filter 'ProcessId=${context.apiPid}').ParentProcessId`,
          ],
          { encoding: "utf8", windowsHide: true },
        )
      : execFileSync("ps", ["-o", "ppid=", "-p", String(context.apiPid)], { encoding: "utf8" });
  expect(Number(parent.trim())).toBe(context.fixturePid);
  if (process.platform === "win32") {
    // The venv launcher has an interpreter child. Both must stop, exactly as teardown does.
    execFileSync("taskkill", ["/PID", String(context.apiPid), "/T", "/F"], { windowsHide: true });
  } else {
    process.kill(context.apiPid, "SIGTERM");
  }
  await expect
    .poll(async () => {
      try {
        await page.request.get(`${context.apiOrigin}/ready`, { timeout: 1_000 });
        return false;
      } catch {
        return true;
      }
    })
    .toBe(true);
  await page.goto(`/league/members/${context.entryId}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Browser smoke team");
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(
    page.getByText(
      "Hesaplama servisine şu an ulaşılamıyor. Yayınlanmış planlar her zamanki gibi aşağıda.",
    ),
  ).toBeVisible();
  await expect(advice).toBeVisible();
  await expect(advice).toContainText(baseline.payload.captain.name);
  await expect(page.getByText("Hesap sonucu", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Hesapla", exact: true }).click();
  await expect(
    page.getByText(MESSAGES.tr.leagueMembers.computeStaticFallback, { exact: false }),
  ).toBeVisible();
  await expect(advice).toContainText(baseline.payload.captain.name);
  await expect(page.getByText("Hesap sonucu", { exact: true })).toHaveCount(0);
});
