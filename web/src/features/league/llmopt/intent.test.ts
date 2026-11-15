import { afterEach, describe, expect, it, vi } from "vitest";

import { checkedPreferences, preferencesKey } from "../advice/decisionPreferences";
import { EMPTY_DRAFT, preparePlans, readIntent } from "./intent";

afterEach(() => vi.unstubAllGlobals());

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

  it("sends exact incoming and final squad counts without selecting players", () => {
    const plans = preparePlans(
      {
        hard: [
          { kind: "club_count", club: "Brighton", count: 2, scope: "transfers_in" },
          { kind: "club_count", club: "Brighton", count: 3 },
        ],
        soft: [{ kind: "club_count", club: "Arsenal", count: 1, scope: "squad" }],
      },
      held,
    );
    expect(plans.base?.preferences.include_players).toBeUndefined();
    expect(plans.base?.preferences.club_counts).toEqual([
      { club: "Brighton", count: 3 },
      { club: "Brighton", count: 2, scope: "transfers_in" },
    ]);
    expect(plans.alternative?.preferences.club_counts).toEqual([
      { club: "Arsenal", count: 1 },
      ...plans.base!.preferences.club_counts!,
    ]);
  });

  it("keeps the hard plan when its preferred club count contradicts it", () => {
    const plans = preparePlans(
      {
        hard: [{ kind: "club_count", club: "Brighton", count: 1 }],
        soft: [{ kind: "club_count", club: "Brighton", count: 3 }],
      },
      held,
    );
    expect(plans).toMatchObject({
      base: { preferences: { club_counts: [{ club: "Brighton", count: 1 }] } },
      alternative: null,
      hardConflict: false,
      alternativeConflict: true,
    });
  });

  it("rejects buying more from a club than the requested final count", () => {
    const plans = preparePlans(
      {
        hard: [
          { kind: "club_count", club: "Brighton", count: 1 },
          { kind: "club_count", club: "Brighton", count: 2, scope: "transfers_in" },
        ],
        soft: [],
      },
      held,
    );
    expect(plans).toMatchObject({ base: null, alternative: null, hardConflict: true });
  });

  it("allows a final squad count with hold, but treats incoming club transfers as a conflict", () => {
    const plans = preparePlans(
      {
        hard: [{ kind: "hold_transfers" }, { kind: "club_count", club: "Arsenal", count: 1 }],
        soft: [{ kind: "club_count", club: "Brighton", count: 1, scope: "transfers_in" }],
      },
      held,
    );
    expect(plans).toMatchObject({
      base: { preferences: { club_counts: [{ club: "Arsenal", count: 1 }] } },
      alternative: null,
      hardConflict: false,
      alternativeConflict: true,
    });
  });
});

describe("club count transport", () => {
  const clubPlayers = [{ id: 17, name: "Example Player", team: "Brighton" }];

  it("validates canonical club names and scopes in an interpreted draft", async () => {
    const message = "Brighton'dan 3 oyuncu al.";
    const hard = [{ kind: "club_count", club: "Brighton", count: 3, scope: "transfers_in" }];
    const mock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "draft", draft: { hard, soft: [] } })),
      );
    vi.stubGlobal("fetch", mock);

    const result = await readIntent(
      "https://advice.example",
      message,
      "tr",
      EMPTY_DRAFT,
      clubPlayers,
      new AbortController().signal,
    );
    expect(JSON.parse(String(mock.mock.calls[0]?.[1]?.body))).toMatchObject({
      message,
      players: clubPlayers,
    });
    expect(result).toEqual({ status: "draft", draft: { hard, soft: [] } });
  });

  it.each([
    { kind: "club_count", club: "Fake Club", count: 2 },
    { kind: "club_count", club: "Brighton", count: 4 },
    { kind: "club_count", club: "Brighton", count: 2, scope: "starting_xi" },
    { kind: "club_count", club: "Brighton", count: 2, player_id: 17 },
  ])("refuses an invalid interpreted club count", async (rule) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "draft", draft: { hard: [rule], soft: [] } })),
        ),
    );
    await expect(
      readIntent(
        "https://advice.example",
        "Kulüpten oyuncu al.",
        "tr",
        EMPTY_DRAFT,
        clubPlayers,
        new AbortController().signal,
      ),
    ).rejects.toThrow("Invalid club count");
  });

  it("sorts exact constraints canonically and omits the default scope", () => {
    const sorted = [
      { club: "Arsenal", count: 1 },
      { club: "Brighton", count: 3 },
      { club: "Brighton", count: 2, scope: "transfers_in" },
    ];
    const unsorted = [sorted[2], { ...sorted[1], scope: "squad" }, sorted[0]];
    expect(checkedPreferences({ club_counts: unsorted }).club_counts).toEqual(sorted);
    expect(preferencesKey(checkedPreferences({ club_counts: unsorted }))).toBe(
      preferencesKey(checkedPreferences({ club_counts: sorted })),
    );
    expect(preferencesKey(checkedPreferences({ club_counts: [] }))).toBe("");
  });
});
