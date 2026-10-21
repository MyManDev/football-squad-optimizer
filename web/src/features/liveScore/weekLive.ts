/** The trimmed wire contract. Player identity resolution happens before scoring. */
export type Position = "GK" | "DEF" | "MID" | "FWD";
export interface WeekElement {
  element_id: number;
  points: number;
  minutes: number;
  card_shown: boolean;
  position?: Position;
  club?: number;
}
export interface MemberWeek {
  entry_id: number;
  gameweek: number;
  pick_order: number[];
  captain: number;
  vice: number;
  active_chip: null | "3xc" | "bboost" | "freehit" | "wildcard";
  transfer_cost: number;
  entry_history_points?: number;
}
export interface WeekLive {
  contract_version: "week_live_v1";
  season: string;
  gameweek: number;
  source_time: string;
  fixtures: { id: number; home_club: number; away_club: number; finished: boolean }[];
  elements: WeekElement[];
  members?: MemberWeek[];
}

const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const integer = (v: unknown): v is number => Number.isSafeInteger(v);
const id = (v: unknown): v is number => integer(v) && v > 0;
const week = (v: unknown): v is number => id(v) && v <= 38;
const only = (v: Record<string, unknown>, keys: string) =>
  Object.keys(v).every((key) => keys.split(" ").includes(key));
const unique = (ids: number[]) => new Set(ids).size === ids.length;

export class WeekLiveError extends Error {}
const assertInput = (ok: unknown, reason: string): void => {
  if (!ok) throw new WeekLiveError(reason);
};

/** Reject impossible dates as well as non-UTC or malformed wire timestamps. */
function instant(value: unknown): boolean {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/.test(value))
    return false;
  const parsed = new Date(value);
  return (
    Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 19) === value.slice(0, 19)
  );
}

export function memberWeek(value: unknown, gameweek: number): MemberWeek {
  assertInput(record(value), "invalid_member");
  const row = value as Record<string, unknown>;
  assertInput(
    new Set<unknown>([null, "3xc", "bboost", "freehit", "wildcard"]).has(row.active_chip),
    "unsupported_chip",
  );
  assertInput(
    only(
      row,
      "entry_id gameweek pick_order captain vice active_chip transfer_cost entry_history_points",
    ) &&
      id(row.entry_id) &&
      week(row.gameweek) &&
      row.gameweek === gameweek &&
      Array.isArray(row.pick_order) &&
      row.pick_order.length === 15 &&
      row.pick_order.every(id) &&
      unique(row.pick_order) &&
      id(row.captain) &&
      id(row.vice) &&
      row.captain !== row.vice &&
      row.pick_order.slice(0, 11).includes(row.captain) &&
      row.pick_order.slice(0, 11).includes(row.vice) &&
      integer(row.transfer_cost) &&
      row.transfer_cost >= 0 &&
      (row.entry_history_points === undefined || integer(row.entry_history_points)),
    "invalid_member",
  );
  return value as MemberWeek;
}

export function weekLive(value: unknown): WeekLive {
  assertInput(record(value), "invalid_week");
  const row = value as Record<string, unknown>;
  assertInput(
    only(row, "contract_version season gameweek source_time fixtures elements members") &&
      row.contract_version === "week_live_v1" &&
      typeof row.season === "string" &&
      /^\d{4}-\d{2}$/.test(row.season) &&
      week(row.gameweek) &&
      instant(row.source_time) &&
      Array.isArray(row.fixtures) &&
      Array.isArray(row.elements) &&
      (row.members === undefined || Array.isArray(row.members)),
    "invalid_week",
  );
  const document = value as WeekLive;
  for (const fixture of document.fixtures) {
    assertInput(
      record(fixture) &&
        only(fixture, "id home_club away_club finished") &&
        id(fixture.id) &&
        id(fixture.home_club) &&
        id(fixture.away_club) &&
        fixture.home_club !== fixture.away_club &&
        typeof fixture.finished === "boolean",
      "invalid_fixture",
    );
  }
  assertInput(unique(document.fixtures.map((fixture) => fixture.id)), "duplicate_fixture");
  for (const element of document.elements) {
    assertInput(
      record(element) &&
        only(element, "element_id points minutes card_shown position club") &&
        id(element.element_id) &&
        integer(element.points) &&
        integer(element.minutes) &&
        element.minutes >= 0 &&
        typeof element.card_shown === "boolean" &&
        (element.position === undefined ||
          ["GK", "DEF", "MID", "FWD"].includes(element.position)) &&
        (element.club === undefined || id(element.club)),
      "invalid_element",
    );
  }
  assertInput(unique(document.elements.map((element) => element.element_id)), "duplicate_element");
  const members = (document.members ?? []).map((member) => memberWeek(member, document.gameweek));
  assertInput(unique(members.map((member) => member.entry_id)), "duplicate_member");
  return document;
}
