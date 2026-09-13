import { describe, expect, it } from "vitest";

import { SMOKE_CHECKS, smokeDeployment } from "./smoke-deployment.mjs";

const BASE = "https://squadopt.pages.dev";
const SHELL = '<!doctype html><title>SquadOpt</title><div id="root"></div>';
const ABSENT = SMOKE_CHECKS.find((check) => check.kind === "absent").path;
const MEMBERS = SMOKE_CHECKS.find((check) => check.requires).path;

function responseFor(url, cacheControl = "public, max-age=0, must-revalidate") {
  if (url.pathname === ABSENT) {
    return {
      ok: false,
      status: 404,
      headers: { get: () => "no-store" },
      text: async () => "<!doctype html><title>404</title>",
    };
  }
  const json = url.pathname.endsWith(".json");
  return {
    ok: true,
    status: 200,
    headers: { get: () => (json ? cacheControl : "text/html") },
    json: async () => ({ version: 1, payload: { members: [{ entry_id: 5662073 }] } }),
    text: async () => SHELL,
  };
}

function servedInstead(path, response) {
  return async (url) => (url.pathname === path ? response : responseFor(url));
}

describe("deployment smoke", () => {
  it("checks every SPA route, the published documents and one absent document", async () => {
    const paths = [];
    await smokeDeployment(BASE, {
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
      smokeDeployment(BASE, {
        attempts: 1,
        fetchImpl: async (url) => responseFor(url, "public, max-age=3600"),
      }),
    ).rejects.toThrow("Deployment smoke failed");
  });

  it("rejects an absent document served as the application shell", async () => {
    await expect(
      smokeDeployment(BASE, {
        attempts: 1,
        fetchImpl: servedInstead(ABSENT, {
          ok: true,
          status: 200,
          headers: { get: () => "text/html" },
          text: async () => SHELL,
        }),
      }),
    ).rejects.toThrow(`Deployment smoke failed for ${BASE}${ABSENT}`);
  });

  it("rejects an absent document that answers anything but 404", async () => {
    await expect(
      smokeDeployment(BASE, {
        attempts: 1,
        fetchImpl: servedInstead(ABSENT, {
          ok: false,
          status: 500,
          headers: { get: () => "no-store" },
          text: async () => "",
        }),
      }),
    ).rejects.toThrow(`Deployment smoke failed for ${BASE}${ABSENT}`);
  });

  it("rejects a members document that lists nobody", async () => {
    await expect(
      smokeDeployment(BASE, {
        attempts: 1,
        fetchImpl: servedInstead(MEMBERS, {
          ok: true,
          status: 200,
          headers: { get: () => "public, max-age=0, must-revalidate" },
          json: async () => ({ payload: { members: [] } }),
        }),
      }),
    ).rejects.toThrow(`Deployment smoke failed for ${BASE}${MEMBERS}`);
  });

  it("rejects credentials in the deployment URL", async () => {
    await expect(
      smokeDeployment("https://user:password@squadopt.pages.dev", { attempts: 1 }),
    ).rejects.toThrow("without credentials");
  });
});
