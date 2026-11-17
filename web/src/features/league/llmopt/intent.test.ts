import { afterEach, describe, expect, it, vi } from "vitest";

import { checkedPreferences, preferencesKey } from "../advice/decisionPreferences";
import { readReply } from "../../../testSupport/intentReply";
import { EMPTY_DRAFT, IntentError, intentBody, intentRefusal, preparePlans } from "./intent";

afterEach(() => vi.unstubAllGlobals());

describe("confirmed LLMOPT rules", () => {
  const held = new Set([7, 11, 15]);

  it("requires the solved week's exact transfers in every revision branch", () => {
    const draft = {
      keep_weeks: [1 as const],
      min_bank: { tenths: 5, week: 2 as const },
      hard: [{ kind: "buy_player", player_id: 18, week: 2 } as const],
      soft: [{ kind: "no_hits" } as const],
    };
    const frozen = { week: 1 as const, transfers_in: [17], transfers_out: [7], chip: null };
    const plans = preparePlans(draft, held, [frozen]);
    expect(plans.window).toBe(3);
    for (const plan of [plans.base, plans.alternative]) {
      expect(plan?.preferences).toMatchObject({
        frozen_weeks: [frozen],
        min_bank: draft.min_bank,
        week_rules: [{ week: 2, rules: { buy_players: [18] } }],
      });
    }
    expect(preparePlans(draft, held).hardConflict).toBe(true);
    expect(
      preparePlans({ ...draft, hard: [{ kind: "wildcard" }] }, held, [frozen]).hardConflict,
    ).toBe(true);
  });

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

  it("rolls the first week and transfers the player in exactly next week within a total hit budget", () => {
    const plans = preparePlans(
      {
        hard: [
          { kind: "buy_player", player_id: 18, week: 2 },
          { kind: "hold_transfers", week: 1 },
          { kind: "hit_budget", points: 4 },
        ],
        soft: [],
      },
      held,
    );
    expect(plans).toMatchObject({
      window: 3,
      hardConflict: false,
      base: {
        chip: null,
        preferences: {
          save_chips: true,
          max_hit_points: 4,
          week_rules: [
            { week: 1, rules: { hold_transfers: true } },
            { week: 2, rules: { buy_players: [18] } },
          ],
        },
      },
    });
    expect(plans.base?.preferences.hold_transfers).toBeUndefined();
    expect(plans.base?.preferences.week_rules?.[1]?.rules.include_players).toBeUndefined();
  });

  it("allows a second-week Wildcard alongside first-week restrictions", () => {
    const hold = { kind: "hold_transfers", week: 1 } as const;
    const wildcard = { kind: "wildcard", week: 2 } as const;
    const valid = preparePlans({ window: 3, hard: [hold, wildcard], soft: [] }, held);
    expect(valid.base).toMatchObject({ chip: null, preferences: { wildcard_week: 2 } });
    expect(
      preparePlans({ window: 3, hard: [hold, { ...wildcard, week: 1 }], soft: [] }, held),
    ).toMatchObject({
      hardConflict: true,
      base: null,
    });
    expect(preparePlans({ window: 1, hard: [wildcard], soft: [] }, held).base).toBeNull();
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
    const result = await readReply(
      new Response(JSON.stringify({ status: "draft", draft: { hard, soft: [] } })),
      clubPlayers,
    );
    expect(intentBody(message, "tr", EMPTY_DRAFT, clubPlayers)).toMatchObject({
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
    await expect(
      readReply(
        new Response(JSON.stringify({ status: "draft", draft: { hard: [rule], soft: [] } })),
        clubPlayers,
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

describe("expected points cost limits", () => {
  const players = [{ id: 17, name: "Bukayo Saka", team: "Arsenal", held: true }];
  const preference = { kind: "keep_player", player_id: 17, max_cost_tenths: 15 } as const;

  function response(draft: unknown) {
    return readReply(new Response(JSON.stringify({ status: "draft", draft })), players);
  }

  it("keeps the exact cost limit attached to its optional preference", async () => {
    const draft = { window: 3, hard: [{ kind: "wildcard" }], soft: [preference] };
    expect(await response(draft)).toEqual({ status: "draft", draft });
  });

  it.each([
    { hard: [preference], soft: [] },
    { hard: [], soft: [], comparison: preference },
    { hard: [], soft: [{ ...preference, max_cost_tenths: -1 }] },
    { hard: [], soft: [{ ...preference, max_cost_tenths: 1.5 }] },
    { hard: [], soft: [{ ...preference, max_cost_tenths: 1001 }] },
  ])("refuses invalid or mandatory price limits", async (draft) => {
    await expect(response(draft)).rejects.toThrow();
  });
});

describe("intent refusals", () => {
  const players = [{ id: 17, name: "Example Player", team: "Brighton" }];
  const refuse = (status: number, code: string | null, headers: Record<string, string> = {}) => {
    return readReply(
      new Response(
        JSON.stringify({ contract_version: "1", error: { code, message: "operator text" } }),
        { status, headers },
      ),
      players,
    ).then(
      () => {
        throw new Error("expected a refusal");
      },
      (error: unknown) => error,
    );
  };

  it.each([
    [503, "PROVIDER_UNAVAILABLE", "busy"],
    [422, "REPLY_REFUSED", "replyInvalid"],
    [502, "PROVIDER_REPLY_CUT", "replyCut"],
    [402, "PROVIDER_ACCOUNT_REFUSED", "accountRefused"],
    [429, "RATE_LIMITED", "limited"],
    [413, "PAYLOAD_TOO_LARGE", "tooLarge"],
    [422, "VALIDATION_FAILED", "invalid"],
    [415, "UNSUPPORTED_MEDIA_TYPE", "unsupported"],
    [500, "INTERNAL", "unavailable"],
  ] as const)("names a %i %s refusal as %s", async (status, code, refusal) => {
    const error = await refuse(status, code);
    expect(error).toBeInstanceOf(IntentError);
    expect(error).toMatchObject({ status, code, retryAfterSeconds: null });
    expect(intentRefusal(error)).toBe(refusal);
  });

  it("reads the wait from Retry-After and bounds it", async () => {
    expect(await refuse(429, "RATE_LIMITED", { "Retry-After": "60" })).toMatchObject({
      retryAfterSeconds: 60,
    });
    expect(await refuse(429, "RATE_LIMITED", { "Retry-After": "999999" })).toMatchObject({
      retryAfterSeconds: 86_400,
    });
    expect(await refuse(429, "RATE_LIMITED", { "Retry-After": "0" })).toMatchObject({
      retryAfterSeconds: null,
    });
    expect(await refuse(429, "RATE_LIMITED", { "Retry-After": "soon" })).toMatchObject({
      retryAfterSeconds: null,
    });
  });

  it("falls back on the status when the body names no code", async () => {
    expect(intentRefusal(await refuse(429, null))).toBe("limited");
    expect(intentRefusal(await refuse(413, "lower case"))).toBe("tooLarge");
    expect(intentRefusal(new Error("network"))).toBe("unavailable");
  });
});
