import type { WindowSize } from "../moves/modePrices";
import type {
  EntryAdvice,
  EntrySquad,
  LeagueMembers,
  LeagueViewEnvelope,
  AdviceStrategy,
  EntryAdviceIndex,
  Scoreboard,
} from "./types";

const CONTRACT_VERSION = "provisional_league_ui_v1";
const BASE = `${import.meta.env.BASE_URL}data/league/`;

export class LeagueDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LeagueDataError";
  }
}

/**
 * Raised when the document exists nowhere: the site publishes only the mode and window it
 * actually computed, so asking for another one is a normal outcome rather than a fault.
 */
export class LeagueDataMissing extends LeagueDataError {
  constructor(relative: string) {
    super(`No published league document at ${relative}.`);
    this.name = "LeagueDataMissing";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function nullableNumber(value: unknown): boolean {
  return value === null || finite(value);
}

function publicMember(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    ((value.member_kind === "human" &&
      Number.isSafeInteger(value.entry_id) &&
      Number(value.entry_id) > 0) ||
      (value.member_kind === "system" && value.entry_id === null)) &&
    (value.manager_name === null || typeof value.manager_name === "string") &&
    (value.team_name === null || typeof value.team_name === "string") &&
    finite(value.rank) &&
    nullableNumber(value.gameweek_points) &&
    nullableNumber(value.total_points) &&
    (value.transfer_cost === undefined || nullableNumber(value.transfer_cost)) &&
    typeof value.movement === "string" &&
    ["up", "down", "same", "new", "unknown"].includes(value.movement) &&
    (value.movement_places === undefined || nullableNumber(value.movement_places))
  );
}

function publishedPlayer(value: unknown): boolean {
  return (
    record(value) &&
    Number.isSafeInteger(value.player_id) &&
    Number(value.player_id) > 0 &&
    typeof value.name === "string" &&
    typeof value.short_name === "string" &&
    typeof value.team === "string" &&
    typeof value.position === "string" &&
    ["GK", "DEF", "MID", "FWD"].includes(value.position) &&
    finite(value.expected_points) &&
    typeof value.is_captain === "boolean" &&
    (value.bench_order == null || Number.isSafeInteger(value.bench_order))
  );
}

function assertEnvelope<T>(value: unknown): LeagueViewEnvelope<T> {
  if (
    !record(value) ||
    value.contract_version !== CONTRACT_VERSION ||
    !record(value.payload) ||
    typeof value.generated_at_utc !== "string" ||
    (value.source_kind !== "live" && value.source_kind !== "example")
  ) {
    throw new LeagueDataError("The published league envelope is invalid.");
  }
  return value as unknown as LeagueViewEnvelope<T>;
}

function assertMembers(
  envelope: LeagueViewEnvelope<LeagueMembers>,
): LeagueViewEnvelope<LeagueMembers> {
  const view = envelope.payload;
  if (
    !record(view) ||
    !Number.isSafeInteger(view.league_id) ||
    view.league_id <= 0 ||
    typeof view.league_name !== "string" ||
    typeof view.season !== "string" ||
    !Number.isSafeInteger(view.gameweek) ||
    view.public_after_deadline !== true ||
    (view.scored_gameweek !== null && !Number.isSafeInteger(view.scored_gameweek)) ||
    !Array.isArray(view.members) ||
    !view.members.every(publicMember)
  ) {
    throw new LeagueDataError("The published member list is invalid.");
  }
  return envelope;
}

function assertSquad(
  envelope: LeagueViewEnvelope<EntrySquad>,
  entryId: number,
): LeagueViewEnvelope<EntrySquad> {
  const view = envelope.payload;
  if (
    !record(view) ||
    !publicMember(view.entry) ||
    view.entry.member_kind !== "human" ||
    view.entry.entry_id !== entryId ||
    !Number.isSafeInteger(view.league_id) ||
    view.league_id <= 0 ||
    typeof view.season !== "string" ||
    !Number.isSafeInteger(view.gameweek) ||
    (view.source_snapshot_id !== null && typeof view.source_snapshot_id !== "string") ||
    !Array.isArray(view.starting_xi) ||
    !view.starting_xi.every(publishedPlayer) ||
    !Array.isArray(view.bench) ||
    !view.bench.every(publishedPlayer) ||
    !Array.isArray(view.missing_fields) ||
    !view.missing_fields.every((field) => typeof field === "string") ||
    !["complete", "partial", "empty"].includes(view.data_quality) ||
    typeof view.free_transfers_known !== "boolean" ||
    typeof view.purchase_prices_known !== "boolean" ||
    !finite(view.free_transfers)
  ) {
    throw new LeagueDataError("The published member squad is invalid or belongs to another entry.");
  }
  return envelope;
}

async function read<T>(relative: string): Promise<LeagueViewEnvelope<T>> {
  const response = await fetch(`${BASE}${relative}`, { cache: "no-cache" });
  if (response.status === 404) throw new LeagueDataMissing(relative);
  if (!response.ok) throw new LeagueDataError(`League data is not available (${response.status}).`);
  // Static hosts can return their HTML app shell for an unpublished JSON path.
  // A broken JSON publication is unreadable and must not become an example fallback.
  const body = await response.text();
  let parsed: LeagueViewEnvelope<T>;
  try {
    parsed = JSON.parse(body) as LeagueViewEnvelope<T>;
  } catch {
    if (/^\s*(?:<!doctype\s+html\b|<html\b)/i.test(body)) {
      throw new LeagueDataMissing(relative);
    }
    throw new LeagueDataError(`The published league document at ${relative} is not valid JSON.`);
  }
  return assertEnvelope(parsed);
}

/**
 * The example league is a development and test convenience. The guard is written so the
 * production build can prove the import unreachable: without it the fixture module was
 * emitted as a chunk no production page ever loads, and it still counted against the
 * bundle budget.
 */
async function mockModule() {
  if (!import.meta.env.DEV && import.meta.env.MODE !== "test") {
    throw new Error("Example league data is not bundled in production.");
  }
  return import("../../fixtures/league");
}

/**
 * Read the published document; fall back to the example one only in development, and only
 * when nothing is published.
 *
 * The gate used to be "development means examples", which was right while no league had
 * ever been published and wrong the day one was: a developer looking at the site saw a
 * league that does not exist, with players nobody owns, and had no way to reach the real
 * one short of a production build. Every disagreement between the producer and this side
 * — the file layout, the id space, our own missing row — survived because the surface a
 * developer actually looks at was showing fiction.
 *
 * Tests keep the examples unconditionally: they assert against fixture contents, and a
 * suite whose expectations depend on whether someone has run the producer locally is a
 * suite that fails for reasons unrelated to the change under test.
 */
async function readOrExample<T>(
  relative: string,
  example: () => Promise<LeagueViewEnvelope<T>>,
): Promise<LeagueViewEnvelope<T>> {
  if (import.meta.env.MODE === "test") return example();
  if (!import.meta.env.DEV) return read<T>(relative);
  try {
    return await read<T>(relative);
  } catch (error) {
    if (error instanceof LeagueDataMissing) return example();
    throw error;
  }
}

export async function loadLeagueMembers(): Promise<LeagueViewEnvelope<LeagueMembers>> {
  return assertMembers(
    await readOrExample<LeagueMembers>(
      "members.json",
      async () => (await mockModule()).mockLeagueMembersEnvelope,
    ),
  );
}

export async function loadEntrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>> {
  return assertSquad(
    await readOrExample<EntrySquad>(`entries/${entryId}.json`, async () => {
      const fixture = (await mockModule()).mockEntrySquadEnvelopes[entryId];
      if (!fixture) throw new LeagueDataError(`No example entry ${entryId}.`);
      return fixture;
    }),
    entryId,
  );
}

export async function loadEntryAdvice(
  entryId: number,
  mode: AdviceStrategy,
  window: WindowSize,
  rivalEntryId: number | null = null,
): Promise<LeagueViewEnvelope<EntryAdvice>> {
  // A named rival reads the producer's per-rival file; without one, the plain path —
  // the baseline for saf-puan, the standings neighbour's copy for a rival strategy.
  const relative =
    rivalEntryId === null
      ? `advice/${entryId}/${mode}/${window}.json`
      : `advice/${entryId}/${mode}/${window}/vs-${rivalEntryId}.json`;
  return readOrExample<EntryAdvice>(relative, async () =>
    (await mockModule()).mockEntryAdviceEnvelope(entryId, mode, window, rivalEntryId),
  );
}

export async function loadEntryAdviceIndex(
  entryId: number,
): Promise<LeagueViewEnvelope<EntryAdviceIndex>> {
  return readOrExample<EntryAdviceIndex>(`advice/${entryId}/index.json`, async () =>
    (await mockModule()).mockEntryAdviceIndex(entryId),
  );
}

/**
 * The weekly scoreboard has no example: it is a real-data surface, and a page that showed
 * an invented league table while nothing was published would be the fiction the example
 * gate above was narrowed to avoid. Missing arrives as `LeagueDataMissing`, and the page
 * says "not published yet".
 */
export async function loadScoreboard(): Promise<LeagueViewEnvelope<Scoreboard>> {
  return read<Scoreboard>("scoreboard.json");
}

export const SUPPORTED_LEAGUE_ID = 352490;

/** Lookup uses only the allowed publication, including in development and tests. */
export async function lookupPublishedLeague(
  leagueId: number,
): Promise<"connected" | "unsupported"> {
  if (!Number.isSafeInteger(leagueId) || leagueId <= 0) {
    throw new LeagueDataError("A positive league ID is required.");
  }
  if (leagueId !== SUPPORTED_LEAGUE_ID) return "unsupported";
  const envelope = assertMembers(await read<LeagueMembers>("members.json"));
  const payload = envelope.payload;
  if (
    envelope.source_kind !== "live" ||
    !payload ||
    payload.league_id !== SUPPORTED_LEAGUE_ID ||
    typeof payload.league_name !== "string" ||
    !payload.league_name.trim() ||
    typeof payload.season !== "string" ||
    !payload.season.trim() ||
    !Number.isSafeInteger(payload.gameweek) ||
    payload.gameweek <= 0 ||
    payload.public_after_deadline !== true ||
    !Array.isArray(payload.members) ||
    !payload.members.every(
      (member) =>
        member &&
        ((member.member_kind === "human" &&
          Number.isSafeInteger(member.entry_id) &&
          member.entry_id > 0) ||
          (member.member_kind === "system" && member.entry_id === null)),
    )
  ) {
    throw new LeagueDataError("The published public league record is invalid.");
  }
  return "connected";
}
