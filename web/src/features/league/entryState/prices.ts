/** Offline port of the accepted purchase-price replay; never reads a network source. */
import {
  EntryStateError,
  gameweek,
  integer,
  object,
  timestampMicros,
  type EntryPicks,
  type TransferHistory,
} from "./parsers";

export interface EntryTransfer {
  event: number;
  element_in: number;
  element_in_cost: number;
  element_out: number;
  element_out_cost: number;
  time_utc: string;
}

export function readTransfers(value: unknown, entryId: number): EntryTransfer[] {
  integer(entryId, "entry id", 1);
  if (!Array.isArray(value)) throw new EntryStateError("Transfers must be an array.");
  const seen = new Set<string>();
  const rows = value.map((value) => {
    const row = object(value, "transfer");
    if (integer(row.entry, "transfer.entry", 1) !== entryId)
      throw new EntryStateError("Transfer entry mismatch.");
    const instant = timestampMicros(row.time);
    if (typeof row.time !== "string" || !/(Z|[+-]00:00)$/.test(row.time))
      throw new EntryStateError("Transfer time must be expressed in UTC.");
    const transfer = {
      event: gameweek(row.event),
      element_in: integer(row.element_in, "transfer.element_in", 1),
      element_in_cost: integer(row.element_in_cost, "transfer.element_in_cost"),
      element_out: integer(row.element_out, "transfer.element_out", 1),
      element_out_cost: integer(row.element_out_cost, "transfer.element_out_cost"),
      time_utc: utcTime(instant),
    };
    if (transfer.element_in === transfer.element_out)
      throw new EntryStateError("Transfer buys and sells the same player.");
    const key = [
      instant.toString(),
      transfer.event,
      transfer.element_in,
      transfer.element_in_cost,
      transfer.element_out,
      transfer.element_out_cost,
    ].join(":");
    if (seen.has(key)) throw new EntryStateError("Duplicate transfer.");
    seen.add(key);
    return transfer;
  });
  return rows.sort((a, b) => compareTime(a.time_utc, b.time_utc));
}

function compareTime(a: string, b: string): number {
  const left = timestampMicros(a),
    right = timestampMicros(b);
  return left < right ? -1 : left > right ? 1 : 0;
}

function utcTime(instant: bigint): string {
  const fraction = ((instant % 1_000_000n) + 1_000_000n) % 1_000_000n;
  const date = new Date(Number((instant - fraction) / 1_000_000n) * 1000);
  if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999)
    throw new EntryStateError("UTC instant is outside the supported calendar.");
  const second = date.toISOString().slice(0, -5);
  return `${second}${fraction ? `.${fraction.toString().padStart(6, "0")}` : ""}Z`;
}

export function readElementPrices(
  value: unknown,
): Record<number, { current_tenths: number; start_tenths: number }> {
  const elements = object(value, "bootstrap").elements;
  if (!Array.isArray(elements) || elements.length === 0)
    throw new EntryStateError("Bootstrap must name elements.");
  const prices: Record<number, { current_tenths: number; start_tenths: number }> = {};
  for (const value of elements) {
    const row = object(value, "element");
    const id = integer(row.id, "element.id", 1);
    if (Object.hasOwn(prices, id)) throw new EntryStateError("Duplicate element price.");
    const current = integer(row.now_cost, "element.now_cost");
    const change = integer(
      row.cost_change_start,
      "element.cost_change_start",
      -Number.MAX_SAFE_INTEGER,
    );
    const start = integer(current - change, "element.start_price");
    prices[id] = { current_tenths: current, start_tenths: start };
  }
  return prices;
}

export function sellPriceTenths(current: number, purchase: number, fee = 0.5): number {
  integer(current, "current price");
  integer(purchase, "purchase price");
  if (typeof fee !== "number" || !Number.isFinite(fee) || fee < 0 || fee > 1)
    throw new EntryStateError("Invalid sell-on fee.");
  if (current <= purchase) return current;
  const share = (1 - fee) * 100;
  const floor = Math.floor(share);
  // Python round() uses ties-to-even; the retained share is rounded before integer division.
  const retained = share - floor === 0.5 ? floor + (floor % 2) : Math.round(share);
  return Number(BigInt(purchase) + (BigInt(current - purchase) * BigInt(retained)) / 100n);
}

export interface RebuiltPrices {
  known: boolean;
  prices: Record<number, number>;
  applied: number;
  free_hit_skipped: number;
  pending: number;
  sales_checked: number;
  reason?: string;
}

function refused(reason: string): RebuiltPrices {
  return {
    known: false,
    prices: {},
    applied: 0,
    free_hit_skipped: 0,
    pending: 0,
    sales_checked: 0,
    reason,
  };
}

function tiedRows(rows: readonly EntryTransfer[]): EntryTransfer[][] {
  const groups: EntryTransfer[][] = [];
  for (const row of rows) {
    const last = groups.at(-1);
    if (last && compareTime(last[0]!.time_utc, row.time_utc) === 0) last.push(row);
    else groups.push([row]);
  }
  return groups;
}

function replay(
  rows: readonly EntryTransfer[],
  prices: Map<number, number>,
  initialBank: number,
  fee: number,
): { bank: number; checked: number } | string {
  let bank = BigInt(initialBank),
    checked = 0;
  for (const group of tiedRows(rows)) {
    const waiting = [...group];
    const stated = new Map(waiting.map((row) => [row.element_in, row.element_in_cost]));
    while (waiting.length > 0) {
      const ready = waiting.findIndex(
        (row) => prices.has(row.element_out) && !prices.has(row.element_in),
      );
      if (ready < 0) return "transfer_does_not_match_held_squad";
      const row = waiting.splice(ready, 1)[0]!;
      const market = stated.get(row.element_out);
      if (market !== undefined) {
        if (row.element_out_cost !== sellPriceTenths(market, prices.get(row.element_out)!, fee))
          return "sale_price_mismatch";
        checked++;
      }
      prices.delete(row.element_out);
      prices.set(row.element_in, row.element_in_cost);
      bank += BigInt(row.element_out_cost) - BigInt(row.element_in_cost);
    }
  }
  const result = Number(bank);
  return Number.isSafeInteger(result) ? { bank: result, checked } : "bank_out_of_range";
}

export interface PriceReplayInputs {
  transfers: readonly EntryTransfer[];
  history: TransferHistory;
  opening: EntryPicks;
  held: EntryPicks;
  budget_tenths: number;
  start_prices: Readonly<Record<number, number>>;
  deadlines: Readonly<Record<number, string>>;
  through_gameweek: number;
  active_chip: string | null;
  sell_on_fee: number;
}

export function rebuildPurchasePrices(input: PriceReplayInputs): RebuiltPrices {
  const {
    transfers,
    history,
    opening,
    held,
    budget_tenths: budget,
    start_prices: start,
    deadlines,
    through_gameweek: through,
    active_chip: active,
    sell_on_fee: fee,
  } = input;
  gameweek(through);
  integer(budget, "season budget", 1);
  sellPriceTenths(0, 0, fee);
  if (
    opening.gameweek !== 1 ||
    opening.entry_id !== history.entry_id ||
    held.entry_id !== history.entry_id ||
    held.gameweek > through
  )
    return refused("squad_identity_mismatch");
  const weeks = Object.keys(history.weeks).map(Number);
  if (weeks.length === 0 || Math.min(...weeks) !== 1) return refused("opening_history_missing");
  for (let week = 1; week <= through; week++) {
    if (!history.weeks[week]) return refused("history_week_missing");
    if (history.weeks[week]!.bank === null) return refused("history_bank_missing");
  }
  if (history.weeks[1]!.bank !== opening.bank_tenths) return refused("opening_bank_mismatch");
  if (opening.squad.some((id) => start[id] === undefined)) return refused("opening_price_missing");
  for (const id of opening.squad) integer(start[id], "start price");
  const cost = opening.squad.reduce(
    (total, id) => total + BigInt(start[id]!),
    BigInt(opening.bank_tenths),
  );
  if (cost !== BigInt(budget)) return refused("opening_budget_mismatch");
  for (const transfer of transfers) {
    if (transfer.event <= 1) return refused("opening_transfer");
    const before = deadlines[transfer.event - 1],
      until = deadlines[transfer.event];
    if (before === undefined || until === undefined) return refused("transfer_deadline_missing");
    const at = timestampMicros(transfer.time_utc);
    if (!(timestampMicros(before) < at && at < timestampMicros(until)))
      return refused("transfer_outside_window");
  }
  const ordered = [...transfers].sort((a, b) => compareTime(a.time_utc, b.time_utc));
  for (const group of tiedRows(ordered)) {
    if (
      new Set(group.map((row) => row.element_out)).size !== group.length ||
      new Set(group.map((row) => row.element_in)).size !== group.length
    )
      return refused("repeated_element_at_one_instant");
  }
  const freeHits = new Set(history.chips_used.freehit ?? []);
  const chipWeeks = new Set([
    ...(history.chips_used.freehit ?? []),
    ...(history.chips_used.wildcard ?? []),
  ]);
  if (active === "freehit") freeHits.add(through);
  if (active === "freehit" || active === "wildcard") chipWeeks.add(through);
  const prices = new Map(opening.squad.map((id) => [id, start[id]!]));
  let bank = opening.bank_tenths,
    applied = 0,
    skipped = 0,
    checked = 0;
  for (let week = 2; week <= through; week++) {
    const rows = ordered.filter((row) => row.event === week);
    if (!chipWeeks.has(week) && rows.length !== history.weeks[week]!.transfers)
      return refused("transfer_count_mismatch");
    const result = replay(rows, freeHits.has(week) ? new Map(prices) : prices, bank, fee);
    if (typeof result === "string") return refused(result);
    checked += result.checked;
    if (freeHits.has(week)) {
      skipped += rows.length;
      continue;
    }
    bank = result.bank;
    applied += rows.length;
    if (bank !== history.weeks[week]!.bank) return refused("history_bank_mismatch");
  }
  if (prices.size !== new Set(held.squad).size || held.squad.some((id) => !prices.has(id)))
    return refused("held_squad_mismatch");
  if (bank !== held.bank_tenths) return refused("held_bank_mismatch");
  const pending = ordered.filter((row) => row.event > through);
  const upcoming = replay(
    pending.filter((row) => row.event === through + 1),
    new Map(prices),
    bank,
    fee,
  );
  if (typeof upcoming === "string") return refused(upcoming);
  return {
    known: true,
    prices: Object.fromEntries(prices),
    applied,
    free_hit_skipped: skipped,
    pending: pending.length,
    sales_checked: checked + upcoming.checked,
  };
}

/** The server's late-joiner fallback is retained and identified; it is not a proved budget. */
export function sellingInputs(
  held: EntryPicks,
  current: Readonly<Partial<Record<number, number>>>,
  rebuilt: RebuiltPrices,
  fee: number,
) {
  if (held.squad.some((id) => current[id] === undefined))
    throw new EntryStateError("Held player has no current price.");
  const known =
    rebuilt.known &&
    Object.keys(rebuilt.prices).length === held.squad.length &&
    held.squad.every((id) => rebuilt.prices[id] !== undefined);
  const sell = Object.fromEntries(
    held.squad.map((id) => [
      id,
      sellPriceTenths(current[id]!, known ? rebuilt.prices[id]! : current[id]!, fee),
    ]),
  );
  const total = known
    ? Number(Object.values(sell).reduce((sum, price) => sum + BigInt(price), 0n))
    : held.market_value_tenths - held.bank_tenths;
  integer(total, "squad selling value");
  return {
    sell_tenths: sell,
    purchase_prices_known: known,
    squad_sell_value_tenths: total,
  };
}
