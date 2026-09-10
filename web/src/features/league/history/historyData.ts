import { withRequestDeadline, type RequestOptions } from "../../../data/request";
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";

export interface WeeklyScore {
  gross_points: number;
  transfer_hit_points: number;
  net_points: number;
}

export interface SuggestedScore extends WeeklyScore {
  captain_bonus_points: number;
  autosub_points: number;
  chip: "wildcard" | "freehit" | "bboost" | "3xc" | null;
}

export interface PlayerReview {
  player_id: number;
  name: string;
  position: "GK" | "DEF" | "MID" | "FWD";
  role: "starter" | "bench";
  captain: boolean;
  vice_captain: boolean;
  expected_points: number | null;
  realized_points: number;
  minutes: number;
  multiplier: number;
  counted_points: number;
  forecast_error: number | null;
}

export interface WeekReview {
  gameweek: number;
  status: "available" | "unsettled" | "unavailable";
  reason: string | null;
  deadline_utc: string | null;
  advice_snapshot_id: string | null;
  advice_captured_at_utc: string | null;
  advice_generated_at_utc: string | null;
  advice_sha256: string | null;
  outcome_snapshot_id: string | null;
  outcome_captured_at_utc: string | null;
  expected_own_points: number | null;
  suggested: SuggestedScore | null;
  actual: WeeklyScore | null;
  actual_reason: string | null;
  net_difference: number | null;
  players: PlayerReview[];
}

export interface SuggestionHistory {
  contract_version: "weekly_suggestion_history_v1";
  generated_at_utc: string;
  payload: {
    league_id: 352490;
    entry_id: number;
    season: string;
    as_of_snapshot_id: string;
    weeks: WeekReview[];
  };
}

function requireThat(condition: unknown): asserts condition {
  if (!condition) throw new LeagueDataError("The weekly suggestion history is inconsistent.");
}
function object(value: unknown): Record<string, unknown> {
  requireThat(typeof value === "object" && value !== null && !Array.isArray(value));
  return value as Record<string, unknown>;
}
const number = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const nullableNumber = (value: unknown) => value === null || number(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const stamp = (value: unknown): value is string =>
  text(value) && /Z$/.test(value) && Number.isFinite(Date.parse(value));
const same = (left: number, right: number) => Math.abs(left - right) < 1e-8;

function score(value: unknown): WeeklyScore {
  const row = object(value);
  requireThat(
    number(row.gross_points) && number(row.transfer_hit_points) && number(row.net_points),
  );
  requireThat(
    row.transfer_hit_points >= 0 &&
      same(row.gross_points - row.transfer_hit_points, row.net_points),
  );
  return row as unknown as WeeklyScore;
}

/** Validate identity, settled state and published arithmetic before displaying a score. */
export function checkedHistory(value: unknown, entryId: number): SuggestionHistory {
  const envelope = object(value);
  requireThat(
    envelope.contract_version === "weekly_suggestion_history_v1" &&
      stamp(envelope.generated_at_utc),
  );
  const payload = object(envelope.payload);
  requireThat(
    payload.league_id === 352490 &&
      payload.entry_id === entryId &&
      Number.isSafeInteger(entryId) &&
      entryId > 0,
  );
  requireThat(
    text(payload.season) && /^\d{4}-\d{2}$/.test(payload.season) && text(payload.as_of_snapshot_id),
  );
  requireThat(Array.isArray(payload.weeks));
  const seen = new Set<number>();
  for (const item of payload.weeks) {
    const row = object(item);
    requireThat(
      number(row.gameweek) &&
        Number.isInteger(row.gameweek) &&
        row.gameweek > 0 &&
        !seen.has(row.gameweek),
    );
    seen.add(row.gameweek);
    requireThat(["available", "unsettled", "unavailable"].includes(String(row.status)));
    requireThat(nullableNumber(row.expected_own_points) && nullableNumber(row.net_difference));
    requireThat(row.reason === null || text(row.reason));
    requireThat(row.actual_reason === null || text(row.actual_reason));
    for (const key of [
      "deadline_utc",
      "advice_captured_at_utc",
      "advice_generated_at_utc",
      "outcome_captured_at_utc",
    ]) {
      requireThat(row[key] === null || stamp(row[key]));
    }
    for (const key of ["advice_snapshot_id", "outcome_snapshot_id"])
      requireThat(row[key] === null || text(row[key]));
    requireThat(
      row.advice_sha256 === null ||
        (text(row.advice_sha256) && /^[a-f0-9]{64}$/.test(row.advice_sha256)),
    );
    requireThat(Array.isArray(row.players));
    if (row.status !== "available") {
      requireThat(
        text(row.reason) &&
          row.suggested === null &&
          row.actual === null &&
          row.net_difference === null &&
          row.players.length === 0,
      );
      continue;
    }
    requireThat(
      row.reason === null &&
        stamp(row.deadline_utc) &&
        stamp(row.advice_generated_at_utc) &&
        stamp(row.advice_captured_at_utc),
    );
    requireThat(
      Date.parse(row.advice_captured_at_utc) <= Date.parse(row.advice_generated_at_utc) &&
        Date.parse(row.advice_generated_at_utc) < Date.parse(row.deadline_utc),
    );
    requireThat(
      stamp(row.outcome_captured_at_utc) &&
        Date.parse(row.outcome_captured_at_utc) >= Date.parse(row.deadline_utc),
    );
    requireThat(
      text(row.advice_snapshot_id) && text(row.advice_sha256) && text(row.outcome_snapshot_id),
    );
    const suggested = score(row.suggested);
    const detail = object(row.suggested);
    requireThat(number(detail.captain_bonus_points) && number(detail.autosub_points));
    requireThat(
      [null, "wildcard", "freehit", "bboost", "3xc"].includes(detail.chip as string | null),
    );
    if (row.actual !== null) {
      const actual = score(row.actual);
      requireThat(
        row.actual_reason === null &&
          number(row.net_difference) &&
          same(row.net_difference, suggested.net_points - actual.net_points),
      );
    } else requireThat(text(row.actual_reason) && row.net_difference === null);
    const players = new Set<number>();
    let counted = 0;
    for (const value of row.players) {
      const player = object(value);
      requireThat(
        number(player.player_id) &&
          Number.isSafeInteger(player.player_id) &&
          player.player_id > 0 &&
          !players.has(player.player_id),
      );
      players.add(player.player_id);
      requireThat(
        text(player.name) && ["GK", "DEF", "MID", "FWD"].includes(String(player.position)),
      );
      requireThat(
        ["starter", "bench"].includes(String(player.role)) &&
          typeof player.captain === "boolean" &&
          typeof player.vice_captain === "boolean",
      );
      requireThat(
        number(player.minutes) && Number.isInteger(player.minutes) && player.minutes >= 0,
      );
      requireThat(
        number(player.multiplier) &&
          Number.isInteger(player.multiplier) &&
          player.multiplier >= 0 &&
          player.multiplier <= 3,
      );
      requireThat(
        number(player.realized_points) &&
          number(player.counted_points) &&
          same(player.counted_points, player.realized_points * player.multiplier),
      );
      requireThat(nullableNumber(player.expected_points) && nullableNumber(player.forecast_error));
      requireThat(
        player.expected_points === null
          ? player.forecast_error === null
          : number(player.forecast_error) &&
              same(
                player.forecast_error,
                player.realized_points - (player.expected_points as number),
              ),
      );
      counted += player.counted_points;
    }
    requireThat(players.size === 15 && same(counted, suggested.gross_points));
  }
  return envelope as unknown as SuggestionHistory;
}

export async function loadSuggestionHistory(
  entryId: number,
  options?: RequestOptions,
): Promise<SuggestionHistory> {
  requireThat(Number.isSafeInteger(entryId) && entryId > 0);
  const relative = `data/league/history/${entryId}.json`;
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${import.meta.env.BASE_URL}${relative}`, {
      cache: "no-cache",
      signal,
    });
    if (response.status === 404) throw new LeagueDataMissing(relative);
    if (!response.ok) throw new LeagueDataError(`History unavailable (${response.status}).`);
    const body = await response.text();
    if (/^\s*(?:<!doctype\s+html\b|<html\b)/i.test(body)) throw new LeagueDataMissing(relative);
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      throw new LeagueDataError("History is not valid JSON.");
    }
    return checkedHistory(parsed, entryId);
  }, options);
}
