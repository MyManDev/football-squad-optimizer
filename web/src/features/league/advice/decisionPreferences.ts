/** Human constraints apply to the entire selected window; forecasts stay unchanged. */
export interface DecisionPreferences {
  keep_players: number[];
  avoid_players: number[];
  no_hits: boolean;
  save_chips: boolean;
  hold_transfers?: boolean;
  include_players?: number[];
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
  const result: DecisionPreferences = {
    keep_players: ids(row.keep_players),
    avoid_players: ids(row.avoid_players),
    no_hits: flag(row.no_hits),
    save_chips: flag(row.save_chips),
    ...(hold ? { hold_transfers: true } : {}),
    ...(include.length ? { include_players: include } : {}),
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
    p.include_players?.length
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
