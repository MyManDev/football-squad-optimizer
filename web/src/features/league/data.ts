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

function assertEnvelope<T>(value: LeagueViewEnvelope<T>): LeagueViewEnvelope<T> {
  if (value.contract_version !== CONTRACT_VERSION) {
    throw new LeagueDataError(
      `League view contract mismatch: expected ${CONTRACT_VERSION}, found ${value.contract_version}.`,
    );
  }
  return value;
}

async function read<T>(relative: string): Promise<LeagueViewEnvelope<T>> {
  const response = await fetch(`${BASE}${relative}`, { cache: "no-cache" });
  if (response.status === 404) throw new LeagueDataMissing(relative);
  if (!response.ok) throw new LeagueDataError(`League data is not available (${response.status}).`);
  // A static host answers an unknown path with the app shell rather than a 404, so a
  // missing document arrives as a 200 carrying HTML. Parsing that as JSON fails with a
  // syntax error that says nothing; treating it as "not published" says what happened.
  const body = await response.text();
  let parsed: LeagueViewEnvelope<T>;
  try {
    parsed = JSON.parse(body) as LeagueViewEnvelope<T>;
  } catch {
    throw new LeagueDataMissing(relative);
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
  return readOrExample<LeagueMembers>(
    "members.json",
    async () => (await mockModule()).mockLeagueMembersEnvelope,
  );
}

export async function loadEntrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>> {
  return readOrExample<EntrySquad>(`entries/${entryId}.json`, async () => {
    const fixture = (await mockModule()).mockEntrySquadEnvelopes[entryId];
    if (!fixture) throw new LeagueDataError(`No example entry ${entryId}.`);
    return fixture;
  });
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
