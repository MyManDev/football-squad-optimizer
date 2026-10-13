/**
 * The capture's device-plan tables the committed site's directory names (#981 step 2),
 * held to what the page does with them. Once a line names a table, the page solves from
 * it instead of the tree's copy, and every refusal falls back to the copy without a word,
 * so a table the page would refuse ships unnoticed until the copy stops. A line that names
 * one must name it the way the page reads it; the file must be there with the sha256 the
 * line names; its envelope and payload must pass the page's validators as the table's
 * contract, for the capture its path names; and the table without its own fields must be
 * the tree's copy without its league, so the parity the copy is held to
 * (`planModel.shipped.test.ts`) carries over to the table. The copy stops with #981 step
 * 8; a missing copy is a finding until then, because that parity test skips a tree with
 * no copy.
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { isDeepStrictEqual } from "node:util";

import {
  DEVICE_PLAN_CONTRACT_VERSION,
  DEVICE_PLAN_TABLE_CONTRACT_VERSION,
  isDevicePlanDocument,
} from "../features/league/device/types";
import { devicePlanTable } from "../features/league/directory";
import { assertEnvelope } from "../features/league/publicationShape";
import { PUBLIC_ROOT } from "./shippedTrees";

/** A directory line that names a device-plan table, or names its digest. */
export interface DevicePlanLine {
  leagueId: unknown;
  /** The league's tree under `data/`, whose `device-plan.json` is the copy. */
  path: string;
  devicePlan: unknown;
  sha256: unknown;
}

/** Every line of the site's directory that names a table or a digest; none without one. */
export function shippedDevicePlanLines(publicRoot: string = PUBLIC_ROOT): DevicePlanLine[] {
  const directory = join(publicRoot, "data", "leagues.json");
  if (!existsSync(directory)) return [];
  const document = JSON.parse(readFileSync(directory, "utf-8")) as {
    payload?: { leagues?: Record<string, unknown>[] };
  };
  return (document.payload?.leagues ?? [])
    .filter((line) => line.device_plan !== undefined || line.device_plan_sha256 !== undefined)
    .map((line) => ({
      leagueId: line.league_id,
      path: String(line.path),
      devicePlan: line.device_plan,
      sha256: line.device_plan_sha256,
    }));
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The table without the fields the copy does not carry, and without its contract. */
function withoutTableFields(payload: Record<string, unknown>): Record<string, unknown> {
  const { contract_version: _version, rules, players, ...rest } = payload;
  const { chips: _chips, transfers_cap: _cap, ...sharedRules } = record(rules) ? rules : {};
  return {
    ...rest,
    rules: sharedRules,
    players: (Array.isArray(players) ? players : []).map((player: unknown) => {
      if (!record(player)) return player;
      const { element_id: _element, start_tenths: _start, ...shared } = player;
      return shared;
    }),
  };
}

/** The copy without its league, and without its contract. */
function withoutLeague(payload: Record<string, unknown>): Record<string, unknown> {
  const { contract_version: _version, league_id: _league, ...rest } = payload;
  return rest;
}

/** The top-level fields that differ, with the first player that differs. */
function differences(table: Record<string, unknown>, copy: Record<string, unknown>): string[] {
  const keys = [...new Set([...Object.keys(table), ...Object.keys(copy)])].sort();
  return keys
    .filter((key) => !isDeepStrictEqual(table[key], copy[key]))
    .map((key) => {
      const [left, right] = [table[key], copy[key]];
      if (key !== "players" || !Array.isArray(left) || !Array.isArray(right)) return key;
      const index = left.findIndex((player, at) => !isDeepStrictEqual(player, right[at]));
      return index < 0 ? `players (${left.length} against ${right.length})` : `players[${index}]`;
    });
}

/** What is wrong with the table a line names, as the page would meet it; empty when nothing. */
export function devicePlanTableProblems(
  line: DevicePlanLine,
  publicRoot: string = PUBLIC_ROOT,
): string[] {
  const table = devicePlanTable(line.devicePlan, line.sha256);
  if (table === undefined) {
    return [
      `names ${JSON.stringify(line.devicePlan)} with sha256 ${JSON.stringify(line.sha256)}, ` +
        "which the page does not read",
    ];
  }
  const file = join(publicRoot, "data", ...table.path.split("/"));
  if (!existsSync(file)) return [`${table.path} is missing`];
  const bytes = readFileSync(file);
  const problems: string[] = [];
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (digest !== table.sha256) {
    problems.push(`${table.path} has sha256 ${digest}, the line names ${table.sha256}`);
  }
  let payload: unknown;
  try {
    payload = assertEnvelope<unknown>(JSON.parse(bytes.toString("utf-8"))).payload;
  } catch (error) {
    return [...problems, `${table.path}: ${(error as Error).message}`];
  }
  if (
    !isDevicePlanDocument(payload) ||
    payload.contract_version !== DEVICE_PLAN_TABLE_CONTRACT_VERSION
  ) {
    return [
      ...problems,
      `${table.path} is not a ${DEVICE_PLAN_TABLE_CONTRACT_VERSION} document the page accepts`,
    ];
  }
  const capture = table.path.split("/")[1];
  if (payload.source_snapshot_id !== capture) {
    problems.push(`${table.path} holds capture ${payload.source_snapshot_id}`);
  }
  const copyFile = join(publicRoot, "data", ...line.path.split("/"), "device-plan.json");
  if (!existsSync(copyFile)) {
    return [...problems, `${line.path}/device-plan.json, the tree's copy, is missing`];
  }
  const copy = assertEnvelope<unknown>(JSON.parse(readFileSync(copyFile, "utf-8"))).payload;
  if (!isDevicePlanDocument(copy) || copy.contract_version !== DEVICE_PLAN_CONTRACT_VERSION) {
    return [...problems, `${line.path}/device-plan.json is not a copy the page accepts`];
  }
  const changed = differences(
    withoutTableFields(payload as unknown as Record<string, unknown>),
    withoutLeague(copy as unknown as Record<string, unknown>),
  );
  if (changed.length > 0) {
    problems.push(
      `${table.path} without its own fields is not ${line.path}/device-plan.json without its ` +
        `league: ${changed.join(", ")} differ`,
    );
  }
  return problems;
}
