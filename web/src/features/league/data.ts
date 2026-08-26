import type { PlayMode, WindowSize } from "../moves/modePrices";
import type { EntryAdvice, EntrySquad, LeagueMembers, LeagueViewEnvelope } from "./types";

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

async function mockModule() {
  return import("../../fixtures/league");
}

export async function loadLeagueMembers(): Promise<LeagueViewEnvelope<LeagueMembers>> {
  if (import.meta.env.DEV || import.meta.env.MODE === "test") {
    return (await mockModule()).mockLeagueMembersEnvelope;
  }
  return read<LeagueMembers>("members.json");
}

export async function loadEntrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>> {
  if (import.meta.env.DEV || import.meta.env.MODE === "test") {
    const fixture = (await mockModule()).mockEntrySquadEnvelopes[entryId];
    if (!fixture) throw new LeagueDataError(`No example entry ${entryId}.`);
    return fixture;
  }
  return read<EntrySquad>(`entries/${entryId}.json`);
}

export async function loadEntryAdvice(
  entryId: number,
  mode: PlayMode,
  window: WindowSize,
): Promise<LeagueViewEnvelope<EntryAdvice>> {
  if (import.meta.env.DEV || import.meta.env.MODE === "test") {
    return (await mockModule()).mockEntryAdviceEnvelope(entryId, mode, window);
  }
  return read<EntryAdvice>(`advice/${entryId}/${mode}/${window}.json`);
}
