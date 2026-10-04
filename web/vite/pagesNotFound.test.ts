// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { preview, type PreviewServer } from "vite";

import { closestNotFound, pagesNotFound, sitePath } from "./pagesNotFound.ts";

let root: string;

function put(path: string, body: string) {
  mkdirSync(join(root, path, ".."), { recursive: true });
  writeFileSync(join(root, path), body);
}

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), "pages-not-found-"));
  put("index.html", "<!doctype html><title>shell</title>");
  put("data/404.html", "<!doctype html><p>No document is published at this address.</p>");
  put("data/league/members.json", "{}");
  put("data/nested/404.html", "<!doctype html><p>nested</p>");
  put("assets/404.html", "<!doctype html><p>No asset is published at this address.</p>");
  put("assets/index-abcdefgh.js", "export {};");
});

afterAll(() => rmSync(root, { recursive: true, force: true }));

describe("closestNotFound", () => {
  it("answers a missing document with the closest 404.html up the tree", () => {
    expect(closestNotFound(root, "/data/leagues.json")).toBe(join(root, "data", "404.html"));
    expect(closestNotFound(root, "/data/league/entries/0.json")).toBe(
      join(root, "data", "404.html"),
    );
    expect(closestNotFound(root, "/data/nested/deeper/x.json")).toBe(
      join(root, "data", "nested", "404.html"),
    );
    expect(closestNotFound(root, "/assets/missing-abcdefgh.js")).toBe(
      join(root, "assets", "404.html"),
    );
  });

  it("leaves existing files, client-side routes and paths outside the root alone", () => {
    expect(closestNotFound(root, "/data/league/members.json")).toBeNull();
    expect(closestNotFound(root, "/assets/index-abcdefgh.js")).toBeNull();
    expect(closestNotFound(root, "/data/league")).toBeNull();
    expect(closestNotFound(root, "/league/352490/members/1")).toBeNull();
    expect(closestNotFound(root, "/")).toBeNull();
    expect(closestNotFound(root, "/../outside.json")).toBeNull();
  });
});

describe("sitePath", () => {
  it("reads the decoded path under the site base", () => {
    expect(sitePath("/data/leagues.json?x=1", "/")).toBe("/data/leagues.json");
    expect(sitePath("/sub/data/a%20b.json", "/sub/")).toBe("/data/a b.json");
    expect(sitePath("/other/data/x.json", "/sub/")).toBeNull();
    expect(sitePath("/data/%E0%A4%A.json", "/")).toBeNull();
  });
});

describe("the preview server", () => {
  let server: PreviewServer;
  let origin: string;

  beforeAll(async () => {
    server = await preview({
      configFile: false,
      root,
      logLevel: "silent",
      build: { outDir: root },
      preview: { host: "127.0.0.1", port: 0, strictPort: false },
      plugins: [pagesNotFound()],
    });
    const address = server.httpServer.address();
    if (address === null || typeof address === "string") throw new Error("no port");
    origin = `http://127.0.0.1:${address.port}`;
  });

  afterAll(async () => {
    await server.close();
  });

  it("answers a missing document 404 with its 404.html, as Pages does", async () => {
    const response = await fetch(`${origin}/data/leagues.json`);
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).toContain("No document is published");
  });

  it("answers a missing asset 404, never with the shell", async () => {
    const response = await fetch(`${origin}/assets/missing-abcdefgh.js`);
    expect(response.status).toBe(404);
    expect(await response.text()).toContain("No asset is published");
  });

  it("still serves files and the shell for client-side routes", async () => {
    const file = await fetch(`${origin}/data/league/members.json`);
    expect(file.status).toBe(200);
    expect(await file.text()).toBe("{}");
    const route = await fetch(`${origin}/league/352490/members/1`);
    expect(route.status).toBe(200);
    expect(await route.text()).toContain("<title>shell</title>");
  });
});
