/** Offline FPL-shaped readers. These do not fetch or authorize a device solve. */
export class EntryStateError extends Error {}

export function object(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new EntryStateError(`${field} must be an object.`);
  return value as Record<string, unknown>;
}

export function integer(value: unknown, field: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum)
    throw new EntryStateError(`${field} must be a safe integer at least ${minimum}.`);
  return value;
}

export function gameweek(value: unknown): number {
  const week = integer(value, "gameweek", 1);
  if (week > 38) throw new EntryStateError("gameweek must be at most 38.");
  return week;
}

function array(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new EntryStateError(`${field} must be an array.`);
  return value;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim())
    throw new EntryStateError(`${field} must be text.`);
  return value;
}

function flag(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new EntryStateError(`${field} must be a boolean.`);
  return value;
}

export interface TransferHistory {
  entry_id: number;
  weeks: Record<number, { transfers: number; cost: number; bank: number | null }>;
  chips_used: Record<string, number[]>;
}

export function readEntry(value: unknown, entryId: number) {
  integer(entryId, "entry id", 1);
  const row = object(value, "entry");
  if (integer(row.id, "entry.id", 1) !== entryId)
    throw new EntryStateError("Entry identity mismatch.");
  return {
    entry_id: entryId,
    name: text(row.name, "entry.name"),
    started_event: gameweek(row.started_event),
  };
}

export function readHistory(value: unknown, entryId: number): TransferHistory {
  integer(entryId, "entry id", 1);
  const document = object(value, "history");
  const weeks: TransferHistory["weeks"] = {};
  const chips: Record<string, number[]> = Object.create(null);
  for (const value of array(document.current, "history.current")) {
    const row = object(value, "history row");
    const week = gameweek(row.event);
    if (Object.hasOwn(weeks, week)) throw new EntryStateError("Duplicate history gameweek.");
    weeks[week] = {
      transfers: integer(row.event_transfers, "history.event_transfers"),
      cost: integer(row.event_transfers_cost, "history.event_transfers_cost"),
      bank: typeof row.bank === "number" && Number.isSafeInteger(row.bank) ? row.bank : null,
    };
  }
  for (const value of array(document.chips, "history.chips")) {
    const row = object(value, "chip");
    const name = text(row.name, "chip.name");
    (chips[name] ??= []).push(gameweek(row.event));
  }
  for (const played of Object.values(chips)) played.sort((a, b) => a - b);
  return { entry_id: entryId, weeks, chips_used: chips };
}

export interface EntryPicks {
  entry_id: number;
  gameweek: number;
  squad: number[];
  starting_xi: number[];
  captain: number;
  vice_captain: number;
  bank_tenths: number;
  /** The source's total market value, including bank. Never a selling budget. */
  market_value_tenths: number;
  active_chip: string | null;
}

export function readPicks(value: unknown, entryId: number, week: number): EntryPicks {
  integer(entryId, "entry id", 1);
  gameweek(week);
  const document = object(value, "picks");
  const history = object(document.entry_history, "picks.entry_history");
  if (gameweek(history.event) !== week) throw new EntryStateError("Picks gameweek mismatch.");
  const rows = array(document.picks, "picks.picks")
    .map((value) => {
      const row = object(value, "pick");
      const multiplier = integer(row.multiplier, "pick.multiplier");
      if (multiplier > 3) throw new EntryStateError("Unknown pick multiplier.");
      return {
        element: integer(row.element, "pick.element", 1),
        position: integer(row.position, "pick.position", 1),
        captain: flag(row.is_captain, "pick.is_captain"),
        vice: flag(row.is_vice_captain, "pick.is_vice_captain"),
      };
    })
    .sort((a, b) => a.position - b.position);
  if (
    rows.length !== 15 ||
    rows.some((row, i) => row.position !== i + 1) ||
    new Set(rows.map((row) => row.element)).size !== 15
  )
    throw new EntryStateError("Picks must name fifteen distinct players in positions 1 to 15.");
  const captains = rows.filter((row) => row.captain);
  const vices = rows.filter((row) => row.vice);
  if (captains.length !== 1 || vices.length !== 1 || captains[0]!.element === vices[0]!.element)
    throw new EntryStateError("Picks must name one captain and one different vice captain.");
  const squad = rows.map((row) => row.element);
  const starting = squad.slice(0, 11);
  const captain = captains[0]!.element;
  if (!starting.includes(captain)) {
    const substitutions = Array.isArray(document.automatic_subs) ? document.automatic_subs : [];
    const matches = substitutions.filter((value: unknown) => {
      if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
      const row = value as Record<string, unknown>;
      return (
        row.entry === entryId &&
        row.event === week &&
        row.element_out === captain &&
        typeof row.element_in === "number" &&
        starting.includes(row.element_in)
      );
    });
    if (matches.length !== 1)
      throw new EntryStateError("Bench captain needs one matching automatic substitution.");
  }
  const bank = integer(history.bank, "picks.bank");
  const marketValue = integer(history.value, "picks.value");
  if (marketValue < bank) throw new EntryStateError("Market value cannot be below the bank.");
  const activeChip =
    document.active_chip == null ? null : text(document.active_chip, "picks.active_chip");
  return {
    entry_id: entryId,
    gameweek: week,
    squad,
    starting_xi: starting,
    captain,
    vice_captain: vices[0]!.element,
    bank_tenths: bank,
    market_value_tenths: marketValue,
    active_chip: activeChip,
  };
}

/** UTC microseconds preserve the Python deadline boundary, including fractional seconds. */
function instant(value: unknown): bigint {
  const match =
    typeof value === "string" &&
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(
      value,
    );
  if (!match) throw new EntryStateError("A timestamp must include its time zone.");
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  if (year < 1) throw new EntryStateError("Invalid calendar year.");
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day ||
    date.getUTCHours() !== hour ||
    date.getUTCMinutes() !== minute ||
    date.getUTCSeconds() !== second
  )
    throw new EntryStateError("Invalid calendar timestamp.");
  const zone = match[8]!;
  let offset = 0;
  if (zone !== "Z") {
    const hours = Number(zone.slice(1, 3)),
      minutes = Number(zone.slice(4));
    if (hours > 23 || minutes > 59) throw new EntryStateError("Invalid time zone offset.");
    offset = (hours * 60 + minutes) * (zone[0] === "+" ? 1 : -1);
  }
  return BigInt(date.getTime() - offset * 60_000) * 1000n + BigInt((match[7] ?? "").padEnd(6, "0"));
}

export function planGameweek(bootstrap: unknown, asOf: string): number {
  const rows = array(object(bootstrap, "bootstrap").events, "bootstrap.events")
    .map((value) => {
      const row = object(value, "event");
      flag(row.finished, "event.finished");
      return { week: gameweek(row.id), deadline: instant(row.deadline_time) };
    })
    .sort((a, b) => a.week - b.week);
  if (new Set(rows.map((row) => row.week)).size !== rows.length)
    throw new EntryStateError("Duplicate deadline gameweek.");
  const now = instant(asOf);
  const next = rows.find((row) => row.deadline > now);
  if (!next) throw new EntryStateError("No open deadline.");
  return next.week;
}
