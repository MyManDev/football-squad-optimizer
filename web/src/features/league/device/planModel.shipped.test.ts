/**
 * The device's one-week plans are the shipped tree's one-week plans. For every human member
 * of every published league tree, each one-week document the member's index names is solved
 * here from the tree's device inputs: the pure-points plan (`saf-puan/1.json`), every rival
 * document (`vs-<rival>.json`, against the rival's own entry document) and every Top 100
 * document (`top100-<weight>.json`). The squad, the eleven, the bench order, the captain,
 * the vice, the transfers, every move row's gain and the planner's objective must be what
 * the tree publishes, player by player, and so must the strategy's account beside them. A
 * named document the device declines by contract (a rival strategy with a Top 100 weight,
 * the manager's word, a window beyond one week) is listed by name with its reason, and the
 * device is held to declining it; nothing is passed over silently. The chip documents are
 * `planModel.chips.shipped.test.ts`'s. The trees are whatever publication the repository
 * holds (`testSupport/shippedTrees.ts`).
 */

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { shippedTrees } from "../../../testSupport/shippedTrees";
import type { AdviceRequest } from "../advice/adviceClient";
import type {
  AdviceStrategy,
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  LeagueMembers,
  LeagueViewEnvelope,
} from "../types";
import type { WindowSize } from "../../../lib/decisionVocabulary";
import { deviceRivalUsable } from "./computable";
import type { LpSolver } from "./lp/problem";
import { solveRequest, type DevicePlanRequest } from "./requests";
import { deviceSelection, rivalFromSquad } from "./selection";
import { DevicePlanRefused } from "./solve/week";
import { benchCoefficient, top100Coefficients } from "./strategies/top100";
import {
  isDevicePlanDocument,
  isDevicePlanEntry,
  isRivalStrategy,
  type DevicePlanAnswer,
  type DevicePlanDocument,
  type DevicePlanEntry,
  type DevicePlanPlayer,
} from "./types";

const require = createRequire(import.meta.url);
/** A document of one published tree. */
const reader =
  (root: string) =>
  <T>(relative: string): T =>
    JSON.parse(readFileSync(join(root, relative), "utf-8")) as T;

type Kind = "saf-puan" | "rival" | "top100";

/** A document the device is asked for, with the request that asks for it. */
interface Case {
  entryId: number;
  kind: Kind;
  path: string;
  squad: EntrySquad;
  published: EntryAdvice;
  request: Omit<DevicePlanRequest, "id" | "document" | "entry">;
}

/** A document the index names that the device declines, and the contract's reason. */
interface Declined {
  entryId: number;
  path: string;
  reason: string;
  squad: EntrySquad;
  request: AdviceRequest;
}

const RIVAL_WITH_WEIGHT = "a rival strategy with a Top 100 weight";
const MANAGERS_WORD = "the manager's word";
const LONGER_WINDOW = "a window beyond one week";
const NO_MEMBER_INPUTS = "no device inputs for the member";
const NO_TOP100_INPUTS = "no device inputs for a Top 100 weight";

interface Tree {
  /** Why nothing in the tree can be solved on the device, or null. */
  absent: string | null;
  cases: Case[];
  declined: Declined[];
}

/**
 * The tree's human members, every one-week document each one's index names, and the
 * request each document answers. The index is the authority on what the publish wrote; a
 * document it names must be there, so a publish that drops one fails here, not silently.
 */
function gather(ROOT: string): Tree {
  const read = reader(ROOT);
  if (!existsSync(join(ROOT, "device-plan.json"))) {
    return { absent: "the tree publishes no device-plan.json", cases: [], declined: [] };
  }
  const document = read<LeagueViewEnvelope<DevicePlanDocument>>("device-plan.json").payload;
  const members = read<LeagueViewEnvelope<LeagueMembers>>("members.json").payload.members;
  const squads = new Map<number, EntrySquad>();
  const squadOf = (entryId: number): EntrySquad | null => {
    if (!squads.has(entryId)) {
      const relative = `entries/${entryId}.json`;
      if (!existsSync(join(ROOT, relative))) return null;
      squads.set(entryId, read<LeagueViewEnvelope<EntrySquad>>(relative).payload);
    }
    return squads.get(entryId)!;
  };
  const cases: Case[] = [];
  const declined: Declined[] = [];
  for (const member of members) {
    if (member.member_kind !== "human") continue;
    const entryId = member.entry_id;
    const squad = squadOf(entryId);
    if (squad === null) throw new Error(`entry ${entryId} is listed without an entry document`);
    const base: AdviceRequest = {
      leagueId: document.league_id,
      entryId,
      strategy: "saf-puan",
      window: 1,
    };
    if (!isDevicePlanEntry(squad.device_plan)) {
      // The publisher's guard for a member the baseline path did not see: the page then
      // offers no device solve for anything of theirs.
      declined.push({
        entryId,
        path: `entries/${entryId}.json`,
        reason: NO_MEMBER_INPUTS,
        squad,
        request: base,
      });
      continue;
    }
    const entry: DevicePlanEntry = squad.device_plan;
    const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(
      `advice/${entryId}/index.json`,
    ).payload;
    const named: Array<{ path: string; request: AdviceRequest }> = [
      { path: `advice/${entryId}/saf-puan/1.json`, request: base },
    ];
    for (const row of index.computed) {
      named.push({
        path: row.path,
        request: {
          ...base,
          strategy: row.strategy as AdviceStrategy,
          window: row.window ?? 1,
          rivalEntryId: row.rival_entry_id,
        },
      });
    }
    const top100 = index.top100?.available ? index.top100 : null;
    for (const [weight, path] of Object.entries(top100?.paths ?? {})) {
      named.push({ path, request: { ...base, top100Weight: Number(weight) } });
    }
    for (const [weight, path] of Object.entries(top100?.word_paths ?? {})) {
      named.push({
        path,
        request: { ...base, top100Weight: Number(weight), managersWord: true },
      });
    }
    for (const row of top100?.documents ?? []) {
      named.push({
        path: row.path,
        request: {
          ...base,
          strategy: row.strategy as AdviceStrategy,
          window: row.window as WindowSize,
          rivalEntryId: row.rival_entry_id,
          top100Weight: row.weight,
        },
      });
    }
    for (const { path, request } of named) {
      const weight = request.top100Weight ?? 0;
      const rivalEntryId = request.rivalEntryId ?? null;
      // The contract's own refusals, each named; the device is held to them below.
      const reason =
        request.window !== 1
          ? LONGER_WINDOW
          : request.managersWord
            ? MANAGERS_WORD
            : weight !== 0 && rivalEntryId !== null
              ? RIVAL_WITH_WEIGHT
              : weight !== 0 &&
                  document.rules.top100 === undefined &&
                  entry.top100_weights === undefined
                ? NO_TOP100_INPUTS
                : null;
      if (reason !== null) {
        declined.push({ entryId, path, reason, squad, request });
        continue;
      }
      const published = read<LeagueViewEnvelope<EntryAdvice>>(path).payload;
      if (rivalEntryId === null) {
        cases.push({
          entryId,
          kind: weight === 0 ? "saf-puan" : "top100",
          path,
          squad,
          published,
          request: { top100Weight: weight },
        });
        continue;
      }
      // The rival's eleven and captain come from their own entry document, as on the page.
      const rivalSquad = squadOf(rivalEntryId);
      if (rivalSquad === null || !deviceRivalUsable(squad, rivalSquad)) {
        throw new Error(`${path}: the rival's entry document cannot be played against`);
      }
      if (!isRivalStrategy(request.strategy)) {
        throw new Error(`${path}: ${request.strategy} is not a strategy the device plays`);
      }
      cases.push({
        entryId,
        kind: "rival",
        path,
        squad,
        published,
        request: {
          strategy: { name: request.strategy, rival: rivalFromSquad(rivalEntryId, rivalSquad)! },
        },
      });
    }
  }
  return { absent: null, cases, declined };
}

const trees = shippedTrees().map(({ path, root }) => ({ path, root, tree: gather(root) }));
const ids = (players: Array<{ player_id: number }>) => players.map((p) => p.player_id);

/** The (squad, starter, captain) a document is chosen on: the base points or a weight's. */
function coefficientsFor(kind: Kind, weight: number) {
  return (player: DevicePlanPlayer): [number, number, number] =>
    kind === "top100" ? top100Coefficients(player, weight) : player.coefficients;
}

/**
 * The planner's objective of a published plan, on the document's integer scale: the squad
 * coefficients over the fifteen, the starter coefficients over the eleven and the
 * captain's, on the points the plan is chosen on, less the caution margin per paid
 * transfer. What the device maximises; a rival strategy maximises it under its band.
 */
function publishedObjective(
  document: DevicePlanDocument,
  published: EntryAdvice,
  coefficients: (player: DevicePlanPlayer) => [number, number, number],
  freeTransfers: number,
): number {
  const byId = new Map(document.players.map((p) => [p.id, coefficients(p)]));
  const eleven = new Set(ids(published.starting_xi!));
  const fifteen = [...ids(published.starting_xi!), ...ids(published.bench!)];
  let total = 0;
  for (const id of fifteen) {
    const [squad, starter, captain] = byId.get(id)!;
    total += squad;
    if (eleven.has(id)) total += starter;
    if (id === published.captain!.player_id) total += captain;
  }
  const arrivals = published.moves.filter((m) => m.player_in !== null).length;
  return total - document.rules.hit_cost_scaled * Math.max(0, arrivals - freeTransfers);
}

/** The device's answer held to the published document, field by field. */
function expectPublished(document: DevicePlanDocument, c: Case, answer: DevicePlanAnswer) {
  const { published } = c;
  const entry = c.squad.device_plan as DevicePlanEntry;
  const weight = c.request.top100Weight ?? 0;
  const coefficients = coefficientsFor(c.kind, weight);
  expect(published.chip ?? null).toBeNull();
  expect(answer.chip).toBeNull();
  const objective = publishedObjective(document, published, coefficients, entry.free_transfers);
  // A plan the server found without finishing its proof is not held to: the device proves
  // its own, which may be the better plan. On the planner's own objective the proven plan
  // may not fall below the published one; a rival strategy's only within the same band.
  if (published.solver_status !== "OPTIMAL") {
    if (c.kind === "rival") {
      expect(answer.rival!.plan_kind).toBe(published.plan_kind);
      expect(answer.rival!.overlap_applied).toBe(published.overlap_applied);
    }
    expect(answer.objective_scaled).toBeGreaterThanOrEqual(objective);
    return;
  }
  expect(answer.objective_scaled).toBe(objective);
  // The ids themselves, not players alike on the planner's numbers: the contract makes the
  // tie-break part of the answer (the table in id order, a tie to the lower rank), and the
  // shipped plans hold equal players the tie-break chose between, so a drift in it fails
  // here. The eleven and the transfers are compared as sets, the bench in its order.
  const sorted = (players: readonly number[]) => [...players].sort((a, b) => a - b);
  const player = (row: { player_id: number } | null) => row?.player_id ?? null;
  expect(sorted(answer.squad)).toEqual(
    sorted([...ids(published.starting_xi!), ...ids(published.bench!)]),
  );
  expect(sorted(answer.starting_xi)).toEqual(sorted(ids(published.starting_xi!)));
  expect(answer.captain).toBe(published.captain!.player_id);
  expect(answer.vice_captain).toBe(published.vice_captain!.player_id);
  expect(answer.bench).toEqual(ids(published.bench!));
  expect(sorted(answer.transfers_in)).toEqual(
    sorted(ids(published.moves.flatMap((m) => (m.player_in ? [m.player_in] : [])))),
  );
  expect(sorted(answer.transfers_out)).toEqual(
    sorted(ids(published.moves.flatMap((m) => (m.player_out ? [m.player_out] : [])))),
  );
  expect(answer.transfer_hit_points).toBe(published.transfer_hit_points ?? 0);
  expect(answer.expected_own_points).toBeCloseTo(published.expected_own_points!, 6);
  if (published.expected_gain_vs_hold == null) expect(answer.expected_gain_vs_hold).toBeNull();
  else expect(answer.expected_gain_vs_hold).toBeCloseTo(published.expected_gain_vs_hold, 6);
  // Every move row: the same pair in the same place, and the same share of the gain.
  expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
    published.moves.map((m) => [player(m.player_out), player(m.player_in)]),
  );
  for (const [index, move] of answer.moves.entries()) {
    const expected = published.moves[index]!.expected_points_delta;
    if (expected === null) expect(move.gain).toBeNull();
    else expect(move.gain).toBeCloseTo(expected, 6);
  }
  // The price is a difference between two plans; it is held where the server proved both.
  const priced = published.control_solver_status === "OPTIMAL";
  if (c.kind === "rival") {
    const rival = answer.rival!;
    expect(rival.mode).toBe(published.mode);
    expect(rival.rival_entry_id).toBe(published.rival_entry_id);
    expect(rival.transfer_cap).toBe(published.transfer_cap);
    expect(rival.overlap_target).toBe(published.overlap_target);
    expect(rival.overlap_applied).toBe(published.overlap_applied);
    expect(rival.plan_kind).toBe(published.plan_kind);
    expect(rival.expected_gap_vs_rival).toBeCloseTo(published.expected_gap_vs_rival!, 6);
    expect(rival.overlap_count).toBe(published.overlap_count);
    expect(rival.captain_agreement).toBe(published.captain_agreement);
    const alternative = published.alternative_plan ?? null;
    if (alternative === null) expect(rival.alternative_plan).toBeNull();
    else {
      expect(rival.alternative_plan?.kind).toBe(alternative.kind);
      expect(rival.alternative_plan?.overlap_applied).toBe(alternative.overlap_applied);
      expect(rival.alternative_plan?.transfer_hit_points).toBe(alternative.transfer_hit_points);
      if (priced) {
        expect(rival.alternative_plan!.expected_points_cost).toBeCloseTo(
          alternative.expected_points_cost,
          6,
        );
      }
    }
    if (priced) {
      expect(rival.expected_points_cost).toBeCloseTo(published.expected_points_cost!, 6);
      if (published.expected_points_cost_ceiling !== undefined) {
        expect(rival.expected_points_cost_ceiling).toBeCloseTo(
          published.expected_points_cost_ceiling,
          6,
        );
      }
    }
  }
  if (c.kind === "top100") {
    const top100 = answer.top100!;
    expect(top100.weight).toBe(published.top100!.weight);
    expect(top100.changed).toBe(published.top100!.changed);
    expect(top100.reasons).toEqual(published.moves.map((m) => m.reason_code));
    if (priced) {
      expect(top100.expected_points_cost).toBeCloseTo(published.expected_points_cost!, 6);
      if (published.expected_points_cost_ceiling !== undefined) {
        expect(top100.expected_points_cost_ceiling).toBeCloseTo(
          published.expected_points_cost_ceiling,
          6,
        );
      }
    }
  }
}

describe("the shipped one-week plans", () => {
  let solver: LpSolver;
  beforeAll(async () => {
    const wasm = readFileSync(require.resolve("highs/runtime"));
    const load = (await import("highs")).default;
    solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
  }, 60_000);

  for (const { path, root: ROOT, tree } of trees) {
    describe(path, () => {
      if (tree.absent !== null) {
        it.skip(`are not solved: ${tree.absent}`, () => {});
        return;
      }
      const read = reader(ROOT);
      const document = read<LeagueViewEnvelope<unknown>>("device-plan.json").payload;

      it("are named by the members' indexes, and every one the device takes is solved here", () => {
        expect(isDevicePlanDocument(document)).toBe(true);
        // One pure-points plan for every human member with device inputs, and at least one.
        const plain = tree.cases.filter((c) => c.kind === "saf-puan");
        const withInputs = new Set(plain.map((c) => c.entryId));
        expect(plain.length).toBe(withInputs.size);
        expect(plain.length).toBeGreaterThan(0);
        for (const c of tree.cases) expect(withInputs.has(c.entryId)).toBe(true);
        expect(new Set(tree.cases.map((c) => c.path)).size).toBe(tree.cases.length);
      });

      it("state every player's coefficients as the server scales his points", () => {
        if (!isDevicePlanDocument(document)) {
          throw new Error("the tree's device inputs are not the published shapes");
        }
        // A published plan can stay optimal under a coefficient that drifted, so the plans
        // alone would not show it. The captain's is the points on the integer scale rounded
        // half up, the bench's a tenth of that by the same rule, the starter's the rest.
        const scale = document.rules.expected_points_scale;
        const drifted = document.players
          .filter(({ coefficients: [squad, starter, captain], expected_points }) => {
            return (
              Math.abs(captain - expected_points * scale) > 0.5 + 1e-6 ||
              squad !== benchCoefficient(captain) ||
              starter !== captain - squad
            );
          })
          .map((p) => p.id);
        expect(drifted).toEqual([]);
      });

      const kinds: Array<[Kind, string]> = [
        ["saf-puan", "the pure-points plan"],
        ["rival", "a rival strategy (vs-*)"],
        ["top100", "a Top 100 weight (top100-*)"],
      ];
      for (const [kind, label] of kinds) {
        const shipped = tree.cases.filter((c) => c.kind === kind);
        if (shipped.length === 0) {
          it.skip(`${label}: no member's index names such a document, so none is solved`, () => {});
          continue;
        }
        it.each(shipped.map((c) => [c.entryId, c.path, c] as const))(
          `entry %i, ${label}, %s is the device's answer`,
          (_, __, c) => {
            if (!isDevicePlanDocument(document) || !isDevicePlanEntry(c.squad.device_plan)) {
              throw new Error("the tree's device inputs are not the published shapes");
            }
            expect(document.source_snapshot_id).toBe(c.published.source_snapshot_id);
            expect(document.source_snapshot_id).toBe(c.squad.source_snapshot_id);
            const answer = solveRequest(solver, {
              document,
              entry: c.squad.device_plan,
              ...c.request,
            });
            expectPublished(document, c, answer);
          },
          60_000,
        );
      }

      if (tree.declined.length === 0) {
        it.skip("declined by contract: the indexes name no document the device declines", () => {});
      } else {
        it.each(tree.declined.map((d) => [d.entryId, d.path, d.reason, d] as const))(
          "entry %i, %s is declined by contract: %s",
          (_, __, reason, d) => {
            // The page offers no device solve for it, so the published document is shown:
            // without the member's inputs nothing is offered, and otherwise the device's
            // own selection rule declines the request.
            if (reason === NO_MEMBER_INPUTS) {
              expect(isDevicePlanEntry(d.squad.device_plan)).toBe(false);
              return;
            }
            // Declined, not missing: the publish wrote what its index names.
            expect(existsSync(join(ROOT, d.path))).toBe(true);
            expect(deviceSelection(d.request, d.squad)).toBeNull();
            if (reason !== RIVAL_WITH_WEIGHT) return;
            // And the solve itself refuses the combination, whatever rival it is given.
            if (!isDevicePlanDocument(document) || !isDevicePlanEntry(d.squad.device_plan)) {
              throw new Error("the tree's device inputs are not the published shapes");
            }
            const strategy = d.request.strategy;
            if (!isRivalStrategy(strategy)) throw new Error(`not a rival strategy: ${strategy}`);
            expect(() =>
              solveRequest(solver, {
                document,
                entry: d.squad.device_plan as DevicePlanEntry,
                strategy: {
                  name: strategy,
                  rival: { entry_id: d.request.rivalEntryId!, starting_xi: [], captain: 0 },
                },
                top100Weight: d.request.top100Weight,
              }),
            ).toThrow(DevicePlanRefused);
          },
        );
      }
    });
  }
});
