// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { shippedTrees } from "./shippedTrees";

let root: string;

function put(path: string, value: unknown) {
  mkdirSync(join(root, path, ".."), { recursive: true });
  writeFileSync(join(root, path), JSON.stringify(value));
}

const directory = (paths: string[]) => ({
  contract_version: "league_directory_v1",
  payload: { leagues: paths.map((path, index) => ({ league_id: index + 1, path })) },
});

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "shipped-trees-"));
});
afterEach(() => rmSync(root, { recursive: true, force: true }));

describe("shippedTrees", () => {
  it("follows the directory to every tree it lists, in its order", () => {
    put("data/leagues.json", directory(["leagues/7", "leagues/3"]));
    // A legacy tree beside a directory is not read: the directory decides.
    put("data/league/members.json", {});
    expect(shippedTrees(root)).toEqual([
      { path: "data/leagues/7", root: join(root, "data", "leagues", "7") },
      { path: "data/leagues/3", root: join(root, "data", "leagues", "3") },
    ]);
  });

  it("reads the legacy tree as the one tree where no directory is published", () => {
    put("data/league/members.json", {});
    expect(shippedTrees(root)).toEqual([
      { path: "data/league", root: join(root, "data", "league") },
    ]);
  });

  it("fails, never skips, when the site publishes no tree", () => {
    mkdirSync(join(root, "data"), { recursive: true });
    expect(() => shippedTrees(root)).toThrow("publishes no league tree");
  });

  it("refuses a directory that lists nothing or a line without a tree path", () => {
    put("data/leagues.json", directory([]));
    expect(() => shippedTrees(root)).toThrow("lists no league");
    put("data/leagues.json", directory(["../outside"]));
    expect(() => shippedTrees(root)).toThrow("without a tree path");
  });

  it("finds the committed site's tree", () => {
    const [first] = shippedTrees();
    expect(first?.path).toMatch(/^data\/(?:league|leagues\/\d+)$/);
  });
});
