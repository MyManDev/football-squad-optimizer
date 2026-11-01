/**
 * A forwarded member's entry document (#983 step 4), built from the forwarder's bundle and
 * the capture's own table the identity rule binds it to: the device block the weekly run
 * would publish for the same member, a refusal where the rule or a reader refuses, and
 * nothing invented in either case.
 */

import { describe, expect, it } from "vitest";

import deviceInstances from "../../../fixtures/device-plan/instances.json";
import { BUNDLE_EXAMPLES, bundleHolding, fixtureCaptureTable } from "../../../fixtures/forwarder";
import type { FixturesPayload } from "../../fixtures/types";
import type { DevicePlanDocument, DevicePlanPlayer } from "../device/types";
import { sellPriceTenths } from "../entryState/prices";
import type { FplEntryBundle } from "../forwarder/documents";
import type { LeagueViewEnvelope } from "../types";
import { forwardedMemberSquad } from "./memberSquad";

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";

function envelope(payload: DevicePlanDocument): LeagueViewEnvelope<DevicePlanDocument> {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload,
  };
}

/** The 2026-27 chip windows as the capture's table states them. */
const CHIP_WINDOWS = ["wildcard", "freehit", "bboost", "3xc"].flatMap((name) => [
  { name, number: 1, start_event: name === "bboost" || name === "3xc" ? 1 : 2, stop_event: 19 },
  { name, number: 1, start_event: 20, stop_event: 38 },
]);

/** A table at `gameweek` naming `players` (element id, start and current price). */
function tableOf(
  gameweek: number,
  players: readonly { element: number; start: number; buy: number }[],
  season = "2026-27",
): DevicePlanDocument {
  const base = fixtureCaptureTable(CAPTURE);
  return {
    ...base,
    season,
    gameweek,
    rules: { ...base.rules, chips: CHIP_WINDOWS },
    players: players.map(({ element, start, buy }, index): DevicePlanPlayer => ({
      id: 5000 + element,
      element_id: element,
      name: `Player ${element}`,
      short_name: `P${element}`,
      team: `Club ${(index % 10) + 1}`,
      position: index < 2 ? "GK" : index < 7 ? "DEF" : index < 12 ? "MID" : "FWD",
      buy_tenths: buy,
      start_tenths: start,
      expected_points: 2,
      coefficients: [200, 1800, 2000],
    })),
  };
}

/** A weekly calendar of the season from 21 August, each deadline at 17:30 UTC. */
function calendar(season = "2026-27"): FixturesPayload {
  return {
    season,
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: 9,
    unscheduled_count: 0,
    gameweeks: Array.from({ length: 12 }, (_, index) => ({
      gameweek: index + 1,
      deadline_utc: new Date(Date.UTC(2026, 7, 21 + 7 * index, 17, 30)).toISOString(),
      fixtures: [],
    })),
  };
}

describe("a forwarded member's document from the parity fixture", () => {
  const member = deviceInstances.members[2]!;
  const table = fixtureCaptureTable(CAPTURE);
  // The fixture member's fifteen, the first eleven a legal formation.
  const fifteen = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
  const bank = member.entry.bank_tenths;
  const worth = Object.values(member.entry.sell_tenths).reduce((sum, price) => sum + price, 0);
  const bundle = bundleHolding(member.entry_id, table.gameweek, fifteen, {
    bank,
    value: bank + worth,
    captain: 132,
    vice: 139,
  });

  it("binds the bundle to the table and builds the block the run publishes", () => {
    const built = forwardedMemberSquad({
      bundle,
      table: envelope(table),
      entryId: member.entry_id,
      fixtures: null,
      leagueId: 314,
    });
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    const squad = built.squad.payload;
    expect(squad.device_plan).toEqual({ ...member.entry, held: fifteen });
    expect([...squad.device_plan!.held].sort()).toEqual([...member.entry.held].sort());
    expect(squad).toMatchObject({
      league_id: 314,
      season: table.season,
      gameweek: table.gameweek,
      source_snapshot_id: CAPTURE,
      bank_tenths: bank,
      free_transfers: 5,
      free_transfers_known: true,
      purchase_prices_known: false,
      squad_sell_value_tenths: worth,
      spendable_budget_tenths: worth + bank,
      squad_basis: "captured",
      active_chip: null,
    });
    expect(squad.entry).toMatchObject({ entry_id: member.entry_id, team_name: "Synthetic XI" });
    expect(squad.starting_xi.map((player) => player.player_id)).toEqual(fifteen.slice(0, 11));
    expect(squad.bench.map((player) => player.bench_order)).toEqual([1, 2, 3, 4]);
    expect(squad.starting_xi.find((player) => player.is_captain)?.player_id).toBe(132);
    expect(squad.starting_xi.find((player) => player.is_vice_captain)?.player_id).toBe(139);
  });

  it("names the member from the league's standings where the page came from them", () => {
    const built = forwardedMemberSquad({
      bundle,
      table: envelope(table),
      entryId: member.entry_id,
      fixtures: null,
      leagueId: 314,
      standing: {
        entry: member.entry_id,
        entry_name: "Table Name",
        player_name: "Manager Name",
        rank: 4,
        rank_sort: 4,
        last_rank: null,
        total: 512,
        event_total: 40,
      },
    });
    expect(built.ok && built.squad.payload.entry).toMatchObject({
      team_name: "Table Name",
      manager_name: "Manager Name",
      rank: 4,
      total_points: 512,
    });
  });

  it.each([
    [
      "another table gameweek",
      (value: FplEntryBundle) => ({ ...value, gameweek: value.gameweek + 1 }),
      "table_gameweek_mismatch",
    ],
    [
      "picks of an earlier week",
      (value: FplEntryBundle) => ({ ...value, picks: value.picks.slice(0, 1) }),
      "picks_gameweek_mismatch",
    ],
    [
      "a history without the held week",
      (value: FplEntryBundle) => ({
        ...value,
        history: {
          ...value.history,
          current: value.history.current.filter((row) => row.event !== table.gameweek - 1),
        },
      }),
      "history_missing_week",
    ],
    [
      "another member's bundle",
      (value: FplEntryBundle) => ({ ...value, entry_id: value.entry_id + 1 }),
      "entry_mismatch",
    ],
  ] as const)("refuses %s, building nothing", (_name, change, reason) => {
    expect(
      forwardedMemberSquad({
        bundle: change(bundle),
        table: envelope(table),
        entryId: member.entry_id,
        fixtures: null,
        leagueId: 0,
      }),
    ).toEqual({ ok: false, reason });
  });

  it("refuses a held player the table does not price", () => {
    const short = { ...table, players: table.players.filter((player) => player.id !== 156) };
    expect(
      forwardedMemberSquad({
        bundle,
        table: envelope(short),
        entryId: member.entry_id,
        fixtures: null,
        leagueId: 0,
      }),
    ).toEqual({ ok: false, reason: "squad_not_in_table" });
  });

  it("refuses a table that is not a capture's own", () => {
    expect(
      forwardedMemberSquad({
        bundle,
        table: envelope({ ...table, contract_version: "league_device_plan_v1" }),
        entryId: member.entry_id,
        fixtures: null,
        leagueId: 0,
      }),
    ).toEqual({ ok: false, reason: "table_unreadable" });
  });
});

describe("a Free Hit walked back, with the purchase prices replayed", () => {
  const example = BUNDLE_EXAMPLES.free_hit_walk_back;
  const elements = [...Array.from({ length: 15 }, (_, index) => 101 + index), 120, 121];
  // The opening fifteen cost 995 with 5 in the bank: the season's 1000. Each risen by 2 since.
  const players = elements.map((element) => ({
    element,
    start: element <= 114 ? 66 : element === 115 ? 71 : 55,
    buy: element === 121 ? 55 : element === 120 ? 57 : (element <= 114 ? 66 : 71) + 2,
  }));
  const table = tableOf(10, players);

  it("plans from the squad before the Free Hit, at the rule's sale prices", () => {
    const built = forwardedMemberSquad({
      bundle: example,
      table: envelope(table),
      entryId: example.entry_id,
      fixtures: calendar(),
      leagueId: 0,
    });
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    const squad = built.squad.payload;
    const held = [...Array.from({ length: 13 }, (_, index) => 101 + index), 120, 121];
    expect(squad.squad_basis).toBe("pre_free_hit_gw08");
    expect(squad.active_chip).toBe("freehit");
    expect(squad.purchase_prices_known).toBe(true);
    expect(squad.free_transfers).toBe(5);
    expect(squad.free_transfers_known).toBe(true);
    const sell = Object.fromEntries(
      held.map((element) => {
        const { buy } = players.find((player) => player.element === element)!;
        const paid = element === 120 || element === 121 ? 55 : 66;
        return [String(5000 + element), sellPriceTenths(buy, paid)];
      }),
    );
    expect(squad.device_plan).toEqual({
      held: held.map((element) => 5000 + element),
      bank_tenths: 5,
      free_transfers: 5,
      sell_tenths: sell,
    });
    expect(sell["5120"]).toBe(56);
    expect(squad.squad_sell_value_tenths).toBe(
      Object.values(sell).reduce((sum, price) => sum + price, 0),
    );
    expect(squad.chips?.states.wildcard?.first_half).toMatchObject({ state: "used", gameweek: 4 });
    expect(squad.chips?.states.freehit?.first_half).toMatchObject({ state: "used", gameweek: 9 });
    expect(squad.chips?.states.bboost?.first_half?.state).toBe("available");
  });

  it("takes the server's fallback where the season's terms are not known", () => {
    const built = forwardedMemberSquad({
      bundle: example,
      table: envelope(tableOf(10, players, "2027-28")),
      entryId: example.entry_id,
      fixtures: calendar("2027-28"),
      leagueId: 0,
    });
    expect(built.ok && built.squad.payload.purchase_prices_known).toBe(false);
  });

  it("takes the server's fallback without the calendar's deadlines", () => {
    const built = forwardedMemberSquad({
      bundle: example,
      table: envelope(table),
      entryId: example.entry_id,
      fixtures: null,
      leagueId: 0,
    });
    expect(built.ok && built.squad.payload.purchase_prices_known).toBe(false);
  });
});

describe("a late joiner, priced at the current prices capped by the stated worth", () => {
  const example = BUNDLE_EXAMPLES.late_joiner;
  const elements = [...Array.from({ length: 16 }, (_, index) => 201 + index), 220];
  const table = tableOf(
    10,
    elements.map((element) => ({ element, start: 60, buy: 67 })),
  );

  it("takes the shortfall from the bank first, then from every sale price", () => {
    const built = forwardedMemberSquad({
      bundle: example,
      table: envelope(table),
      entryId: example.entry_id,
      fixtures: calendar(),
      leagueId: 0,
    });
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    const squad = built.squad.payload;
    // Fifteen at 67 is 1005 against a stated worth of 1003 less the bank of 5: 7 short.
    // The bank pays 5 of it, and every sale price the other 2.
    expect(squad.purchase_prices_known).toBe(false);
    expect(squad.squad_sell_value_tenths).toBe(998);
    expect(squad.device_plan?.bank_tenths).toBe(0);
    expect(new Set(Object.values(squad.device_plan!.sell_tenths))).toEqual(new Set([65]));
    // A history from gameweek 4 leaves the banked count unknown: one, as the server reads it.
    expect(squad.free_transfers).toBe(1);
    expect(squad.free_transfers_known).toBe(false);
    expect(squad.device_plan?.free_transfers).toBe(1);
  });
});
