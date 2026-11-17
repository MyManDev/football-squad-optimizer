export interface ClubCount {
  club: string;
  count: number;
  scope?: "squad" | "transfers_in";
}

export function clubCountKey({ club, scope = "squad" }: ClubCount): string {
  return `${club}:${scope}`;
}

export function clubCountsConflict(counts: readonly ClubCount[], holdsTransfers: boolean) {
  const incoming = new Map<string, number>();
  const squad = new Map<string, number>();
  for (const { club, count, scope } of counts) {
    const group = scope === "transfers_in" ? incoming : squad;
    const previous = group.get(club);
    if (previous !== undefined && previous !== count) return true;
    group.set(club, count);
  }
  if (holdsTransfers && incoming.size) return true;
  for (const [club, count] of incoming) {
    if ((squad.get(club) ?? count) < count) return true;
  }
  const minimums = new Map([...incoming, ...squad]);
  return [...minimums.values()].reduce((total, count) => total + count, 0) > 15;
}

export type PlanWeekNumber = 1 | 2 | 3;

export function isPlanWeek(value: unknown): value is PlanWeekNumber {
  return value === 1 || value === 2 || value === 3;
}

export interface FrozenPlanWeek {
  week: PlanWeekNumber;
  transfers_in: number[];
  transfers_out: number[];
  chip: "wildcard" | "freehit" | "bboost" | "3xc" | null;
  starting_xi?: number[];
  captain?: number;
}

export interface BankFloor {
  tenths: number;
  week?: PlanWeekNumber;
}

export type PlanScenario = { player_id: number; week?: PlanWeekNumber } & (
  { kind: "price_increase"; tenths: number } | { kind: "unavailable" }
);

interface RulePreferences {
  keep_players: number[];
  avoid_players: number[];
  no_hits: boolean;
  save_chips: boolean;
  hold_transfers?: boolean;
  include_players?: number[];
  club_counts?: ClubCount[];
}

interface WeekRulePreferences extends RulePreferences {
  buy_players?: number[];
}

/** The top-level rules apply across the window. Specific weeks can add restrictions. */
export interface DecisionPreferences extends RulePreferences {
  week_rules?: { week: PlanWeekNumber; rules: WeekRulePreferences }[];
  max_hit_points?: number;
  wildcard_week?: 2 | 3;
  hold_opening_transfers?: boolean;
  min_opening_bank_tenths?: number;
  net_points_priority?: boolean;
  frozen_weeks?: FrozenPlanWeek[];
  min_bank?: BankFloor;
  scenario?: PlanScenario;
}

function checkedClubCounts(value: unknown, holdsTransfers: boolean): ClubCount[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 16) throw new Error("Invalid club counts");
  const seen = new Set<string>();
  const counts = value.map((item: unknown): ClubCount => {
    if (item === null || typeof item !== "object" || Array.isArray(item))
      throw new Error("Invalid club count");
    const { club, count, scope } = item as Record<string, unknown>;
    if (
      Object.keys(item).some((key) => key !== "club" && key !== "count" && key !== "scope") ||
      typeof club !== "string" ||
      !club ||
      club.trim() !== club ||
      club.length > 80 ||
      /[\p{C}\p{Zl}\p{Zp}]/u.test(club) ||
      (count !== 1 && count !== 2 && count !== 3) ||
      (scope !== undefined && scope !== "squad" && scope !== "transfers_in")
    )
      throw new Error("Invalid club count");
    const rule: ClubCount = { club, count, ...(scope === "transfers_in" ? { scope } : {}) };
    const key = clubCountKey(rule);
    if (seen.has(key)) throw new Error("Repeated club count");
    seen.add(key);
    return rule;
  });
  if (clubCountsConflict(counts, holdsTransfers)) throw new Error("Conflicting club counts");
  return counts.sort(
    (a, b) =>
      (a.club < b.club ? -1 : Number(a.club > b.club)) ||
      Number(a.scope === "transfers_in") - Number(b.scope === "transfers_in"),
  );
}

function preferenceRecord(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid preferences");
  return value as Record<string, unknown>;
}

const ruleKeys = [
  "keep_players",
  "avoid_players",
  "no_hits",
  "save_chips",
  "hold_transfers",
  "include_players",
  "club_counts",
];

function expectKeys(row: Record<string, unknown>, extra: string[]) {
  if (Object.keys(row).some((key) => !ruleKeys.includes(key) && !extra.includes(key)))
    throw new Error("Unknown preference");
}

function checkedIds(value: unknown): number[] {
  if (
    !Array.isArray(value) ||
    value.length > 15 ||
    value.some((id) => !Number.isSafeInteger(id) || id < 1) ||
    new Set(value).size !== value.length
  )
    throw new Error("Invalid player preferences");
  return [...value].sort((a: number, b: number) => a - b) as number[];
}

function checkedRules(row: Record<string, unknown>): WeekRulePreferences {
  const ids = (value: unknown) => (value === undefined ? [] : checkedIds(value));
  const flag = (v: unknown): boolean => {
    if (v === undefined) return false;
    if (typeof v !== "boolean") throw new Error("Invalid preference flag");
    return v;
  };
  const hold = flag(row.hold_transfers);
  const include = ids(row.include_players);
  const buy = ids(row.buy_players);
  const clubCounts = checkedClubCounts(row.club_counts, hold);
  const result: WeekRulePreferences = {
    keep_players: ids(row.keep_players),
    avoid_players: ids(row.avoid_players),
    no_hits: flag(row.no_hits),
    save_chips: flag(row.save_chips),
    ...(hold ? { hold_transfers: true } : {}),
    ...(include.length ? { include_players: include } : {}),
    ...(clubCounts.length ? { club_counts: clubCounts } : {}),
    ...(buy.length ? { buy_players: buy } : {}),
  };
  const included = new Set([...result.keep_players, ...include, ...buy]);
  if (
    included.size > 15 ||
    result.avoid_players.some((id) => included.has(id)) ||
    // A player bought in a week is not held before it, so cannot also be kept.
    buy.some((id) => result.keep_players.includes(id)) ||
    (hold && buy.length)
  )
    throw new Error("Conflicting player preferences");
  return result;
}

function hasRules(p: WeekRulePreferences) {
  return Boolean(
    p.keep_players.length ||
    p.avoid_players.length ||
    p.no_hits ||
    p.save_chips ||
    p.hold_transfers ||
    p.include_players?.length ||
    p.club_counts?.length ||
    p.buy_players?.length,
  );
}

function checkedWeeks(value: unknown, global: RulePreferences, holdOpening: boolean) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 3) throw new Error("Invalid week rules");
  const seen = new Set<PlanWeekNumber>();
  return value
    .map((item: unknown) => {
      const row = preferenceRecord(item);
      if (Object.keys(row).length !== 2 || !isPlanWeek(row.week) || seen.has(row.week))
        throw new Error("Invalid week rule");
      seen.add(row.week);
      const fields = preferenceRecord(row.rules);
      expectKeys(fields, ["buy_players"]);
      const rules = checkedRules(fields);
      const holdsTransfers = !!(
        global.hold_transfers ||
        rules.hold_transfers ||
        (row.week === 1 && holdOpening)
      );
      const included = new Set([
        ...global.keep_players,
        ...(global.include_players ?? []),
        ...rules.keep_players,
        ...(rules.include_players ?? []),
        ...(rules.buy_players ?? []),
      ]);
      if (
        !hasRules(rules) ||
        included.size > 15 ||
        [...global.avoid_players, ...rules.avoid_players].some((id) => included.has(id)) ||
        rules.buy_players?.some(
          (id) => global.keep_players.includes(id) || rules.keep_players.includes(id),
        ) ||
        (holdsTransfers && rules.buy_players?.length) ||
        clubCountsConflict(
          [...(global.club_counts ?? []), ...(rules.club_counts ?? [])],
          holdsTransfers,
        )
      )
        throw new Error("Conflicting week rules");
      return { week: row.week, rules };
    })
    .sort((left, right) => left.week - right.week);
}

export function isHitBudget(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 60;
}

export function checkedBankFloor(value: unknown): BankFloor {
  const { tenths, week, ...extra } = preferenceRecord(value);
  if (
    Object.keys(extra).length ||
    typeof tenths !== "number" ||
    !Number.isInteger(tenths) ||
    tenths < 1 ||
    tenths > 10_000 ||
    (week !== undefined && !isPlanWeek(week))
  )
    throw new Error("Invalid minimum bank");
  return { tenths, ...(week === undefined ? {} : { week }) };
}

export function checkedScenario(value: unknown): PlanScenario {
  const { kind, player_id, week, tenths, ...extra } = preferenceRecord(value);
  if (
    Object.keys(extra).length ||
    typeof player_id !== "number" ||
    !Number.isSafeInteger(player_id) ||
    player_id < 1 ||
    (week !== undefined && !isPlanWeek(week))
  )
    throw new Error("Invalid scenario player or week");
  const scope = { player_id, ...(week === 2 || week === 3 ? { week } : {}) };
  if (kind === "unavailable" && tenths === undefined) return { kind, ...scope };
  if (
    kind === "price_increase" &&
    typeof tenths === "number" &&
    Number.isInteger(tenths) &&
    tenths >= 1 &&
    tenths <= 10_000
  )
    return { kind, ...scope, tenths };
  throw new Error("Invalid scenario change");
}

function checkedFrozenWeeks(value: unknown): FrozenPlanWeek[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 3) throw new Error("Invalid frozen weeks");
  const seen = new Set<PlanWeekNumber>();
  return value
    .map((item: unknown): FrozenPlanWeek => {
      const { week, transfers_in, transfers_out, chip, starting_xi, captain, ...extra } =
        preferenceRecord(item);
      if (
        Object.keys(extra).length ||
        !isPlanWeek(week) ||
        seen.has(week) ||
        (chip !== null &&
          chip !== "wildcard" &&
          chip !== "freehit" &&
          chip !== "bboost" &&
          chip !== "3xc")
      )
        throw new Error("Invalid frozen week");
      seen.add(week);
      const incoming = checkedIds(transfers_in);
      const outgoing = checkedIds(transfers_out);
      if (incoming.length !== outgoing.length || incoming.some((id) => outgoing.includes(id)))
        throw new Error("Invalid frozen transfers");
      const selected: FrozenPlanWeek = {
        week,
        transfers_in: incoming,
        transfers_out: outgoing,
        chip,
      };
      if (starting_xi !== undefined || captain !== undefined) {
        const starters = checkedIds(starting_xi);
        if (
          starters.length !== 11 ||
          typeof captain !== "number" ||
          !starters.includes(captain) ||
          starters.some((id) => outgoing.includes(id))
        )
          throw new Error("Invalid frozen lineup");
        selected.starting_xi = starters;
        selected.captain = captain;
      }
      return selected;
    })
    .sort((left, right) => left.week - right.week);
}

export function checkedPreferences(value: unknown): DecisionPreferences {
  const row = preferenceRecord(value === undefined ? {} : value);
  expectKeys(row, [
    "week_rules",
    "max_hit_points",
    "wildcard_week",
    "hold_opening_transfers",
    "min_opening_bank_tenths",
    "net_points_priority",
    "frozen_weeks",
    "min_bank",
    "scenario",
  ]);
  const global = checkedRules(row);
  const holdOpening = row.hold_opening_transfers;
  if (holdOpening !== undefined && typeof holdOpening !== "boolean")
    throw new Error("Invalid opening transfer hold");
  if (holdOpening && clubCountsConflict(global.club_counts ?? [], true))
    throw new Error("Conflicting opening transfer hold");
  const minOpeningBank = row.min_opening_bank_tenths;
  if (
    minOpeningBank !== undefined &&
    (typeof minOpeningBank !== "number" ||
      !Number.isInteger(minOpeningBank) ||
      minOpeningBank < 1 ||
      minOpeningBank > 10_000)
  )
    throw new Error("Invalid minimum opening bank");
  const netPointsPriority = row.net_points_priority;
  if (netPointsPriority !== undefined && typeof netPointsPriority !== "boolean")
    throw new Error("Invalid net points priority");
  const weekRules = checkedWeeks(row.week_rules, global, holdOpening === true);
  const frozenWeeks = checkedFrozenWeeks(row.frozen_weeks);
  const minBank = row.min_bank === undefined ? undefined : checkedBankFloor(row.min_bank);
  const scenario = row.scenario === undefined ? undefined : checkedScenario(row.scenario);
  for (const frozen of frozenWeeks) {
    const local = weekRules.find(({ week }) => week === frozen.week)?.rules;
    const avoided = [...global.avoid_players, ...(local?.avoid_players ?? [])];
    const required = [
      ...global.keep_players,
      ...(global.include_players ?? []),
      ...(local?.keep_players ?? []),
      ...(local?.include_players ?? []),
    ];
    if (
      (frozen.transfers_in.length &&
        (global.hold_transfers || local?.hold_transfers || (frozen.week === 1 && holdOpening))) ||
      local?.buy_players?.some((id) => !frozen.transfers_in.includes(id)) ||
      [...frozen.transfers_in, ...(frozen.starting_xi ?? [])].some((id) => avoided.includes(id)) ||
      frozen.transfers_out.some((id) => required.includes(id))
    )
      throw new Error("Frozen week conflicts with player or transfer rules");
  }
  const maxHits = row.max_hit_points;
  if (maxHits !== undefined && !isHitBudget(maxHits)) throw new Error("Invalid hit budget");
  const wildcardWeek = row.wildcard_week;
  if (wildcardWeek !== undefined) {
    if (wildcardWeek !== 2 && wildcardWeek !== 3) throw new Error("Invalid Wildcard week");
    const local = weekRules.find(({ week }) => week === wildcardWeek)?.rules;
    if (global.save_chips || global.hold_transfers || local?.save_chips || local?.hold_transfers)
      throw new Error("Conflicting Wildcard week");
  }
  return {
    ...global,
    ...(weekRules.length ? { week_rules: weekRules } : {}),
    ...(maxHits === undefined ? {} : { max_hit_points: maxHits }),
    ...(wildcardWeek === undefined ? {} : { wildcard_week: wildcardWeek }),
    ...(holdOpening ? { hold_opening_transfers: true } : {}),
    ...(minOpeningBank === undefined ? {} : { min_opening_bank_tenths: minOpeningBank }),
    ...(netPointsPriority ? { net_points_priority: true } : {}),
    ...(frozenWeeks.length ? { frozen_weeks: frozenWeeks } : {}),
    ...(minBank === undefined ? {} : { min_bank: minBank }),
    ...(scenario === undefined ? {} : { scenario }),
  };
}

export function holdsOpeningTransfers(p?: DecisionPreferences): boolean {
  return Boolean(
    p?.hold_transfers ||
    p?.hold_opening_transfers ||
    p?.week_rules?.find(({ week }) => week === 1)?.rules.hold_transfers,
  );
}

export function preferencesKey(value?: DecisionPreferences): string {
  const p = checkedPreferences(value);
  return hasRules(p) ||
    p.max_hit_points !== undefined ||
    p.net_points_priority ||
    preferenceScope(p) === "selected_weeks"
    ? JSON.stringify(p)
    : "";
}

export function preferenceScope(p?: DecisionPreferences) {
  return p?.week_rules?.length ||
    p?.wildcard_week ||
    p?.hold_opening_transfers ||
    p?.min_opening_bank_tenths !== undefined ||
    p?.frozen_weeks?.length ||
    p?.min_bank !== undefined ||
    p?.scenario !== undefined
    ? "selected_weeks"
    : "all_selected_weeks";
}

export function preferencesFromUrl(params: URLSearchParams): {
  value?: DecisionPreferences;
  valid: boolean;
} {
  const raw = params.get("preferences");
  if (raw === null) return { valid: true };
  try {
    if (raw.length > 3000) throw new Error("Too long");
    const value = checkedPreferences(JSON.parse(raw));
    return { value: preferencesKey(value) ? value : undefined, valid: true };
  } catch {
    return { valid: false };
  }
}
