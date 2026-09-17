/** Raw URL parsing and the single index-authoritative member advice resolver. */

import { isPlayMode, type WindowSize } from "../../moves/modePrices";
import {
  isMemberStrategy,
  strategyNeedsRival,
  type AdviceStrategy,
  type EntryAdviceIndex,
  type EntryView,
  type MemberStrategy,
} from "../types";
import type { AdviceRequest } from "./adviceClient";
import { TOP100_WEIGHTS, parseTop100, top100Path, type Top100Weight } from "./top100";

/**
 * The windows the producer published for a strategy, from the index. A tree from
 * before the windows existed names its explicit `window`; no index names no windows.
 */
export function availableWindows(
  index: EntryAdviceIndex | null | undefined,
  strategy: AdviceStrategy,
): WindowSize[] {
  if (!index?.strategies?.includes(strategy)) return [];
  const windows = index.windows === undefined ? [index.window] : (index.windows[strategy] ?? []);
  return [
    ...new Set(
      windows.filter(
        (window) =>
          [1, 3, 5].includes(window) &&
          !index.unavailable?.some(
            (row) =>
              row.strategy === strategy &&
              row.rival_entry_id === null &&
              (row.window ?? index.window) === window,
          ),
      ),
    ),
  ];
}

/** The members a rival can be chosen from: the league's other human entries. */
export function rivalCandidates(members: EntryView[], entryId: number): EntryView[] {
  return members.filter((member) => member.member_kind === "human" && member.entry_id !== entryId);
}

/** The window the URL asks for, before the index has had a say. */
export function requestedWindow(searchParams: URLSearchParams): WindowSize {
  const raw = Number(searchParams.get("window"));
  return raw === 3 ? 3 : raw === 5 ? 5 : 1;
}

function selectedStrategy(searchParams: URLSearchParams): AdviceStrategy {
  const rawMode = searchParams.get("mode");
  return isMemberStrategy(rawMode) ? rawMode : isPlayMode(rawMode) ? rawMode : "saf-puan";
}

export function selectedAdviceRequest(
  searchParams: URLSearchParams,
  leagueId: number,
  entryId: number,
  members: EntryView[],
  context?: { season: string; gameweek: number },
  defaultRivalEntryId: number | null = null,
): AdviceRequest {
  const strategy: AdviceStrategy = selectedStrategy(searchParams);
  const window: WindowSize = requestedWindow(searchParams);
  const candidates = rivalCandidates(members, entryId);
  const isCandidate = (id: number) =>
    Number.isInteger(id) && candidates.some((member) => member.entry_id === id);
  const rawRival = Number(searchParams.get("rival"));
  let rivalEntryId: number | null = null;
  if (strategy !== "saf-puan" && isCandidate(rawRival)) {
    rivalEntryId = rawRival;
  } else if (
    strategyNeedsRival(strategy) &&
    defaultRivalEntryId !== null &&
    isCandidate(defaultRivalEntryId)
  ) {
    rivalEntryId = defaultRivalEntryId;
  }
  return { leagueId, entryId, strategy, window, rivalEntryId, ...context };
}

/**
 * The combinations connected to the application compute path: pure points at any of
 * its windows, or a one-week member strategy with a rival named. A rival strategy at a
 * longer window and the legacy play modes are shown from the published tree only.
 */
export function canComputeAdvice(request: AdviceRequest): boolean {
  if (request.strategy === "saf-puan") return true;
  if (request.window !== 1) return false;
  return isMemberStrategy(request.strategy) && request.rivalEntryId != null;
}

export type PublishedAdviceStatus =
  "ready" | "index-missing" | "index-error" | "not-listed" | "declared-unavailable";

export interface PublishedAdviceSelection {
  request: AdviceRequest;
  status: PublishedAdviceStatus;
  path: string | null;
  reason: string | null;
  strategies: MemberStrategy[];
  windows: WindowSize[];
  rivals: { entryId: number; path: string | null; reason: string | null }[];
  /**
   * The manager's word: whether this publish solved the switched-on plan for the member
   * (`available`), whether the URL asked for it and the selection can honour it (`on`,
   * true only on the one-week pure-points plan), and what the words came from. A switch
   * the index cannot honour is reported with the producer's reason, never flipped silently.
   */
  evidence: {
    available: boolean;
    on: boolean;
    reason: string | null;
    sourceKind: string | null;
    appliedCount: number | null;
  };
  /**
   * The Top 100 influence: whether this publish solved any weight for the member
   * (`available`), the weights that can be shown with the manager's word as it stands
   * (`weights`, zero always among them), the weight the page is showing (`weight`, zero
   * unless its file exists for this selection), whether the URL asked for something the
   * page cannot show (`notOffered`), and the producer's reason when nothing was solved.
   */
  top100: {
    available: boolean;
    weights: Top100Weight[];
    weight: Top100Weight;
    notOffered: boolean;
    reason: string | null;
  };
}

/** The URL parameter that switches the manager's word on: `llm=on`. */
export const EVIDENCE_PARAMETER = "llm";
const EVIDENCE_OFF = {
  available: false,
  on: false,
  reason: null,
  sourceKind: null,
  appliedCount: null,
} as const;

const TOP100_OFF = {
  available: false,
  weights: [0],
  weight: 0,
  notOffered: false,
  reason: null,
} as const satisfies PublishedAdviceSelection["top100"];

/**
 * The weights whose file the index names at the one path it may name, for this member,
 * with or without the manager's word. A path anywhere else is not a file this page reads.
 */
function top100Weights(index: EntryAdviceIndex, entryId: number, word: boolean): Top100Weight[] {
  const menu = index.top100;
  if (!menu || menu.available !== true) return [0];
  const paths = word ? menu.word_paths : menu.paths;
  if (!paths || typeof paths !== "object") return [0];
  return TOP100_WEIGHTS.filter(
    (weight) => weight === 0 || paths[String(weight)] === top100Path(entryId, weight, word),
  );
}

/** One authority for controls, templates, static reads and the compute button. */
export function resolvePublishedAdvice(
  searchParams: URLSearchParams,
  leagueId: number,
  entryId: number,
  members: EntryView[],
  index: EntryAdviceIndex | null | undefined,
  context?: { season: string; gameweek: number },
): PublishedAdviceSelection {
  const request = selectedAdviceRequest(searchParams, leagueId, entryId, members, context);
  const result: PublishedAdviceSelection = {
    request,
    status: "index-missing",
    path: null,
    reason: null,
    strategies: [],
    windows: [],
    rivals: [],
    evidence: { ...EVIDENCE_OFF },
    top100: { ...TOP100_OFF, weights: [...TOP100_OFF.weights] },
  };
  if (!index) return result;
  if (
    index.league_id !== leagueId ||
    index.entry_id !== entryId ||
    (context && (index.season !== context.season || index.gameweek !== context.gameweek)) ||
    !Array.isArray(index.strategies) ||
    !Array.isArray(index.rival_entry_ids) ||
    !Array.isArray(index.computed) ||
    !Array.isArray(index.unavailable) ||
    (index.windows !== undefined &&
      (index.windows === null ||
        typeof index.windows !== "object" ||
        Object.values(index.windows).some((windows) => !Array.isArray(windows)))) ||
    index.computed.some(
      (row) => !row || typeof row.strategy !== "string" || typeof row.path !== "string",
    ) ||
    index.unavailable.some(
      (row) => !row || typeof row.strategy !== "string" || typeof row.reason !== "string",
    )
  ) {
    return { ...result, status: "index-error" };
  }
  result.status = "not-listed";
  const evidenceIndex = index.evidence;
  const evidencePath =
    evidenceIndex && evidenceIndex.available === true && typeof evidenceIndex.path === "string"
      ? evidenceIndex.path
      : null;
  const evidenceAsked = searchParams.get(EVIDENCE_PARAMETER) === "on";
  result.evidence =
    evidencePath !== null && evidenceIndex && evidenceIndex.available === true
      ? {
          available: true,
          on: false,
          reason: null,
          sourceKind: evidenceIndex.source_kind ?? null,
          appliedCount: evidenceIndex.applied_count ?? null,
        }
      : {
          ...EVIDENCE_OFF,
          reason: evidenceIndex && evidenceIndex.available === false ? evidenceIndex.reason : null,
        };
  const top100Index = index.top100;
  const top100Asked = parseTop100(searchParams);
  result.top100 = {
    ...TOP100_OFF,
    weights: [0],
    available: top100Index?.available === true && top100Weights(index, entryId, false).length > 1,
    notOffered: !top100Asked.offered,
    reason: top100Index && top100Index.available === false ? top100Index.reason : null,
  };
  result.strategies = [...new Set(index.strategies.filter(isMemberStrategy))];
  result.windows = availableWindows(index, request.strategy);
  const { strategy, window } = request;
  if (strategyNeedsRival(strategy)) {
    const rivalIds = [
      ...new Set(
        index.rival_entry_ids.filter((id) => Number.isSafeInteger(id) && id > 0 && id !== entryId),
      ),
    ];
    result.rivals = rivalIds.map((rivalEntryId) => {
      const expectedPath = `advice/${entryId}/${strategy}/${window}/vs-${rivalEntryId}.json`;
      const declared = index.unavailable.find(
        (row) =>
          row.strategy === strategy &&
          row.rival_entry_id === rivalEntryId &&
          (row.window ?? index.window) === window,
      );
      const computed = index.computed.filter(
        (row) =>
          row.strategy === strategy &&
          row.rival_entry_id === rivalEntryId &&
          row.path === expectedPath,
      );
      return {
        entryId: rivalEntryId,
        path: !declared && computed.length === 1 ? expectedPath : null,
        reason: declared?.reason ?? null,
      };
    });
    const rawRival = searchParams.get("rival");
    const rivalEntryId = rawRival === null ? index.default_rival_entry_id : Number(rawRival);
    request.rivalEntryId =
      rivalEntryId !== null && rivalIds.includes(rivalEntryId) ? rivalEntryId : null;
  } else {
    request.rivalEntryId = null;
  }
  const mode = searchParams.get("mode");
  const rawWindow = searchParams.get("window");
  if (
    (mode !== null && !isMemberStrategy(mode)) ||
    !isMemberStrategy(strategy) ||
    !result.strategies.includes(strategy) ||
    (rawWindow !== null && !["1", "3", "5"].includes(rawWindow))
  )
    return result;
  const declared = index.unavailable.find(
    (row) =>
      row.strategy === strategy &&
      row.rival_entry_id === (request.rivalEntryId ?? null) &&
      (row.window ?? index.window) === window,
  );
  if (declared) return { ...result, status: "declared-unavailable", reason: declared.reason };
  if (!result.windows.includes(window)) return result;
  if (strategy === "saf-puan") {
    // The word is solved for the one-week pure-points plan only; asked for anywhere
    // else, the switch stays off and the controls say why.
    const switched = evidenceAsked && evidencePath !== null && window === 1;
    // The Top 100 menu is the same one-week plan at another weight. A weight whose file
    // this selection cannot read shows the published plan, and the controls say so.
    const weights = window === 1 ? top100Weights(index, entryId, switched) : [0 as const];
    const asked = top100Asked.weight;
    const weight = weights.includes(asked) ? asked : 0;
    const top100 = {
      ...result.top100,
      weights,
      weight,
      notOffered: result.top100.notOffered || (asked !== 0 && weight === 0),
    };
    return {
      ...result,
      status: "ready",
      path:
        weight !== 0
          ? top100Path(entryId, weight, switched)
          : switched
            ? evidencePath
            : `advice/${entryId}/saf-puan/${window}.json`,
      evidence: { ...result.evidence, on: switched },
      top100,
    };
  }
  const rival = result.rivals.find((row) => row.entryId === request.rivalEntryId);
  if (!rival?.path) return result;
  return { ...result, status: "ready", path: rival.path };
}
