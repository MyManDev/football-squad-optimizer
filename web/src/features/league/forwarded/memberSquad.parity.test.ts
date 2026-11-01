/// <reference types="node" />
// @vitest-environment node
/**
 * The parity run of #983 box 1 (decision 4, #983 comment 6559339847): every member of the
 * published league builds its device block from forwarded data, through the same
 * `forwardedMemberSquad` the member page runs, and the block is held field by field to the
 * one the weekly run published for that member in the committed tree. Raw captures are not
 * committed, so the pinned vectors are the always-on half of the box and this run is the
 * other half, against real FPL.
 *
 * Opt-in: nothing runs unless `FORWARDER_PARITY` names a source, so CI never reads FPL.
 *
 * - `FORWARDER_PARITY=local` runs the Worker's handler in this process
 *   (`workers/fpl-proxy/src/worker.js`, real `fetch`, no cache): FPL read through the code
 *   the deployed Worker runs.
 * - `FORWARDER_PARITY=https://squadopt.mymandev.com` (any origin) reads `/api/v1/fpl/...`
 *   from that site with the site's own client.
 *
 * One bundle per member, one member at a time, with a short pause between them. The report
 * names entry ids, field names, counts and differences only: never a manager, a team or a
 * player.
 *
 * The published block was built at the capture's time from what FPL showed then. The
 * identity rule binds the bundle to the held week (the table gameweek minus 1), but a bundle
 * read later also carries what happened after the capture: the table gameweek's transfers,
 * chips and history row once its deadline has passed. So each member is built three ways:
 *
 * - `held week`: the bundle with every transfer, chip and history row after the held week
 *   left out; only what the identity rule binds;
 * - `capture`: as `held week`, but keeping the table gameweek's transfers made before the
 *   capture's time, in case FPL showed them to the capture;
 * - `forwarded`: the bundle as the forwarder answers it now, as a visitor's page builds it.
 *
 * The check holds the `held week` or the `capture` build to the published block (whichever
 * matches the member), and reports the `forwarded` build beside them, with what moved.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

import { describe, expect, it } from "vitest";

import { PUBLIC_ROOT } from "../../../testSupport/shippedTrees";
import type { FixturesPayload } from "../../fixtures/types";
import {
  DEVICE_PLAN_TABLE_CONTRACT_VERSION,
  isDevicePlanDocument,
  type DevicePlanDocument,
  type DevicePlanEntry,
} from "../device/types";
import { devicePlanTable } from "../directory";
import { createForwarderClient, FORWARDER_ROOT, type ForwarderClient } from "../forwarder/client";
import type { FplEntryBundle } from "../forwarder/documents";
import { bundleMatchesTable } from "../forwarder/identity";
import { assertEnvelope } from "../publicationShape";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { forwardedMemberSquad } from "./memberSquad";

const SOURCE = process.env.FORWARDER_PARITY?.trim() ?? "";
const LEAGUE = 352490;
const PAUSE_MS = 300;
const DATA = join(PUBLIC_ROOT, "data");

/** The Worker's handler: plain JavaScript without declarations, typed by `WorkerModule`. */
const WORKER_MODULE = pathToFileURL(
  join(__dirname, "../../../../../workers/fpl-proxy/src/worker.js"),
).href;

interface WorkerModule {
  createWorker(options: {
    fetch?: (input: string, init: RequestInit) => Promise<Response>;
    cache?: null;
    log?: (event: string, fields: Record<string, unknown>) => void;
  }): { fetch(request: Request): Promise<Response> };
}

/** The forwarder the source names, and the words the report gives it. */
async function forwarderFor(
  source: string,
  events: Map<string, number>,
): Promise<{ client: ForwarderClient; words: string }> {
  if (source === "local") {
    const { createWorker } = (await import(/* @vite-ignore */ WORKER_MODULE)) as WorkerModule;
    const worker = createWorker({
      fetch: (input, init) => globalThis.fetch(input, init),
      cache: null,
      // A failure's kind and status, never its message, as the Worker logs it.
      log: (event, fields) => {
        const key = [event, fields.route, fields.failure, fields.status]
          .filter((part) => part !== undefined)
          .join(" ");
        events.set(key, (events.get(key) ?? 0) + 1);
      },
    });
    const origin = "https://forwarder.invalid";
    return {
      client: createForwarderClient({
        root: `${origin}${FORWARDER_ROOT}`,
        fetch: (input, init) =>
          worker.fetch(new Request(input, { method: "GET", headers: init.headers })),
      }),
      words: "local: the Worker's handler in this process, real FPL, no cache",
    };
  }
  const origin = new URL(source);
  if ((origin.protocol !== "https:" && origin.protocol !== "http:") || origin.pathname !== "/") {
    throw new Error("FORWARDER_PARITY is `local` or a site's origin, such as https://host.");
  }
  return {
    client: createForwarderClient({
      root: `${origin.origin}${FORWARDER_ROOT}`,
      fetch: (input, init) => globalThis.fetch(input, init),
    }),
    words: `${origin.origin}: the deployed forwarder, through the site's client`,
  };
}

function json(relative: string): unknown {
  return JSON.parse(readFileSync(join(DATA, ...relative.split("/")), "utf-8"));
}

interface PublishedTree {
  tablePath: string;
  table: LeagueViewEnvelope<DevicePlanDocument>;
  fixtures: FixturesPayload;
  members: number[];
  entry(entryId: number): LeagueViewEnvelope<EntrySquad>;
}

/** The league's line in the committed directory, its capture's table, members and entries. */
function publishedTree(): PublishedTree {
  const directory = json("leagues.json") as {
    payload: { leagues: Record<string, unknown>[] };
  };
  const line = directory.payload.leagues.find((row) => row.league_id === LEAGUE);
  if (line === undefined) throw new Error(`The directory has no line for league ${LEAGUE}.`);
  const ref = devicePlanTable(line.device_plan, line.device_plan_sha256);
  if (ref === undefined) throw new Error("The league's line names no capture table.");
  const bytes = readFileSync(join(DATA, ...ref.path.split("/")));
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (digest !== ref.sha256) throw new Error(`${ref.path} is not at the sha256 its line names.`);
  const table = assertEnvelope<unknown>(JSON.parse(bytes.toString("utf-8")));
  if (
    !isDevicePlanDocument(table.payload) ||
    table.payload.contract_version !== DEVICE_PLAN_TABLE_CONTRACT_VERSION
  ) {
    throw new Error(`${ref.path} is not a table the page accepts.`);
  }
  const fixtures = json("fixtures.json") as { contract_version: string; payload: FixturesPayload };
  if (fixtures.contract_version !== "fixtures_v1") throw new Error("No fixture list.");
  const tree = String(line.path);
  const members = assertEnvelope<{ league_id: number; members: { entry_id: number }[] }>(
    json(`${tree}/members.json`),
  );
  if (members.payload.league_id !== LEAGUE) throw new Error("members.json is another league's.");
  return {
    tablePath: ref.path,
    table: table as LeagueViewEnvelope<DevicePlanDocument>,
    fixtures: fixtures.payload,
    members: members.payload.members.map((member) => member.entry_id),
    entry: (entryId) => assertEnvelope<EntrySquad>(json(`${tree}/entries/${entryId}.json`)),
  };
}

/** The capture's UTC time, from its id (`fpl-live-YYYYMMDDTHHMMSSZ-...`). */
function captureTime(snapshot: string): number {
  const parts = /^fpl-live-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z-/.exec(snapshot);
  if (parts === null) throw new Error("The table's capture id carries no time.");
  const [, year, month, day, hour, minute, second] = parts.map(Number);
  return Date.UTC(year!, month! - 1, day!, hour!, minute!, second!);
}

type BuildName = "held week" | "capture" | "forwarded";
const BUILDS: readonly BuildName[] = ["held week", "capture", "forwarded"];

/** The bundle as each build reads it. */
function trimmed(
  bundle: FplEntryBundle,
  build: BuildName,
  held: number,
  capturedAt: number,
): FplEntryBundle {
  if (build === "forwarded") return bundle;
  return {
    ...bundle,
    history: {
      current: bundle.history.current.filter((row) => row.event <= held),
      chips: bundle.history.chips.filter((row) => row.event <= held),
    },
    transfers: bundle.transfers.filter((row) =>
      build === "held week"
        ? row.event <= held
        : row.event <= held || Date.parse(row.time) <= capturedAt,
    ),
  };
}

const DEVICE_FIELDS = [
  "top100_weights",
  "held",
  "bank_tenths",
  "free_transfers",
  "sell_tenths",
] as const;

/** The entry document's fields that feed or sit beside the block, compared as a second view. */
const ENTRY_FIELDS = [
  "gameweek",
  "season",
  "source_snapshot_id",
  "squad_basis",
  "active_chip",
  "bank_tenths",
  "free_transfers",
  "free_transfers_known",
  "purchase_prices_known",
  "squad_sell_value_tenths",
  "spendable_budget_tenths",
  "chips_used",
  "chips",
  "lineup",
  "captain",
  "vice_captain",
  "data_quality",
  "missing_fields",
] as const;

/** Which input each field comes from, and whether it can move after the capture. */
const MOBILITY: Record<string, string> = {
  top100_weights: "the table's rules; fixed with the table",
  held: "the held week's picks, frozen at that week's deadline; fixed",
  bank_tenths:
    "the held week's bank, less what the stated value withholds when purchase prices are " +
    "not known; moves only where purchase_prices_known moves",
  free_transfers: "the history through the held week; fixed",
  sell_tenths:
    "the table's prices (capture time; FPL's later price changes do not reach it) and the " +
    "purchase-price replay, which also checks the table gameweek's transfers: those made " +
    "after the capture can move it",
  chips_used: "the history's chips: a chip played in the table gameweek appears after its deadline",
  chips: "as chips_used",
  data_quality: "the forwarded document always says complete",
  missing_fields: "the forwarded document always says none",
};

function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

/** The fifteen of an entry document in its order, as player ids. */
function lineup(squad: EntrySquad): number[] {
  return [...squad.starting_xi, ...squad.bench].map((player) => player.player_id);
}

function entryField(squad: EntrySquad, field: (typeof ENTRY_FIELDS)[number]): unknown {
  const fifteen = [...squad.starting_xi, ...squad.bench];
  if (field === "lineup") return lineup(squad);
  if (field === "captain") return fifteen.findIndex((player) => player.is_captain);
  if (field === "vice_captain") return fifteen.findIndex((player) => player.is_vice_captain);
  return (squad as unknown as Record<string, unknown>)[field];
}

/** Paths under two values whose leaves differ, for the chip states. */
function leafPaths(left: unknown, right: unknown, path: string): string[] {
  if (isDeepStrictEqual(left, right)) return [];
  const isRecord = (value: unknown) =>
    typeof value === "object" && value !== null && !Array.isArray(value);
  if (!isRecord(left) || !isRecord(right)) return [path];
  const [a, b] = [left as Record<string, unknown>, right as Record<string, unknown>];
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .sort()
    .flatMap((key) => leafPaths(a[key], b[key], `${path}.${key}`));
}

/**
 * A value as a published document carries it: JSON. The forwarded document is built in
 * memory, where `chips_used` is a null-prototype object; as JSON it is the same.
 */
function asJson(value: unknown): unknown {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

/** What differs in one field, without a name or a player list; null where it matches. */
function difference(field: string, built: unknown, own: unknown): string | null {
  const [forwarded, published] = [asJson(built), asJson(own)];
  if (isDeepStrictEqual(forwarded, published)) return null;
  if (forwarded === undefined) return "absent from the forwarded document";
  if (published === undefined) return "absent from the published document";
  if (typeof forwarded === "number" && typeof published === "number") {
    if (field === "captain" || field === "vice_captain") return "another place in the fifteen";
    return `forwarded ${signed(forwarded - published)} against published`;
  }
  if (field === "held" || field === "lineup") {
    const [a, b] = [forwarded as number[], published as number[]];
    const places = a.filter((id, index) => id !== b[index]).length;
    const other = a.filter((id) => !b.includes(id)).length;
    return other === 0
      ? `the same players, ${places} places in another order`
      : `${other} of ${b.length} players not in the published one`;
  }
  if (field === "sell_tenths") {
    const [a, b] = [forwarded as Record<string, number>, published as Record<string, number>];
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
    const unpaired = keys.filter((key) => a[key] === undefined || b[key] === undefined).length;
    const steps = keys
      .filter((key) => a[key] !== undefined && b[key] !== undefined && a[key] !== b[key])
      .map((key) => a[key]! - b[key]!)
      .sort((x, y) => x - y);
    const total = steps.reduce((sum, step) => sum + step, 0);
    return (
      `${steps.length} of ${keys.length} sale prices differ` +
      (steps.length > 0 ? ` (${steps.map(signed).join(", ")}; total ${signed(total)})` : "") +
      (unpaired > 0 ? `, ${unpaired} players held by one side only` : "")
    );
  }
  if (field === "chips_used") {
    const [a, b] = [forwarded as Record<string, number[]>, published as Record<string, number[]>];
    const names = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
    const plays = names
      .filter((name) => !isDeepStrictEqual(a[name] ?? [], b[name] ?? []))
      .map(
        (name) =>
          `${name}: forwarded ${(a[name] ?? []).length} plays, published ${(b[name] ?? []).length}`,
      )
      .join("; ");
    return plays || "the same plays, with an empty list on one side only";
  }
  if (field === "chips") {
    return leafPaths(forwarded, published, "chips")
      .map((path) => path.replace(/^chips\./, ""))
      .join(", ");
  }
  return `forwarded ${JSON.stringify(forwarded)}, published ${JSON.stringify(published)}`;
}

interface MemberRun {
  entryId: number;
  /** Why no bundle came, where none came. */
  refused: string | null;
  copy: string | null;
  sourceTime: string | null;
  /** What the bundle carries after the held week: transfers before and after the capture. */
  later: { before: number; after: number; chips: number; rows: number } | null;
  builds: Partial<Record<BuildName, { refused: string } | { squad: EntrySquad }>>;
}

describe.skipIf(SOURCE === "")("forwarded device blocks against the published ones", () => {
  it(
    "builds every member's block from forwarded data and compares it",
    { timeout: 600_000 },
    async () => {
      const events = new Map<string, number>();
      const { client, words } = await forwarderFor(SOURCE, events);
      const tree = publishedTree();
      const table = tree.table.payload;
      const held = table.gameweek - 1;
      const capturedAt = captureTime(table.source_snapshot_id);
      const started = Date.now();

      const runs: MemberRun[] = [];
      for (const [index, entryId] of tree.members.entries()) {
        if (index > 0) await new Promise((resolve) => setTimeout(resolve, PAUSE_MS));
        const read = await client.entryBundle(entryId, table.gameweek, { timeoutMs: 120_000 });
        if (!read.ok) {
          runs.push({
            entryId,
            refused: read.reason,
            copy: null,
            sourceTime: null,
            later: null,
            builds: {},
          });
          continue;
        }
        const bundle = read.document;
        const match = bundleMatchesTable(bundle, table, entryId);
        const run: MemberRun = {
          entryId,
          refused: match.ok ? null : `identity: ${match.reason}`,
          copy: read.copy,
          sourceTime: bundle.source_time,
          later: {
            before: bundle.transfers.filter(
              (row) => row.event > held && Date.parse(row.time) <= capturedAt,
            ).length,
            after: bundle.transfers.filter(
              (row) => row.event > held && Date.parse(row.time) > capturedAt,
            ).length,
            chips: bundle.history.chips.filter((row) => row.event > held).length,
            rows: bundle.history.current.filter((row) => row.event > held).length,
          },
          builds: {},
        };
        for (const build of BUILDS) {
          const built = forwardedMemberSquad({
            bundle: trimmed(bundle, build, held, capturedAt),
            table: tree.table,
            entryId,
            fixtures: tree.fixtures,
            leagueId: LEAGUE,
          });
          run.builds[build] = built.ok ? { squad: built.squad.payload } : { refused: built.reason };
        }
        runs.push(run);
      }

      const lines: string[] = [];
      const say = (line = "") => lines.push(line);
      say(`Forwarded device blocks against the published ones (#983 box 1), league ${LEAGUE}`);
      say(`source: ${words}`);
      say(
        `run: ${new Date(started).toISOString()}, ${Math.round((Date.now() - started) / 1000)} s`,
      );
      say(
        `table: ${tree.tablePath} (gameweek ${table.gameweek}, capture ` +
          `${new Date(capturedAt).toISOString()}); held week ${held}`,
      );
      say(`published entries: ${tree.members.length} (leagues/${LEAGUE}/entries/<id>.json)`);
      const read = runs.filter((run) => run.sourceTime !== null);
      const times = read.map((run) => run.sourceTime!).sort();
      say(
        `bundles: ${read.length} of ${runs.length} read` +
          (times.length > 0 ? `, source_time ${times[0]} to ${times.at(-1)}` : "") +
          `; copies ${JSON.stringify(
            Object.fromEntries(
              [...new Set(read.map((run) => String(run.copy)))].map((copy) => [
                copy,
                read.filter((run) => String(run.copy) === copy).length,
              ]),
            ),
          )}`,
      );
      for (const run of runs.filter((run) => run.refused !== null)) {
        say(`  ${run.entryId}: no bundle or not bound: ${run.refused}`);
      }
      if (events.size > 0) {
        say(`worker log events: ${JSON.stringify(Object.fromEntries(events))}`);
      }
      say();
      say(
        "Builds: `held week` leaves out every transfer, chip and history row after the held " +
          "week; `capture` also keeps the table gameweek's transfers made before the capture; " +
          "`forwarded` is the bundle as answered now.",
      );

      // Per field and build: members that match, and the mismatches.
      type Section = "device_plan" | "entry";
      const mismatches: {
        build: BuildName;
        section: Section;
        entryId: number;
        field: string;
        detail: string;
      }[] = [];
      const counts = new Map<string, number>();
      const tally = (key: string) => counts.set(key, (counts.get(key) ?? 0) + 1);
      const refusals: { build: BuildName; entryId: number; reason: string }[] = [];
      /** Each member's device-block result per build: true where every field matches. */
      const whole = new Map<number, Partial<Record<BuildName, boolean>>>();
      for (const run of runs) {
        if (run.refused !== null) continue;
        const published = tree.entry(run.entryId).payload;
        const verdict: Partial<Record<BuildName, boolean>> = {};
        for (const build of BUILDS) {
          const result = run.builds[build]!;
          if ("refused" in result) {
            refusals.push({ build, entryId: run.entryId, reason: result.refused });
            verdict[build] = false;
            continue;
          }
          const squad = result.squad;
          const block = (squad.device_plan ?? {}) as Partial<DevicePlanEntry>;
          const own = (published.device_plan ?? {}) as Partial<DevicePlanEntry>;
          const fields = [
            ...new Set([...DEVICE_FIELDS, ...Object.keys(block), ...Object.keys(own)]),
          ];
          let all = true;
          for (const field of fields) {
            const detail = difference(
              field,
              (block as Record<string, unknown>)[field],
              (own as Record<string, unknown>)[field],
            );
            if (detail === null) tally(`${build}|device_plan|${field}`);
            else {
              all = false;
              mismatches.push({
                build,
                section: "device_plan",
                entryId: run.entryId,
                field,
                detail,
              });
            }
          }
          verdict[build] = all;
          for (const field of ENTRY_FIELDS) {
            const detail = difference(
              field,
              entryField(squad, field),
              entryField(published, field),
            );
            if (detail === null) tally(`${build}|entry|${field}`);
            else mismatches.push({ build, section: "entry", entryId: run.entryId, field, detail });
          }
        }
        whole.set(run.entryId, verdict);
      }

      const bound = runs.filter((run) => run.refused === null).length;
      /** One row per field, one column per build: members whose field matches exactly. */
      const fieldTable = (rows: readonly (readonly [string, (build: BuildName) => number])[]) => {
        const width = Math.max(5, ...rows.map(([field]) => field.length));
        say(`  ${"field".padEnd(width)}  ${BUILDS.map((build) => build.padStart(10)).join("  ")}`);
        for (const [field, matching] of rows) {
          const cells = BUILDS.map((build) => `${matching(build)}/${bound}`.padStart(10));
          say(`  ${field.padEnd(width)}  ${cells.join("  ")}`);
        }
      };
      const matching =
        (section: Section, field: string) =>
        (build: BuildName): number =>
          counts.get(`${build}|${section}|${field}`) ?? 0;
      const deviceFields = [
        ...new Set([
          ...DEVICE_FIELDS,
          ...mismatches.filter((row) => row.section === "device_plan").map((row) => row.field),
        ]),
      ];
      say();
      say("Device block (device_plan): members whose field matches exactly");
      fieldTable([
        ...deviceFields.map((field) => [field, matching("device_plan", field)] as const),
        [
          "whole block",
          (build: BuildName) =>
            [...whole.values()].filter((verdict) => verdict[build] === true).length,
        ] as const,
      ]);
      say();
      say("Entry document beside the block: members whose field matches exactly");
      fieldTable(ENTRY_FIELDS.map((field) => [field, matching("entry", field)] as const));
      say();
      say("Refused builds (no document):");
      if (refusals.length === 0) say("  none");
      for (const { build, entryId, reason } of refusals) say(`  [${build}] ${entryId}: ${reason}`);
      say();
      say("Mismatches (entry id, field, what differs):");
      if (mismatches.length === 0) say("  none");
      for (const build of BUILDS) {
        for (const row of mismatches.filter((row) => row.build === build)) {
          say(`  [${build}] ${row.entryId} ${row.section}.${row.field}: ${row.detail}`);
        }
      }
      say();
      say("What the bundles carry after the held week (counts per member):");
      say("  entry id   transfers before capture   transfers after capture   chips   history rows");
      for (const run of runs) {
        if (run.later === null) continue;
        const { before, after, chips, rows } = run.later;
        say(
          `  ${String(run.entryId).padEnd(9)}  ${String(before).padStart(24)}   ` +
            `${String(after).padStart(23)}   ${String(chips).padStart(5)}   ${String(rows).padStart(12)}`,
        );
      }
      say();
      say("What each compared field comes from, and whether it can move after the capture:");
      for (const [field, source] of Object.entries(MOBILITY)) say(`  ${field}: ${source}`);
      say(
        "  every other entry field: the held week's picks and history, or the table; fixed " +
          "with the identity rule",
      );

      const unmatched = runs
        .filter((run) => run.refused === null)
        .filter((run) => {
          const verdict = whole.get(run.entryId)!;
          return verdict["held week"] !== true && verdict.capture !== true;
        })
        .map((run) => run.entryId);
      say();
      say(
        `Verdict: ${bound - unmatched.length} of ${tree.members.length} members' device blocks ` +
          "match the published ones exactly in the `held week` or the `capture` build" +
          (unmatched.length > 0 ? `; not: ${unmatched.join(", ")}` : ""),
      );
      // Straight to the terminal: this run's console lines are not echoed here.
      process.stdout.write(`${lines.join("\n")}\n`);

      expect(runs.map((run) => [run.entryId, run.refused])).toEqual(
        tree.members.map((entryId) => [entryId, null]),
      );
      expect(unmatched).toEqual([]);
    },
  );
});
