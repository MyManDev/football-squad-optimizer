/**
 * The member the visitor said they are, kept for this browser tab: one claim, made in one
 * league. A claim made in league A is nobody in league B.
 *
 * The claim lives in sessionStorage, so a reload in the same tab keeps it and a new visit
 * asks again. Without storage it lives in this module for the page's life. Only the
 * identity module (and the test helpers) read or write it; every page reads identity
 * through `useLeagueIdentity`. A later sign-in replaces this file.
 */

const STORAGE_KEY = "squadopt.member";
const CHANGE_EVENT = "squadopt:member-changed";

export interface MemberClaim {
  leagueId: number;
  entryId: number;
  managerName: string | null;
  teamName: string | null;
  leagueName: string | null;
}

// Versions that remembered the member across visits wrote it here; that choice is gone.
try {
  window.localStorage.removeItem("squadopt.viewer");
} catch {
  // Browser storage is optional.
}

let storageUsable = true;
let memory: MemberClaim | null = null;
// The last stored text and what it reads as, so an unchanged store reads as the same object.
let lastRaw: string | null = null;
let lastParsed: MemberClaim | null = null;

function positiveId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** A claim, or null for anything that is not one. Names are kept exactly as written. */
function parse(value: unknown): MemberClaim | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (!positiveId(record.leagueId) || !positiveId(record.entryId)) return null;
  return {
    leagueId: record.leagueId,
    entryId: record.entryId,
    managerName: text(record.managerName),
    teamName: text(record.teamName),
    leagueName: text(record.leagueName),
  };
}

function parseStored(raw: string | null): MemberClaim | null {
  if (raw === lastRaw) return lastParsed;
  let parsed: MemberClaim | null = null;
  if (raw !== null) {
    try {
      parsed = parse(JSON.parse(raw));
    } catch {
      parsed = null;
    }
  }
  lastRaw = raw;
  lastParsed = parsed;
  return parsed;
}

/** The claim as it stands now, read through to the tab's storage on every call. */
export function readMemberClaim(): MemberClaim | null {
  if (storageUsable) {
    try {
      return parseStored(window.sessionStorage.getItem(STORAGE_KEY));
    } catch {
      storageUsable = false;
    }
  }
  return memory;
}

/** Makes a claim, or drops it with null; anything that is not a claim drops it too. */
export function writeMemberClaim(claim: MemberClaim | null): void {
  const valid = claim === null ? null : parse(claim);
  memory = valid;
  if (storageUsable) {
    try {
      if (valid === null) window.sessionStorage.removeItem(STORAGE_KEY);
      else window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(valid));
    } catch {
      // The claim in memory carries the rest of this page's life.
      storageUsable = false;
    }
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Calls back on every write in this tab; sessionStorage belongs to one tab, so no other. */
export function subscribeMemberClaim(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}
