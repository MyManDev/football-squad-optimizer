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
  if (!response.ok) throw new LeagueDataError(`League data is not available (${response.status}).`);
  return assertEnvelope((await response.json()) as LeagueViewEnvelope<T>);
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
