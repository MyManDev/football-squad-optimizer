/**
 * The shipped league tree, read by the page's own validators.
 *
 * Every other test here reads example documents, so a producer that starts publishing a
 * shape the page refuses stays green everywhere and breaks only in production: a member's
 * index with a rival strategy's three-week file was refused whole, and every control on
 * the live member page went dark. This walks what is actually committed under
 * `public/data/league` and holds each index and each advice document to the validators
 * the page applies, and each file the index names to the path the page would read.
 *
 * It also reads `history/` and `scoreboard.json`, which a settled publish writes and
 * nothing else validated. Those two are worse than the advice tree when they are wrong,
 * because the page does not fail on them: `loadLiveSeries` loads every member with
 * `Promise.allSettled`, re-checks each one inside a bare `catch` and drops the ones that
 * throw, leaving a quietly smaller league and one sentence nobody is watching.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolvePublishedAdvice } from "./advice/adviceSelection";
import { isAdvicePayload } from "./advice/adviceShape";
import { TOP100_WEIGHTS, top100TargetPath } from "./advice/top100";
import { checkedHistory } from "./history/historyData";
import { summarizeLiveSeries } from "./history/liveSeries";
import { assertAdviceIndex, assertEnvelope, assertMembers } from "./publicationShape";
import type { EntryAdviceIndex, LeagueMembers, Scoreboard } from "./types";

const ROOT = join(__dirname, "../../../public/data/league");
const read = (relative: string): unknown => JSON.parse(readFileSync(join(ROOT, relative), "utf-8"));

function walk(directory: string, found: string[] = []): string[] {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) walk(path, found);
    else if (entry.name.endsWith(".json")) found.push(path);
  }
  return found;
}

const shipped = existsSync(join(ROOT, "members.json"));

describe.skipIf(!shipped)("the shipped league tree", () => {
  const members = shipped
    ? assertMembers(assertEnvelope<LeagueMembers>(read("members.json"))).payload
    : null;
  const humans = (members?.members ?? []).flatMap((member) =>
    member.member_kind === "human" ? [member.entry_id] : [],
  );

  it("names at least one member", () => {
    expect(humans.length).toBeGreaterThan(0);
  });

  it("publishes an index the page accepts for every member, and the baseline resolves", () => {
    for (const entryId of humans) {
      const relative = `advice/${entryId}/index.json`;
      if (!existsSync(join(ROOT, relative))) continue;
      const index = assertAdviceIndex(
        assertEnvelope<EntryAdviceIndex>(read(relative)),
        entryId,
      ).payload;
      if (!Array.isArray(index.strategies) || index.strategies.length === 0) continue;
      const selection = resolvePublishedAdvice(
        new URLSearchParams("mode=saf-puan&window=1"),
        index.league_id,
        entryId,
        members!.members,
        index,
      );
      expect(selection.status, relative).toBe("ready");
      expect(existsSync(join(ROOT, selection.path!)), selection.path!).toBe(true);
    }
  });

  it("names only files that exist, at the paths the page would read", () => {
    for (const entryId of humans) {
      const relative = `advice/${entryId}/index.json`;
      if (!existsSync(join(ROOT, relative))) continue;
      const index = (read(relative) as { payload: EntryAdviceIndex }).payload;
      for (const row of index.computed ?? []) {
        expect(existsSync(join(ROOT, row.path)), row.path).toBe(true);
      }
      const menu = index.top100;
      if (menu?.available !== true) continue;
      for (const [weight, path] of Object.entries(menu.paths)) {
        expect(path).toBe(
          top100TargetPath(
            entryId,
            { strategy: "saf-puan", window: 1, rivalEntryId: null },
            Number(weight),
            false,
          ),
        );
        expect(existsSync(join(ROOT, path)), path).toBe(true);
      }
      for (const row of menu.documents ?? []) {
        expect(TOP100_WEIGHTS).toContain(row.weight);
        expect(row.path).toBe(
          top100TargetPath(
            entryId,
            { strategy: row.strategy, window: row.window, rivalEntryId: row.rival_entry_id },
            row.weight,
            false,
          ),
        );
        expect(existsSync(join(ROOT, row.path)), row.path).toBe(true);
        // Every setting the index names must be selectable on the page.
        const query = new URLSearchParams({
          mode: row.strategy,
          window: String(row.window),
          top100: String(row.weight),
        });
        if (row.rival_entry_id !== null) query.set("rival", String(row.rival_entry_id));
        const selection = resolvePublishedAdvice(
          query,
          index.league_id,
          entryId,
          members!.members,
          index,
        );
        expect(selection.path, row.path).toBe(row.path);
      }
    }
  });

  it("publishes a history every member's own validator accepts", () => {
    const refused: string[] = [];
    for (const entryId of humans) {
      const relative = `history/${entryId}.json`;
      if (!existsSync(join(ROOT, relative))) continue;
      try {
        checkedHistory(read(relative), entryId);
      } catch (error) {
        refused.push(`${relative}: ${(error as Error).message}`);
      }
    }
    expect(refused).toEqual([]);
  });

  it("would notice a settled week that does not reconcile", () => {
    // A guard that has only ever seen good documents proves nothing about its own
    // sensitivity, and gameweek 5 is the first week to carry realized points through
    // this path. Break one settled week of a real document and require a refusal.
    const entryId = humans.find((id) => existsSync(join(ROOT, `history/${id}.json`)));
    if (entryId === undefined) return;
    const document = read(`history/${entryId}.json`) as {
      payload: { weeks: { reason: string | null; actual: unknown; net_difference: number }[] };
    };
    const settled = document.payload.weeks.find(
      (week) => week.reason === null && week.actual !== null,
    );
    if (settled === undefined) return;
    settled.net_difference += 1;
    expect(() => checkedHistory(document, entryId)).toThrow();
  });

  it("publishes a scoreboard and a history for the same members, and the page keeps them all", () => {
    if (!existsSync(join(ROOT, "scoreboard.json"))) return;
    const view = assertEnvelope<Scoreboard>(read("scoreboard.json")).payload;
    // Every member the scoreboard names is a member the page will try to load a history
    // for, so a scoreboard ahead of the history directory is a member dropped on sight.
    const named = [
      ...new Set(view.gameweeks.flatMap((week) => week.members.map((row) => row.entry_id))),
    ];
    const missing = named.filter((id) => !existsSync(join(ROOT, `history/${id}.json`)));
    expect(missing, "scoreboard names a member with no published history").toEqual([]);

    // The page drops a member whose history does not summarize against this scoreboard,
    // and says so only in a count. Here it has to be zero, member by member, so the
    // failure names the member instead of shrinking the league quietly.
    const dropped: string[] = [];
    for (const entryId of named) {
      if (!existsSync(join(ROOT, `history/${entryId}.json`))) continue;
      try {
        summarizeLiveSeries([checkedHistory(read(`history/${entryId}.json`), entryId)], view);
      } catch (error) {
        dropped.push(`${entryId}: ${(error as Error).message}`);
      }
    }
    expect(dropped).toEqual([]);
  });

  it("publishes only advice documents the page's runtime shape accepts", () => {
    const refused: string[] = [];
    for (const path of walk(join(ROOT, "advice"))) {
      if (path.endsWith("index.json")) continue;
      const document = JSON.parse(readFileSync(path, "utf-8")) as { payload?: unknown };
      if (!isAdvicePayload(document.payload)) refused.push(path.slice(ROOT.length + 1));
    }
    expect(refused).toEqual([]);
    // Well over a thousand documents; a loaded machine needs more than the default.
  }, 180_000);
});
