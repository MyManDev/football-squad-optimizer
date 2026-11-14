import { describe, expect, it } from "vitest";

import { preparePlans } from "./intent";

describe("confirmed LLMOPT rules", () => {
  const held = new Set([7, 11, 15]);

  it("compares a hard no-hits rule with the same rule and a preferred transfer roll", () => {
    const draft = preparePlans(
      { hard: [{ kind: "no_hits" }], soft: [{ kind: "hold_transfers" }] },
      held,
    );
    expect(draft.base).toMatchObject({
      chip: null,
      preferences: { no_hits: true, save_chips: true },
    });
    expect(draft.alternative).toMatchObject({
      chip: null,
      preferences: { no_hits: true, hold_transfers: true, save_chips: true },
    });
  });

  it("refuses to relax a required transfer roll when the required player is not held", () => {
    const draft = preparePlans(
      { hard: [{ kind: "hold_transfers" }, { kind: "include_player", player_id: 18 }], soft: [] },
      held,
    );
    expect(draft).toMatchObject({ hardConflict: true, base: null, alternative: null });
  });

  it("keeps the base when a preferred transfer conflicts with holding", () => {
    const draft = preparePlans(
      { hard: [{ kind: "hold_transfers" }], soft: [{ kind: "include_player", player_id: 18 }] },
      held,
    );
    expect(draft).toMatchObject({
      hardConflict: false,
      alternativeConflict: true,
      alternative: null,
    });
    expect(draft.base?.preferences).toMatchObject({ hold_transfers: true });
  });

  it("builds explicit with and without plans without removing the hard rules", () => {
    const draft = preparePlans(
      {
        hard: [{ kind: "keep_player", player_id: 11 }],
        soft: [{ kind: "hold_transfers" }],
        comparison: { kind: "include_player", player_id: 18, both: true },
      },
      held,
    );
    expect(draft.base?.preferences).toMatchObject({ keep_players: [11], avoid_players: [18] });
    expect(draft.alternative?.preferences).toMatchObject({
      keep_players: [11],
      include_players: [18],
    });
    expect(draft.alternative?.preferences.hold_transfers).toBeUndefined();
  });

  it("does not schedule a second solution when the two requested sets are identical", () => {
    const draft = preparePlans(
      { hard: [{ kind: "no_hits" }], soft: [], comparison: { kind: "no_hits" } },
      held,
    );
    expect(draft.alternative).toBeNull();
    expect(draft.alternativeConflict).toBe(false);
  });

  it("reports a squad-size conflict for more than fifteen mandatory players", () => {
    const hard = Array.from({ length: 16 }, (_, i) => ({
      kind: "include_player" as const,
      player_id: i + 1,
    }));
    expect(preparePlans({ hard, soft: [] }, held).hardConflict).toBe(true);
  });

  it("keeps all hard player rules and plays a required Wildcard on each branch", () => {
    const plans = preparePlans(
      {
        hard: [
          { kind: "wildcard" },
          { kind: "keep_player", player_id: 11 },
          { kind: "avoid_player", player_id: 15 },
        ],
        soft: [{ kind: "include_player", player_id: 18 }],
      },
      held,
    );
    expect(plans.base).toMatchObject({
      chip: "wildcard",
      preferences: { keep_players: [11], avoid_players: [15], save_chips: false },
    });
    expect(plans.alternative).toMatchObject({
      chip: "wildcard",
      preferences: {
        keep_players: [11],
        avoid_players: [15],
        include_players: [18],
        save_chips: false,
      },
    });
  });

  it("preserves the ordinary plan when comparing a preferred Wildcard", () => {
    const plans = preparePlans({ hard: [{ kind: "no_hits" }], soft: [{ kind: "wildcard" }] }, held);
    expect(plans.base).toMatchObject({
      chip: null,
      preferences: { no_hits: true, save_chips: true },
    });
    expect(plans.alternative).toMatchObject({
      chip: "wildcard",
      preferences: { no_hits: true, save_chips: false },
    });
  });

  it.each(["hold_transfers", "save_chips"] as const)("does not relax a required %s", (kind) => {
    const hard = [{ kind }] as const;
    const required = preparePlans({ hard: [...hard, { kind: "wildcard" }], soft: [] }, held);
    expect(required).toMatchObject({ base: null, alternative: null, hardConflict: true });
    const preferred = preparePlans({ hard: [...hard], soft: [{ kind: "wildcard" }] }, held);
    expect(preferred).toMatchObject({
      base: { chip: null },
      alternative: null,
      alternativeConflict: true,
      hardConflict: false,
    });
  });
});
