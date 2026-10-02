/** Editorial league injury rows remain distinct from verified coach statements. */
export const OFFICIAL_INJURY_LIMIT =
  "Editorial injury rows do not establish absence, expected minutes, or complete squad health.";

export interface OfficialInjuryFacts {
  contract_version: "official_pl_injuries_v1";
  season: string;
  source_url: "https://www.premierleague.com/en/latest-player-injuries";
  source_updated_at: string | null;
  observed_at: string;
  roster_clubs: string[];
  received_clubs: string[];
  missing_clubs: string[];
  incomplete_clubs: string[];
  unknown_source_clubs: string[];
  listed_rows: number;
  mapped_rows: number;
  facts: {
    player_id: number;
    club: string;
    injury: string | null;
    source_date: string | null;
    details_urls: string[];
  }[];
  limit: typeof OFFICIAL_INJURY_LIMIT;
}

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const names = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.every((name) => typeof name === "string" && name.trim().length > 0) &&
  new Set(value).size === value.length;
const nullableText = (value: unknown) => value === null || typeof value === "string";

export function isInjurySourceInstant(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

export function safeInjurySourceUrl(value: unknown): value is string {
  if (typeof value !== "string" || /[\s\\]/.test(value)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !!url.hostname && !url.username && !url.password;
  } catch {
    return false;
  }
}

export function isOfficialInjuryFacts(value: unknown): value is OfficialInjuryFacts {
  if (
    !record(value) ||
    Object.keys(value).length !== 14 ||
    value.contract_version !== "official_pl_injuries_v1" ||
    typeof value.season !== "string" ||
    !/^20[0-9]{2}-[0-9]{2}$/.test(value.season) ||
    value.source_url !== "https://www.premierleague.com/en/latest-player-injuries" ||
    !isInjurySourceInstant(value.observed_at) ||
    !(value.source_updated_at === null || isInjurySourceInstant(value.source_updated_at)) ||
    !names(value.roster_clubs) ||
    !names(value.received_clubs) ||
    !names(value.missing_clubs) ||
    !names(value.incomplete_clubs) ||
    !names(value.unknown_source_clubs) ||
    !count(value.listed_rows) ||
    Number(value.listed_rows) > 200 ||
    !count(value.mapped_rows) ||
    Number(value.mapped_rows) > Number(value.listed_rows) ||
    !Array.isArray(value.facts) ||
    value.facts.length > Number(value.mapped_rows) ||
    value.limit !== OFFICIAL_INJURY_LIMIT
  )
    return false;
  const roster = new Set(value.roster_clubs);
  const received = new Set(value.received_clubs);
  if (
    value.received_clubs.some((club) => !roster.has(club)) ||
    value.incomplete_clubs.some((club) => !received.has(club)) ||
    value.missing_clubs.some((club) => !roster.has(club) || received.has(club)) ||
    value.missing_clubs.length !== roster.size - received.size ||
    value.unknown_source_clubs.some((club) => roster.has(club))
  )
    return false;
  return (
    value.facts.every(
      (fact) =>
        record(fact) &&
        Object.keys(fact).length === 5 &&
        count(fact.player_id) &&
        Number(fact.player_id) > 0 &&
        typeof fact.club === "string" &&
        received.has(fact.club) &&
        nullableText(fact.injury) &&
        nullableText(fact.source_date) &&
        Array.isArray(fact.details_urls) &&
        fact.details_urls.length <= 5 &&
        fact.details_urls.every(safeInjurySourceUrl) &&
        new Set(fact.details_urls).size === fact.details_urls.length,
    ) && new Set(value.facts.map((fact: Record<string, unknown>) => fact.player_id)).size <= 50
  );
}
