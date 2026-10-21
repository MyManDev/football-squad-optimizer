import { DEVICE_CHIPS, type DeviceChip } from "../device/types";
import {
  EntryStateError,
  gameweek,
  integer,
  type EntryPicks,
  type TransferHistory,
} from "./parsers";

export function bankedFreeTransfers(
  history: TransferHistory,
  week: number,
  cap: number | null,
  activeChip: string | null = null,
): { count: number; known: boolean } {
  gameweek(week);
  if (cap === null) return { count: 1, known: false };
  integer(cap, "free-transfer cap", 1);
  const unlimited = new Set([
    ...(history.chips_used.wildcard ?? []),
    ...(history.chips_used.freehit ?? []),
  ]);
  if (activeChip === "wildcard" || activeChip === "freehit") unlimited.add(week);
  let available = 0;
  for (let at = 1; at <= week; at++) {
    const row = history.weeks[at];
    if (!row) return { count: 1, known: false };
    const chip = at === 1 || unlimited.has(at);
    available = Math.min(cap, available + (chip ? 0 : 1));
    const consumed = chip ? 0 : Math.min(row.transfers, available);
    const expectedCost = chip ? 0 : (row.transfers - consumed) * 4;
    if (row.cost !== expectedCost) return { count: 1, known: false };
    available -= consumed;
  }
  return { count: Math.min(cap, available + 1), known: true };
}

/** Walk actual picks, refusing a missing intervening week rather than assuming no chip. */
export function heldSquadBasis(
  captured: EntryPicks,
  read: (week: number) => EntryPicks,
): EntryPicks {
  if (captured.active_chip !== "freehit") return captured;
  for (let week = captured.gameweek - 1; week >= 1; week--) {
    const previous = read(week);
    if (previous.gameweek !== week || previous.entry_id !== captured.entry_id)
      throw new EntryStateError("Free Hit basis identity mismatch.");
    if (previous.active_chip !== "freehit") return previous;
  }
  throw new EntryStateError("Free Hit has no earlier squad basis.");
}

export interface ChipWindow {
  name: DeviceChip;
  number: number;
  start_event: number;
  stop_event: number;
}
interface ChipState {
  state: "unknown" | "used" | "expired" | "not_yet" | "available";
  gameweek: number | null;
  start_event: number;
  stop_event: number;
}

export function chipStates(
  windows: readonly ChipWindow[],
  week: number,
  played: Partial<Record<string, readonly number[]>> | null,
): Record<DeviceChip, { first_half: ChipState | null; second_half: ChipState | null }> {
  gameweek(week);
  for (const window of windows) {
    if (!DEVICE_CHIPS.includes(window.name)) throw new EntryStateError("Unknown chip window.");
    integer(window.number, "chip uses", 1);
    gameweek(window.start_event);
    gameweek(window.stop_event);
    if (window.stop_event < window.start_event) throw new EntryStateError("Reversed chip window.");
  }
  return Object.fromEntries(
    DEVICE_CHIPS.map((name) => {
      const own = windows
        .filter((window) => window.name === name)
        .toSorted((a, b) => a.start_event - b.start_event);
      if (own.length > 2) throw new EntryStateError("More chip windows than halves.");
      const weeks = played === null ? null : [...(played[name] ?? [])].sort((a, b) => a - b);
      if (
        weeks?.some(
          (at) => !own.some((window) => at >= window.start_event && at <= window.stop_event),
        )
      )
        throw new EntryStateError("Chip played outside its windows.");
      const states = own.map((window): ChipState => {
        const inside = weeks?.filter((at) => at >= window.start_event && at <= window.stop_event);
        const used = inside !== undefined && inside.length >= window.number;
        const state =
          weeks === null
            ? "unknown"
            : used
              ? "used"
              : week > window.stop_event
                ? "expired"
                : week < window.start_event || (name === "freehit" && weeks.includes(week - 1))
                  ? "not_yet"
                  : "available";
        return {
          state,
          gameweek: used ? inside[0]! : null,
          start_event: window.start_event,
          stop_event: window.stop_event,
        };
      });
      return [name, { first_half: states[0] ?? null, second_half: states[1] ?? null }];
    }),
  ) as Record<DeviceChip, { first_half: ChipState | null; second_half: ChipState | null }>;
}
