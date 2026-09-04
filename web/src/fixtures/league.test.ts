import { describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "./league";

describe("provisional league fixtures", () => {
  it("keeps ten human members and one explicit system member inside the envelope", () => {
    const envelope = mockLeagueMembersEnvelope;
    const humans = envelope.payload.members.filter((member) => member.member_kind === "human");
    const system = envelope.payload.members.filter((member) => member.member_kind === "system");
    const ids = humans.map((member) => member.entry_id);

    expect(envelope.contract_version).toBe("provisional_league_ui_v1");
    expect(envelope.source_kind).toBe("example");
    expect(ids).toHaveLength(10);
    expect(new Set(ids).size).toBe(ids.length);
    expect(system).toHaveLength(1);
    expect(system[0]).toMatchObject({ entry_id: null, team_name: "SquadOpt" });
    expect(Object.keys(mockEntrySquadEnvelopes)).toHaveLength(ids.length);
  });

  it("contains both partial and empty edge cases without inventing picks", () => {
    const squads = Object.values(mockEntrySquadEnvelopes).map((entry) => entry.payload);
    const partial = squads.find((entry) => entry.data_quality === "partial");
    const empty = squads.find((entry) => entry.data_quality === "empty");

    expect(partial?.missing_fields.length).toBeGreaterThan(0);
    expect(partial?.starting_xi.length).toBeLessThan(11);
    expect(empty?.starting_xi).toEqual([]);
    expect(empty?.bench).toEqual([]);
  });

  it("keeps complete squads valid while varying membership and formation", () => {
    const complete = Object.values(mockEntrySquadEnvelopes)
      .map((entry) => entry.payload)
      .filter((entry) => entry.data_quality === "complete");

    for (const entry of complete) {
      const squad = [...entry.starting_xi, ...entry.bench];
      const positions = squad.reduce<Record<string, number>>((counts, player) => {
        counts[player.position] = (counts[player.position] ?? 0) + 1;
        return counts;
      }, {});

      expect(entry.starting_xi).toHaveLength(11);
      expect(entry.bench).toHaveLength(4);
      expect(new Set(squad.map((player) => player.player_id)).size).toBe(15);
      expect(positions).toEqual({ GK: 2, DEF: 5, MID: 5, FWD: 3 });
      expect(entry.starting_xi.filter((player) => player.is_captain)).toHaveLength(1);
    }

    const squadSignatures = complete.map((entry) =>
      [...entry.starting_xi, ...entry.bench]
        .map((player) => player.player_id)
        .sort((left, right) => left - right)
        .join(","),
    );
    const formationSignatures = complete.map((entry) =>
      ["DEF", "MID", "FWD"]
        .map(
          (position) => entry.starting_xi.filter((player) => player.position === position).length,
        )
        .join("-"),
    );
    expect(new Set(squadSignatures).size).toBeGreaterThan(1);
    expect(new Set(formationSignatures).size).toBeGreaterThan(1);
  });

  it("keys advice to the requested entry, mode and window", () => {
    const advice = mockEntryAdviceEnvelope(35249001, "agresif", 3).payload;

    expect(advice).toMatchObject({ entry_id: 35249001, mode: "agresif", window: 3 });
    expect(advice.moves[0]?.expected_points_cost).toBeGreaterThan(0);
  });

  it("records unknown transfer and purchase-price inputs without silently trusting them", () => {
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;

    expect(squad.free_transfers).toBe(1);
    expect(squad.free_transfers_known).toBe(false);
    expect(squad.purchase_prices_known).toBe(false);
    expect(squad.source_snapshot_id).toBeTruthy();
  });

  it("keeps the settled system comparison arithmetically consistent", () => {
    const comparison = mockEntrySquadEnvelopes[35249001]!.payload.squadopt_comparison;

    expect(comparison).not.toBeNull();
    expect(comparison!.difference_points).toBe(
      comparison!.member_gameweek_points - comparison!.squadopt_gameweek_points,
    );
  });
});
