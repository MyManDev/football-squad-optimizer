import { describe, expect, it } from "vitest";

import { SMOKE_CHECKS, smokeDeployment } from "./smoke-deployment.mjs";

function responseFor(url, cacheControl = "public, max-age=0, must-revalidate") {
  const json = url.pathname.endsWith(".json");
  return {
    ok: true,
    status: 200,
    headers: { get: () => (json ? cacheControl : "text/html") },
    json: async () => ({ version: 1 }),
    text: async () => "<!doctype html><title>SquadOpt</title>",
  };
}

describe("deployment smoke", () => {
  it("checks all six SPA routes and the published JSON", async () => {
    const paths = [];
    await smokeDeployment("https://squadopt.pages.dev", {
      attempts: 1,
      fetchImpl: async (url) => {
        paths.push(url.pathname);
        return responseFor(url);
      },
    });
    expect(paths).toEqual(SMOKE_CHECKS.map((check) => check.path));
  });

  it("rejects stale-cache policy on published JSON", async () => {
    await expect(
      smokeDeployment("https://squadopt.pages.dev", {
        attempts: 1,
        fetchImpl: async (url) => responseFor(url, "public, max-age=3600"),
      }),
    ).rejects.toThrow("Deployment smoke failed");
  });

  it("rejects credentials in the deployment URL", async () => {
    await expect(
      smokeDeployment("https://user:password@squadopt.pages.dev", { attempts: 1 }),
    ).rejects.toThrow("without credentials");
  });
});
