import { withRequestDeadline } from "../../../data/request";
import { LeagueDataError } from "../dataErrors";
import type { Scoreboard } from "../types";
import { checkedHistory, loadSuggestionHistory, type SuggestionHistory } from "./historyData";

export const SERIES_BASIS = "official_autosub_captain_v2";
export const SERIES_POPULATION = "recorded_member_suggestions_vs_actual";

/** One immutable advice/outcome pair per member-week; never the paper ledger. */
export function summarizeLiveSeries(histories: SuggestionHistory[], view: Scoreboard) {
  const seen = new Set<number>();
  const rows = histories
    .flatMap((document) => {
      const history = checkedHistory(document, document.payload.entry_id).payload;
      if (
        history.season !== view.season ||
        history.as_of_snapshot_id !== view.source_snapshot_id ||
        history.league_id !== view.league_id ||
        seen.has(history.entry_id)
      ) {
        throw new LeagueDataError(
          "The member series mixes captures, seasons or duplicate members.",
        );
      }
      seen.add(history.entry_id);
      return history.weeks.flatMap((week) => {
        const settled = view.gameweeks.some(
          (row) => row.gameweek === week.gameweek && row.finished && row.data_checked,
        );
        if (
          !settled ||
          week.status !== "available" ||
          week.suggested === null ||
          week.actual === null ||
          week.net_difference === null
        )
          return [];
        return [
          {
            entryId: history.entry_id,
            gameweek: week.gameweek,
            suggested: week.suggested.net_points,
            actual: week.actual.net_points,
            difference: week.net_difference,
            recordKey: `${history.entry_id}:${week.gameweek}:${week.advice_sha256}:${week.outcome_snapshot_id}`,
          },
        ];
      });
    })
    .sort((a, b) => a.gameweek - b.gameweek || a.entryId - b.entryId);
  const gameweeks = [...new Set(rows.map((row) => row.gameweek))];
  const weeks = gameweeks.map((gameweek) => {
    const group = rows.filter((row) => row.gameweek === gameweek);
    return {
      gameweek,
      members: group.length,
      meanDifference: group.reduce((sum, row) => sum + row.difference, 0) / group.length,
    };
  });
  return {
    rows,
    weeks,
    memberWeeks: rows.length,
    weekClusters: weeks.length,
    meanDifference: rows.length
      ? rows.reduce((sum, row) => sum + row.difference, 0) / rows.length
      : null,
  };
}

export type LiveSeries = ReturnType<typeof summarizeLiveSeries>;

/**
 * The measurement owner supplies the horizon: docs/contracts/member_week_horizon_v1.md.
 * Correlation is required evidence that within-week dependence was measured. It is
 * validated here, never defaulted, displayed or used to estimate a target in the browser.
 */
export function remainingWeeks(
  value: unknown,
  series: LiveSeries,
  view: Scoreboard,
): number | null {
  if (!value || typeof value !== "object" || series.weekClusters < 2) return null;
  const row = value as Record<string, unknown>;
  const keys = series.rows.map((item) => item.recordKey).sort();
  if (
    row.contract_version !== "member_week_horizon_v1" ||
    row.season !== view.season ||
    row.league_id !== view.league_id ||
    row.scoring_basis !== SERIES_BASIS ||
    row.population !== SERIES_POPULATION ||
    typeof row.measurement_artifact !== "string" ||
    !/^docs\/[a-z0-9_-]+\.json$/.test(row.measurement_artifact) ||
    typeof row.within_week_correlation !== "number" ||
    !Number.isFinite(row.within_week_correlation) ||
    row.within_week_correlation < -1 ||
    row.within_week_correlation > 1 ||
    typeof row.required_week_clusters !== "number" ||
    !Number.isSafeInteger(row.required_week_clusters) ||
    row.required_week_clusters < 2 ||
    !Array.isArray(row.member_week_keys) ||
    !row.member_week_keys.every((key) => typeof key === "string") ||
    JSON.stringify([...row.member_week_keys].sort()) !== JSON.stringify(keys)
  )
    return null;
  return Math.max(0, row.required_week_clusters - series.weekClusters);
}

export async function loadLiveSeries(view: Scoreboard, signal?: AbortSignal) {
  const entries = [
    ...new Set(view.gameweeks.flatMap((week) => week.members.map((row) => row.entry_id))),
  ];
  const results = await Promise.allSettled(
    entries.map((id) => loadSuggestionHistory(id, { signal })),
  );
  signal?.throwIfAborted();
  const histories: SuggestionHistory[] = [];
  for (const result of results) {
    if (result.status !== "fulfilled") continue;
    // A failed/mismatched member publication costs its own rows, never creates a zero.
    try {
      summarizeLiveSeries([result.value], view);
      histories.push(result.value);
    } catch {
      /* counted below */
    }
  }
  const series = summarizeLiveSeries(histories, view);
  let horizon: unknown = null;
  try {
    horizon = await withRequestDeadline(
      async (requestSignal) => {
        const response = await fetch(`${import.meta.env.BASE_URL}data/league/series-horizon.json`, {
          cache: "no-cache",
          signal: requestSignal,
        });
        return response.ok ? await response.json() : null;
      },
      { signal },
    );
  } catch {
    signal?.throwIfAborted();
  }
  return {
    series,
    remaining: remainingWeeks(horizon, series, view),
    unavailableMembers: Math.max(0, view.registered_members - histories.length),
  };
}
