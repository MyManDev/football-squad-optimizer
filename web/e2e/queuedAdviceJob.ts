import { expect, type Locator, type Page } from "@playwright/test";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";

/** Observe the actual HTTP reply for this job, including its id and state. */
async function jobStatus(page: Page, jobId: string, status: "queued" | "completed") {
  const response = await page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === `/api/v1/advice-jobs/${jobId}`,
  );
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ job_id: jobId, status });
}

export async function startQueuedJob(
  page: Page,
  jobId: string,
  compute: Locator,
  language: "tr" | "en",
) {
  const [accepted] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname.endsWith("/advice") &&
        r.status() === 202,
    ),
    compute.click(),
  ]);
  expect(await accepted.json()).toMatchObject({ job_id: jobId, status: "queued" });
  await expect(
    page.getByRole("button", { name: LLMOPT_COPY[language].computing, exact: true }),
  ).toBeVisible();
  await Promise.all([jobStatus(page, jobId, "queued"), page.clock.fastForward(2_000)]);
}

export async function reloadQueuedJob(page: Page, jobId: string, language: "tr" | "en" = "en") {
  const queued = page
    .waitForEvent("framenavigated", (frame) => frame === page.mainFrame())
    .then(() => jobStatus(page, jobId, "queued"));
  await Promise.all([queued, page.reload()]);
  await expect(
    page.getByRole("button", { name: LLMOPT_COPY[language].computing, exact: true }),
  ).toBeVisible();
}

/** Advance the full poll interval after the resumed job's queued reply has arrived. */
export async function observeCompletedJob(page: Page, jobId: string) {
  await Promise.all([jobStatus(page, jobId, "completed"), page.clock.fastForward(2_000)]);
}
