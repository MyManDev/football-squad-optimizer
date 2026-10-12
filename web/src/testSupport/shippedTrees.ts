/**
 * The league trees the committed site publishes, found the way the page finds them: each
 * tree `public/data/leagues.json` lists, or the one legacy tree `public/data/league` where
 * the site publishes no directory. The tests that hold the shipped tree to the page's
 * validators walk these, so the first publish under the directory is checked like every
 * publish before it. A site with neither is an error, never a skipped suite: a guard that
 * skips when the path it knows moves would ship the moved tree unchecked.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Vitest gives each file its __dirname (and a non-file import.meta.url under jsdom);
// Playwright loads the specs as modules, with a file: import.meta.url and no __dirname.
export const PUBLIC_ROOT =
  typeof __dirname === "string"
    ? join(__dirname, "../../public")
    : fileURLToPath(new URL("../../public", import.meta.url));

export interface ShippedTree {
  /** The tree's path under `public/`, as the page requests it. */
  path: string;
  /** The tree on disk. */
  root: string;
}

const TREE_PATH = /^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/;

export function shippedTrees(publicRoot: string = PUBLIC_ROOT): ShippedTree[] {
  const tree = (path: string): ShippedTree => ({
    path,
    root: join(publicRoot, ...path.split("/")),
  });
  const directory = join(publicRoot, "data", "leagues.json");
  if (existsSync(directory)) {
    const document = JSON.parse(readFileSync(directory, "utf-8")) as {
      payload?: { leagues?: { path?: unknown }[] };
    };
    const leagues = document.payload?.leagues ?? [];
    if (leagues.length === 0) throw new Error(`${directory} lists no league.`);
    return leagues.map(({ path }) => {
      if (typeof path !== "string" || !TREE_PATH.test(path)) {
        throw new Error(`${directory} lists a league without a tree path.`);
      }
      return tree(`data/${path}`);
    });
  }
  if (existsSync(join(publicRoot, "data", "league", "members.json"))) return [tree("data/league")];
  throw new Error(`${join(publicRoot, "data")} publishes no league tree.`);
}
