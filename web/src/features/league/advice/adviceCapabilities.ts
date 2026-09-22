/**
 * What the compute service will answer right now: `league_capabilities_v1`, checked.
 *
 * The published index says what was solved and written to the static tree. This document
 * is the other authority, and only a build with a configured service ever reads it: the
 * strategies and windows the service computes, and whether the current capture has the
 * input the Top 100 setting and the manager's word are each computed from. It is validated
 * like every other document the page reads; a shape this module does not recognise is no
 * capabilities at all, and the page stays what the static site is.
 *
 * The contract names no windows per switch, so the two rules the service applies are
 * written here once: a Top 100 setting may be asked wherever the plan itself may, and the
 * manager's word on the one-week pure-points plan only.
 */

import type { WindowSize } from "../../moves/modePrices";
import { LeagueDataError } from "../data";
import { isMemberChip, type MemberChip } from "./chipChoice";
import { isTop100Weight, type Top100Weight } from "./top100";

export const LEAGUE_CAPABILITIES_CONTRACT = "league_capabilities_v1";

export interface StrategyCapability {
  windows: WindowSize[];
  requiresRival: boolean;
}

export interface AdviceCapabilities {
  leagueId: number;
  captureSnapshotId: string;
  season: string;
  gameweek: number;
  strategies: Record<string, StrategyCapability>;
  /** The settings the service would accept now; zero is always one of them. */
  models?: ("current" | "football")[];
  top100Weights: Top100Weight[];
  managersWord: boolean;
  /** Missing member means unknown history; an empty list means no held chips. */
  chipStrategyWindows?: WindowSize[];
  chipsByEntry?: Record<string, MemberChip[]>;
}

export class AdviceCapabilitiesError extends LeagueDataError {}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isWindow(value: unknown): value is WindowSize {
  return value === 1 || value === 3 || value === 5;
}

/** The document as the page uses it, or an error naming the first thing that is wrong. */
export function checkedCapabilities(value: unknown, leagueId: number): AdviceCapabilities {
  if (!record(value) || value.contract_version !== LEAGUE_CAPABILITIES_CONTRACT) {
    throw new AdviceCapabilitiesError("Not a league capabilities document.");
  }
  if (value.league_id !== leagueId) {
    throw new AdviceCapabilitiesError("The capabilities answer another league.");
  }
  if (
    typeof value.capture_snapshot_id !== "string" ||
    !value.capture_snapshot_id ||
    typeof value.season !== "string" ||
    !value.season ||
    !Number.isSafeInteger(value.gameweek) ||
    (value.gameweek as number) < 1
  ) {
    throw new AdviceCapabilitiesError("The capabilities name no capture, season or gameweek.");
  }
  if (!record(value.strategies) || !record(value.top100) || !record(value.managers_word)) {
    throw new AdviceCapabilitiesError("The capabilities have no strategies or switches.");
  }
  const strategies: Record<string, StrategyCapability> = {};
  for (const [slug, row] of Object.entries(value.strategies)) {
    if (
      !record(row) ||
      typeof row.requires_rival !== "boolean" ||
      !Array.isArray(row.windows) ||
      !row.windows.every(isWindow)
    ) {
      throw new AdviceCapabilitiesError(`Strategy ${slug} has an invalid capability.`);
    }
    strategies[slug] = {
      windows: [...new Set(row.windows as WindowSize[])],
      requiresRival: row.requires_rival,
    };
  }
  const { available, weights } = value.top100;
  if (
    typeof available !== "boolean" ||
    !Array.isArray(weights) ||
    !weights.every((weight) => Number.isSafeInteger(weight)) ||
    typeof value.managers_word.available !== "boolean"
  ) {
    throw new AdviceCapabilitiesError("The capabilities state a switch this page cannot read.");
  }
  // A setting this page has no radio for is not offered here; zero needs no offer.
  const offered = available ? weights.filter(isTop100Weight).filter((weight) => weight !== 0) : [];
  let chipStrategyWindows: WindowSize[] | undefined;
  let chipsByEntry: Record<string, MemberChip[]> | undefined;
  if (value.chips !== undefined) {
    if (!record(value.chips) || !record(value.chips.held_by_entry)) {
      throw new AdviceCapabilitiesError("The capabilities have no member chip list.");
    }
    if (value.chips.strategy !== undefined) {
      const strategy = value.chips.strategy;
      if (
        !record(strategy) ||
        strategy.version !== "model_opportunity_reservation_v1" ||
        !Array.isArray(strategy.windows) ||
        !strategy.windows.every(isWindow)
      )
        throw new AdviceCapabilitiesError("Invalid chip strategy capabilities.");
      chipStrategyWindows = [...new Set(strategy.windows as WindowSize[])];
    }
    chipsByEntry = {};
    for (const [entry, chips] of Object.entries(value.chips.held_by_entry)) {
      if (
        !/^[1-9][0-9]*$/.test(entry) ||
        !Number.isSafeInteger(Number(entry)) ||
        !Array.isArray(chips) ||
        !chips.every(isMemberChip) ||
        new Set(chips).size !== chips.length
      ) {
        throw new AdviceCapabilitiesError("The capabilities have an invalid member chip list.");
      }
      chipsByEntry[entry] = chips;
    }
  }
  if (
    value.models !== undefined &&
    (!Array.isArray(value.models) ||
      !value.models.every((m) => m === "current" || m === "football"))
  )
    throw new AdviceCapabilitiesError("Invalid model capabilities.");
  return {
    ...(value.models === undefined ? {} : { models: value.models as ("current" | "football")[] }),
    leagueId,
    captureSnapshotId: value.capture_snapshot_id,
    season: value.season,
    gameweek: value.gameweek as number,
    strategies,
    top100Weights: [0, ...new Set(offered)],
    managersWord: value.managers_word.available,
    ...(chipStrategyWindows === undefined ? {} : { chipStrategyWindows }),
    ...(chipsByEntry === undefined ? {} : { chipsByEntry }),
  };
}

/**
 * The capabilities, if they speak about the page on screen: the same league, season and
 * gameweek, and the same capture as the squad shown. A service working from another
 * capture would answer with a plan this page has to refuse, minutes later; saying so
 * before the request is the kinder order.
 */
export function capabilitiesForPage(
  capabilities: AdviceCapabilities | null | undefined,
  page: { leagueId: number; season: string; gameweek: number; snapshotId?: string | null },
): AdviceCapabilities | null {
  if (!capabilities) return null;
  if (
    capabilities.leagueId !== page.leagueId ||
    capabilities.season !== page.season ||
    capabilities.gameweek !== page.gameweek
  ) {
    return null;
  }
  if (page.snapshotId != null && capabilities.captureSnapshotId !== page.snapshotId) return null;
  return capabilities;
}
