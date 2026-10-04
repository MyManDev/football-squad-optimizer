import { describe, expect, it } from "vitest";

import {
  ABSENT_ASSET,
  DIRECTORY,
  LEGACY_TREE,
  SMOKE_CHECKS,
  smokeDeployment,
  treeChecks,
} from "./smoke-deployment.mjs";

const BASE = "https://squadopt.pages.dev";
const SHELL =
  '<!doctype html><title>SquadOpt</title><script type="module" src="/assets/index-AbCd1234.js">' +
  '</script><link rel="stylesheet" href="/assets/index-EfGh5678.css"><div id="root"></div>';
// What the shell reaches: the entry, its stylesheet, a lazy page, the page's worker and a font.
const ASSETS = {
  "/assets/index-AbCd1234.js": [
    "text/javascript",
    'import("./Page-IjKl9012.js");m.f=["assets/Page-IjKl9012.js","assets/Page-MnOp3456.css"]',
  ],
  "/assets/index-EfGh5678.css": ["text/css", "body{font:url(/assets/font-QrSt7890.woff2)}"],
  "/assets/Page-IjKl9012.js": [
    "text/javascript",
    "new Worker(new URL(`/assets/solver.worker-Uv-Wx123.js`, import.meta.url))",
  ],
  "/assets/Page-MnOp3456.css": ["text/css", "main{}"],
  "/assets/solver.worker-Uv-Wx123.js": ["text/javascript", "self.onmessage=()=>{}"],
  "/assets/font-QrSt7890.woff2": ["font/woff2", ""],
};
// A site from before the directory: the legacy tree alone.
const LEGACY = treeChecks({ leagueId: null, path: LEGACY_TREE });
const ABSENT = LEGACY.find((check) => check.kind === "absent").path;
const MEMBERS = LEGACY.find((check) => check.requires).path;

function responseFor(url, cacheControl = "public, max-age=0, must-revalidate") {
  if (url.pathname === DIRECTORY || url.pathname === ABSENT || url.pathname === ABSENT_ASSET) {
    return {
      ok: false,
      status: 404,
      headers: { get: () => "no-store" },
      text: async () => "<!doctype html><title>404</title>",
    };
  }
  if (url.pathname in ASSETS) {
    const [type, body] = ASSETS[url.pathname];
    return {
      ok: true,
      status: 200,
      headers: {
        get: (name) => (name === "content-type" ? type : "public, max-age=31536000, immutable"),
      },
      text: async () => body,
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
    const checked = [
      DIRECTORY,
      ...SMOKE_CHECKS.map((check) => check.path),
      ...LEGACY.map((check) => check.path),
    ];
    expect(paths.slice(0, checked.length)).toEqual(checked);
    // The shell once more, then every asset it reaches, through the entry, the lazy page
    // and its worker, each once.
    const rest = paths.slice(checked.length);
    expect(rest[0]).toBe("/");
    expect(rest.slice(1).sort()).toEqual(Object.keys(ASSETS).sort());
  });

  it("reads the league directory again after a failure, as every other check does", async () => {
    let failures = 1;
    const paths = [];
    await smokeDeployment(BASE, {
      attempts: 2,
      sleep: async () => {},
      fetchImpl: async (url) => {
        paths.push(url.pathname);
        if (url.pathname === DIRECTORY && failures-- > 0) {
          return { ok: false, status: 522, headers: { get: () => "" } };
        }
        return responseFor(url);
      },
    });
    expect(paths.filter((path) => path === DIRECTORY)).toHaveLength(2);
  });

  it.each(Object.keys(ASSETS))("rejects %s served as the HTML shell", async (asset) => {
    await expect(
      smokeDeployment(BASE, {
        attempts: 1,
        fetchImpl: servedInstead(asset, {
          ok: true,
          status: 200,
          headers: { get: (name) => (name === "content-type" ? "text/html" : "immutable") },
          text: async () => SHELL,
        }),
      }),
    ).rejects.toThrow(`Deployment smoke failed for ${BASE}${asset}`);
  });

  it("rejects a missing asset that answers the shell or can be cached", async () => {
    for (const response of [
      { ok: true, status: 200, headers: { get: () => "text/html" }, text: async () => SHELL },
      {
        ok: false,
        status: 404,
        headers: { get: () => "public, max-age=31536000, immutable" },
        text: async () => "<!doctype html><title>404</title>",
      },
    ]) {
      await expect(
        smokeDeployment(BASE, { attempts: 1, fetchImpl: servedInstead(ABSENT_ASSET, response) }),
      ).rejects.toThrow(`Deployment smoke failed for ${BASE}${ABSENT_ASSET}`);
    }
  });

  it("checks every tree a published directory lists, by its own path and address", async () => {
    const directory = {
      contract_version: "league_directory_v1",
      payload: {
        leagues: [
          { league_id: 352490, path: "leagues/352490" },
          { league_id: 7, path: "leagues/7" },
        ],
      },
    };
    const paths = [];
    await smokeDeployment(BASE, {
      attempts: 1,
      fetchImpl: async (url) => {
        paths.push(url.pathname);
        if (url.pathname === DIRECTORY) {
          return {
            ok: true,
            status: 200,
            headers: { get: () => "public, max-age=0, must-revalidate" },
            json: async () => directory,
          };
        }
        if (url.pathname.endsWith("/entries/0.json")) return responseFor(new URL(ABSENT, BASE));
        return responseFor(url);
      },
    });
    const expected = [
      DIRECTORY,
      ...SMOKE_CHECKS.map((check) => check.path),
      "/league/352490/members/0",
      "/data/leagues/352490/members.json",
      "/data/leagues/352490/entries/0.json",
      "/league/7/members/0",
      "/data/leagues/7/members.json",
      "/data/leagues/7/entries/0.json",
    ];
    expect(paths.slice(0, expected.length)).toEqual(expected);
    expect(paths).not.toContain(MEMBERS);
  });

  it("fails on a directory that answers anything but 200 or 404, or lists no league", async () => {
    for (const [status, json] of [
      [500, async () => ({})],
      [200, async () => ({ payload: { leagues: [] } })],
      [200, async () => ({ payload: { leagues: [{ path: 7 }] } })],
    ]) {
      await expect(
        smokeDeployment(BASE, {
          attempts: 1,
          fetchImpl: async (url) =>
            url.pathname === DIRECTORY
              ? { ok: status === 200, status, headers: { get: () => "" }, json }
              : responseFor(url),
        }),
      ).rejects.toThrow("the league directory");
    }
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
