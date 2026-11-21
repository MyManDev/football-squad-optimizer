import { createRequire } from "node:module";
import { stdin } from "node:process";

const requireWeb = createRequire(
  new URL("../../../web/package.json", import.meta.url),
);
const { chromium } = requireWeb("playwright");
let raw = "";
for await (const chunk of stdin) raw += chunk;
const input = JSON.parse(raw);
const origin = new URL(input.origin);
if (
  origin.protocol !== "http:" ||
  origin.hostname !== "127.0.0.1" ||
  input.window !== 1
) {
  throw new Error("A loopback HTTP origin and a one-week draft are required.");
}
const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
});
try {
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1280, height: 900 },
  });
  const blocked = [];
  context.on("request", (request) => {
    const url = new URL(request.url());
    if (
      /^https?:$/.test(url.protocol) &&
      (url.origin !== origin.origin ||
        /^\/api\/v1\/llmopt\/(prompt|check)$/.test(url.pathname))
    ) {
      blocked.push(url.pathname);
    }
  });
  const page = await context.newPage();
  // Network interception disables the browser's HTTP cache. Deny other origins in Chromium itself.
  const session = await context.newCDPSession(page);
  await session.send("Network.enable");
  await session.send("Network.setBlockedURLs", {
    urlPatterns: [
      { urlPattern: origin.origin + "/api/v1/llmopt/prompt", block: true },
      { urlPattern: origin.origin + "/api/v1/llmopt/check", block: true },
      { urlPattern: origin.origin + "/*", block: false },
    ],
    urls: ["http://*", "https://*"],
  });
  let deviceWorkers = 0;
  page.on("worker", (worker) => {
    if (
      /\/deviceSolver\.worker-[^/]+\.js$/.test(new URL(worker.url()).pathname)
    )
      deviceWorkers++;
  });
  page.setDefaultTimeout(30_000);
  await page.clock.setFixedTime(new Date(input.asOfUtc));
  await page.addInitScript(
    ({
      origin,
      leagueId,
      entryId,
      managerName,
      teamName,
      leagueName,
      draft,
      deadline,
    }) => {
      localStorage.setItem("squadopt.language", "en");
      localStorage.setItem("squadopt.league", String(leagueId));
      sessionStorage.setItem(
        "squadopt.member",
        JSON.stringify({
          leagueId,
          entryId,
          managerName,
          teamName,
          leagueName,
        }),
      );
      sessionStorage.setItem("squadopt.openingShown", "1");
      const key =
        "squadopt.llmopt:" + JSON.stringify([origin, false, leagueId, entryId]);
      if (!sessionStorage.getItem(key))
        sessionStorage.setItem(key, JSON.stringify({ deadline, draft }));

      // On reload performance.now() starts at navigation. Cold runs start at the actual click.
      const warm = sessionStorage.getItem("measurement.warmReload") === "1";
      sessionStorage.removeItem("measurement.warmReload");
      const sample = { start: warm ? 0 : null, base: null, combined: null };
      window.planSample = sample;
      document.addEventListener(
        "click",
        (event) => {
          if (
            sample.start === null &&
            event.target.closest("button")?.textContent.trim() ===
              "Compute plans"
          ) {
            sample.start = performance.now();
          }
        },
        true,
      );
      function frame() {
        if (sample.start !== null) {
          for (const card of document.querySelectorAll(
            "article[data-plan-ready]",
          )) {
            const heading = card.querySelector("h3");
            const title = heading?.textContent.trim();
            if (title === "Base plan" && !sample.base) {
              // Follow the first calculated value, which is absent from the pending card.
              const value = card.querySelector("dl dd");
              if (!value?.textContent.trim()) continue;
              const rect = value.getBoundingClientRect();
              if (rect.top < 0 || rect.bottom > innerHeight)
                value.scrollIntoView({
                  block: "center",
                  behavior: "instant",
                });
              const visible = value.getBoundingClientRect();
              if (
                visible.height > 0 &&
                visible.top >= 0 &&
                visible.bottom <= innerHeight &&
                visible.width > 0 &&
                visible.left >= 0 &&
                visible.right <= innerWidth &&
                value.checkVisibility({
                  opacityProperty: true,
                  visibilityProperty: true,
                })
              ) {
                sample.base = {
                  ms: performance.now(),
                  decision: card.dataset.transferDecision,
                };
              }
            }
            if (
              title === "Plan with all preferences" &&
              !sample.combined &&
              card.getBoundingClientRect().height > 0
            ) {
              sample.combined = {
                ms: performance.now(),
                decision: card.dataset.transferDecision,
              };
            }
          }
        }
        if (!sample.base || !sample.combined) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    },
    input,
  );
  const result = {};
  for (const pass of ["cold", "warm"]) {
    const workersBefore = deviceWorkers;
    const boundary = await context.request.post(
      new URL("/__measurement/pass/" + pass, origin).href,
    );
    if (!boundary.ok())
      throw new Error(
        "The local measurement segment could not start: " + boundary.status(),
      );
    try {
      if (pass === "cold") {
        await page.goto(
          new URL(
            "/league/" +
              input.leagueId +
              "/members/" +
              input.entryId +
              "/llmopt",
            origin,
          ).href,
        );
        await page
          .getByRole("button", { name: "Compute plans", exact: true })
          .click();
      } else {
        await page.evaluate(() =>
          sessionStorage.setItem("measurement.warmReload", "1"),
        );
        await page.reload();
      }
      await page.waitForFunction(
        () => window.planSample?.base && window.planSample?.combined,
        undefined,
        { timeout: 150_000 },
      );
    } catch (error) {
      const observed = await page.evaluate(() => ({
        sample: window.planSample,
        headings: [
          ...document.querySelectorAll("article[data-plan-ready] h3"),
        ].map((h) => h.textContent),
      }));
      throw new Error(
        input.case +
          " " +
          pass +
          ": " +
          JSON.stringify(observed) +
          " " +
          (await page.locator("body").innerText({ timeout: 3000 })).slice(
            -2000,
          ),
        { cause: error },
      );
    }
    result[pass] = await page.evaluate(() => {
      const { start, base, combined } = window.planSample;
      return {
        first_visible_seconds: (base.ms - start) / 1000,
        total_seconds: (Math.max(base.ms, combined.ms) - start) / 1000,
        base_decision: JSON.parse(base.decision),
        combined_decision: JSON.parse(combined.decision),
      };
    });
    result[pass].device_workers = deviceWorkers - workersBefore;
  }
  if (blocked.length)
    throw new Error("Unexpected network paths: " + blocked.join(", "));
  for (const part of ["base_decision", "combined_decision"]) {
    if (
      JSON.stringify(result.cold[part]) !== JSON.stringify(result.warm[part])
    ) {
      throw new Error("The warm page restored a different " + part);
    }
  }
  process.stdout.write(JSON.stringify(result) + "\n");
} finally {
  await browser.close();
}
