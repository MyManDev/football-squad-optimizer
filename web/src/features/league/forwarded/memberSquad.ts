/**
 * A forwarded member's entry document (#983 step 4): the document the member page reads,
 * built on the visitor's device from the forwarder's entry bundle and the capture's own table
 * the identity rule binds it to (`bundleMatchesTable`). It is what the weekly run builds from
 * a capture for a member it renders, step for step:
 *
 * - the squad, its armbands and its bank from the held week, the week before a Free Hit when
 *   the captured week played one (`capture_entries.CapturePicksProvider.picks`);
 * - the free transfers from the history under the table's cap (`live.banking`);
 * - the purchase prices replayed from the transfers where the replay holds, else the
 *   current prices capped by the picks' stated worth (`entries.held_squad_from_picks`);
 * - the spending power and the sale prices the solver takes
 *   (`transfers.member_planning_inputs`, `planning.pricing.spending_power`), as the device
 *   block (`device_plan.device_plan_entry`);
 * - the chip windows of the table's rules against the history (`entries.chip_states`).
 *
 * Nothing here reads the network. A bundle the identity rule refuses, a part a reader
 * refuses, or a held player the table does not price is a refusal: no document, so the page
 * shows nothing in its place.
 */

import type { FixturesPayload } from "../../fixtures/types";
import { EntryStateError } from "../entryState/parsers";
import { rebuildPurchasePrices, sellingInputs, type RebuiltPrices } from "../entryState/prices";
import { bankedFreeTransfers, chipStates, type ChipWindow } from "../entryState/rules";
import {
  DEVICE_PLAN_TABLE_CONTRACT_VERSION,
  isDeviceChip,
  type DevicePlanDocument,
  type DevicePlanEntry,
  type DevicePlanPlayer,
} from "../device/types";
import type { FplEntryBundle, FplStandingRow } from "../forwarder/documents";
import { bundleEntryState } from "../forwarder/entryState";
import type { BundleTableRefusal } from "../forwarder/identity";
import type {
  EntryChipAvailability,
  EntrySquad,
  EntrySquadPlayer,
  HumanEntryView,
  LeagueViewEnvelope,
} from "../types";

/**
 * The season's squad budget and sell-on fee in the game's own settings
 * (`game_config.rules.squad_total_spend` and `transfers_sell_on_fee`, as
 * `live.rules.squad_budget_tenths` and `transfer_sell_on_fee` read them from the capture's
 * bootstrap). The capture's table does not carry them (`league_device_plan_v2`), so the
 * device holds them by season; a season not named here replays no purchase prices and takes
 * the same fallback a member whose replay does not hold takes.
 */
export const SEASON_TERMS: Readonly<
  Record<string, { budget_tenths: number; sell_on_fee: number }>
> = {
  "2026-27": { budget_tenths: 1000, sell_on_fee: 0.5 },
};

/**
 * Why no document is built:
 *
 * - the identity rule's refusals, and `unreadable` for a part an entry-state reader refuses;
 * - `table_unreadable`: the table is not a capture's own table with every player's element id;
 * - `squad_not_in_table`: a held player the table does not price, as the run refuses a held
 *   player the capture no longer lists.
 */
export type ForwardedSquadRefusal =
  BundleTableRefusal | "unreadable" | "table_unreadable" | "squad_not_in_table";

export type ForwardedMemberSquad =
  | { ok: true; squad: LeagueViewEnvelope<EntrySquad> }
  | { ok: false; reason: ForwardedSquadRefusal };

export interface ForwardedMemberInputs {
  bundle: FplEntryBundle;
  /** The capture's own table the bundle was asked for, as the page read it. */
  table: LeagueViewEnvelope<DevicePlanDocument>;
  entryId: number;
  /** The site's calendar: each gameweek's deadline, for the purchase-price replay. */
  fixtures: FixturesPayload | null;
  /** The league the page was opened from, or 0 for an entry opened on its own. */
  leagueId: number;
  /** The member's row in the league's standings, where the page was opened from one. */
  standing?: FplStandingRow | null;
}

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;

function position(value: string): EntrySquadPlayer["position"] {
  return (POSITIONS as readonly string[]).includes(value)
    ? (value as EntrySquadPlayer["position"])
    : "UNK";
}

/** The season's chip windows the table's rules state, or null where one cannot be read. */
function chipWindows(rules: DevicePlanDocument["rules"]): ChipWindow[] | null {
  if (!Array.isArray(rules.chips)) return null;
  const windows: ChipWindow[] = [];
  for (const value of rules.chips) {
    if (typeof value !== "object" || value === null) return null;
    const { name, number, start_event, stop_event } = value as Record<string, unknown>;
    if (!isDeviceChip(name)) return null;
    windows.push({
      name,
      number: number as number,
      start_event: start_event as number,
      stop_event: stop_event as number,
    });
  }
  return windows;
}

/** The member's chip windows before the table's deadline, or undefined where none can be read. */
function chipBlock(
  table: DevicePlanDocument,
  played: Record<string, number[]>,
): EntryChipAvailability | undefined {
  const windows = chipWindows(table.rules);
  if (windows === null) return undefined;
  try {
    return {
      known: true,
      gameweek: table.gameweek,
      states: chipStates(windows, table.gameweek, played),
    };
  } catch (error) {
    if (error instanceof EntryStateError) return undefined;
    throw error;
  }
}

/** Each gameweek's deadline the calendar states, for the table's season; null for another. */
function deadlines(
  fixtures: FixturesPayload | null,
  season: string,
): Record<number, string> | null {
  if (fixtures === null || fixtures.season !== season) return null;
  return Object.fromEntries(fixtures.gameweeks.map((week) => [week.gameweek, week.deadline_utc]));
}

/** The planner's budget: the bank and sale prices after the stated worth caps them. */
function spendingPower(
  bank: number,
  sell: Readonly<Record<number, number>>,
  stated: number | null,
): { bank: number; sell: Record<number, number> } {
  if (stated === null) return { bank, sell: { ...sell } };
  const total = Object.values(sell).reduce((sum, price) => sum + price, 0);
  const shortfall = Math.max(0, total - stated);
  const perPlayer = Math.max(0, shortfall - bank);
  const withheld = shortfall - perPlayer;
  return {
    bank: bank - withheld,
    sell: Object.fromEntries(
      Object.entries(sell).map(([id, price]) => [id, Math.max(0, price - perPlayer)]),
    ),
  };
}

export function forwardedMemberSquad({
  bundle,
  table: envelope,
  entryId,
  fixtures,
  leagueId,
  standing = null,
}: ForwardedMemberInputs): ForwardedMemberSquad {
  const table = envelope.payload;
  if (table.contract_version !== DEVICE_PLAN_TABLE_CONTRACT_VERSION) {
    return { ok: false, reason: "table_unreadable" };
  }
  const byElement = new Map<number, DevicePlanPlayer>();
  for (const player of table.players) {
    if (player.element_id === undefined || player.start_tenths === undefined) {
      return { ok: false, reason: "table_unreadable" };
    }
    byElement.set(player.element_id, player);
  }
  const read = bundleEntryState(bundle, table, entryId);
  if (!read.ok) return read;
  const { history, transfers, captured, held, opening } = read.state;
  if (held.squad.some((element) => !byElement.has(element))) {
    return { ok: false, reason: "squad_not_in_table" };
  }
  const row = (element: number) => byElement.get(element)!;
  const current = Object.fromEntries(
    [...byElement].map(([element, player]) => [element, player.buy_tenths]),
  );
  const start = Object.fromEntries(
    [...byElement].map(([element, player]) => [element, player.start_tenths!]),
  );
  const cap = table.rules.max_free_transfers;
  try {
    const banked = bankedFreeTransfers(history, captured.gameweek, cap, captured.active_chip);
    // What was paid for each held player, where the replay of the transfers holds; otherwise
    // the current prices, and the picks' stated worth less the bank caps them.
    const terms = SEASON_TERMS[table.season];
    const calendar = deadlines(fixtures, table.season);
    let selling: { sell: Record<number, number>; known: boolean; worth: number };
    if (terms !== undefined) {
      const rebuilt: RebuiltPrices =
        opening !== null && calendar !== null
          ? rebuildPurchasePrices({
              transfers,
              history,
              opening,
              held,
              budget_tenths: terms.budget_tenths,
              start_prices: start,
              deadlines: calendar,
              through_gameweek: captured.gameweek,
              active_chip: captured.active_chip,
              sell_on_fee: terms.sell_on_fee,
            })
          : {
              known: false,
              prices: {},
              applied: 0,
              free_hit_skipped: 0,
              pending: 0,
              sales_checked: 0,
            };
      const inputs = sellingInputs(held, current, rebuilt, terms.sell_on_fee);
      selling = {
        sell: inputs.sell_tenths,
        known: inputs.purchase_prices_known,
        worth: inputs.squad_sell_value_tenths,
      };
    } else {
      selling = {
        sell: Object.fromEntries(held.squad.map((element) => [element, current[element]!])),
        known: false,
        worth: held.market_value_tenths - held.bank_tenths,
      };
    }
    const power = spendingPower(
      held.bank_tenths,
      selling.sell,
      selling.known ? null : selling.worth,
    );
    if (power.bank < 0) return { ok: false, reason: "unreadable" };
    const top100 = table.rules.top100?.weights.filter((weight) => weight !== 0);
    const devicePlan: DevicePlanEntry = {
      ...(top100 === undefined ? {} : { top100_weights: top100 }),
      held: held.squad.map((element) => row(element).id),
      bank_tenths: power.bank,
      free_transfers: Math.min(banked.count, cap),
      sell_tenths: Object.fromEntries(
        held.squad.map((element) => [String(row(element).id), power.sell[element]!]),
      ),
    };
    const player = (element: number, index: number): EntrySquadPlayer => {
      const listed = row(element);
      return {
        player_id: listed.id,
        name: listed.name,
        short_name: listed.short_name,
        team: listed.team,
        position: position(listed.position),
        price_tenths: listed.buy_tenths,
        expected_points: listed.expected_points,
        event_points: null,
        is_captain: element === held.captain,
        is_vice_captain: element === held.vice_captain,
        role: index < 11 ? "starter" : "bench",
        bench_order: index < 11 ? null : index - 10,
      };
    };
    const fifteen = held.squad.map(player);
    // As the weekly run's entry view words it: a fact the sources could not prove is named.
    const missing = [
      ...(banked.known ? [] : ["free_transfers"]),
      ...(selling.known ? [] : ["purchase_prices"]),
    ];
    const quality = missing.length === 0 ? "complete" : "partial";
    const entry: HumanEntryView = {
      member_kind: "human",
      entry_id: entryId,
      manager_name: standing?.player_name ?? null,
      team_name: standing?.entry_name ?? read.state.entry.name,
      rank: standing?.rank ?? 0,
      gameweek_points: null,
      transfer_cost: null,
      total_points: standing?.total ?? null,
      movement: "unknown",
      movement_places: null,
      data_quality: quality,
    };
    const squad: EntrySquad = {
      league_id: leagueId,
      season: table.season,
      gameweek: table.gameweek,
      scored_gameweek: null,
      entry,
      starting_xi: fifteen.slice(0, 11),
      bench: fifteen.slice(11),
      bank_tenths: held.bank_tenths,
      free_transfers: banked.count,
      free_transfers_known: banked.known,
      chips_used: history.chips_used,
      ...(() => {
        const chips = chipBlock(table, history.chips_used);
        return chips === undefined ? {} : { chips };
      })(),
      purchase_prices_known: selling.known,
      squad_sell_value_tenths: selling.worth,
      spendable_budget_tenths: selling.worth + held.bank_tenths,
      source_snapshot_id: table.source_snapshot_id,
      squadopt_comparison: null,
      data_quality: quality,
      missing_fields: missing,
      squad_basis:
        held.gameweek === captured.gameweek
          ? "captured"
          : `pre_free_hit_gw${String(held.gameweek).padStart(2, "0")}`,
      active_chip: captured.active_chip,
      device_plan: devicePlan,
    };
    return {
      ok: true,
      squad: {
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: bundle.source_time,
        source_kind: "live",
        payload: squad,
      },
    };
  } catch (error) {
    if (error instanceof EntryStateError) return { ok: false, reason: "unreadable" };
    throw error;
  }
}
