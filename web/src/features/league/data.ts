import { withRequestDeadline, type RequestOptions } from "../../data/request";
import { LeagueDataError, LeagueDataMissing } from "./dataErrors";
import { assertAdviceIndex, assertEnvelope, assertMembers, assertSquad } from "./publicationShape";
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

export { LeagueDataError, LeagueDataMissing } from "./dataErrors";

const BASE = `${import.meta.env.BASE_URL}data/league/`;

async function read<T>(relative: string, options?: RequestOptions): Promise<LeagueViewEnvelope<T>> {
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${BASE}${relative}`, { cache: "no-cache", signal });
    if (response.status === 404) throw new LeagueDataMissing(relative);
    if (!response.ok)
      throw new LeagueDataError(`League data is not available (${response.status}).`);
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
  }, options);
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
  options?: RequestOptions,
): Promise<LeagueViewEnvelope<T>> {
  options?.signal?.throwIfAborted();
  if (import.meta.env.MODE === "test") return example();
  if (!import.meta.env.DEV) return read<T>(relative, options);
  try {
    return await read<T>(relative, options);
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
  options?: RequestOptions,
): Promise<LeagueViewEnvelope<EntryAdvice>> {
  // A named rival reads the producer's per-rival file; without one, the plain path —
  // the baseline for saf-puan, the standings neighbour's copy for a rival strategy.
  const relative =
    rivalEntryId === null
      ? `advice/${entryId}/${mode}/${window}.json`
      : `advice/${entryId}/${mode}/${window}/vs-${rivalEntryId}.json`;
  return readOrExample<EntryAdvice>(
    relative,
    async () => (await mockModule()).mockEntryAdviceEnvelope(entryId, mode, window, rivalEntryId),
    options,
  );
}

export async function loadEntryAdviceIndex(
  entryId: number,
): Promise<LeagueViewEnvelope<EntryAdviceIndex>> {
  const envelope = await readOrExample<EntryAdviceIndex>(`advice/${entryId}/index.json`, async () =>
    (await mockModule()).mockEntryAdviceIndex(entryId),
  );
  return assertAdviceIndex(envelope, entryId);
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
