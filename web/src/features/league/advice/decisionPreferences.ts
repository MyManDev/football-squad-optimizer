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

/** Human constraints apply to the entire selected window; forecasts stay unchanged. */
export interface DecisionPreferences {
  keep_players: number[];
  avoid_players: number[];
  no_hits: boolean;
  save_chips: boolean;
  hold_transfers?: boolean;
  include_players?: number[];
  club_counts?: ClubCount[];
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

export function checkedPreferences(value: unknown): DecisionPreferences {
  if (value === undefined) value = {};
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid preferences");
  const row = value as Record<string, unknown>;
  if (
    Object.keys(row).some(
      (k) =>
        ![
          "keep_players",
          "avoid_players",
          "no_hits",
          "save_chips",
          "hold_transfers",
          "include_players",
          "club_counts",
        ].includes(k),
    )
  )
    throw new Error("Unknown preference");
  const ids = (v: unknown): number[] => {
    if (v === undefined) return [];
    if (
      !Array.isArray(v) ||
      v.length > 15 ||
      v.some((id) => !Number.isSafeInteger(id) || id < 1) ||
      new Set(v).size !== v.length
    )
      throw new Error("Invalid player preferences");
    return [...v].sort((a: number, b: number) => a - b) as number[];
  };
  const flag = (v: unknown): boolean => {
    if (v === undefined) return false;
    if (typeof v !== "boolean") throw new Error("Invalid preference flag");
    return v;
  };
  const hold = flag(row.hold_transfers);
  const include = ids(row.include_players);
  const clubCounts = checkedClubCounts(row.club_counts, hold);
  const result: DecisionPreferences = {
    keep_players: ids(row.keep_players),
    avoid_players: ids(row.avoid_players),
    no_hits: flag(row.no_hits),
    save_chips: flag(row.save_chips),
    ...(hold ? { hold_transfers: true } : {}),
    ...(include.length ? { include_players: include } : {}),
    ...(clubCounts.length ? { club_counts: clubCounts } : {}),
  };
  if ([...result.keep_players, ...include].some((id) => result.avoid_players.includes(id)))
    throw new Error("Conflicting player preferences");
  return result;
}

export function preferencesKey(value?: DecisionPreferences): string {
  const p = checkedPreferences(value);
  return p.keep_players.length ||
    p.avoid_players.length ||
    p.no_hits ||
    p.save_chips ||
    p.hold_transfers ||
    p.include_players?.length ||
    p.club_counts?.length
    ? JSON.stringify(p)
    : "";
}

export function preferencesFromUrl(params: URLSearchParams): {
  value?: DecisionPreferences;
  valid: boolean;
} {
  const raw = params.get("preferences");
  if (raw === null) return { valid: true };
  try {
    if (raw.length > 1500) throw new Error("Too long");
    const value = checkedPreferences(JSON.parse(raw));
    return { value: preferencesKey(value) ? value : undefined, valid: true };
  } catch {
    return { valid: false };
  }
}
