/** Official observations are source facts, distinct from model estimates. */
export interface OfficialInformation {
  version: "fpl_information_v1";
  season: string;
  gameweek: number;
  source_snapshot_id: string;
  observed_at: string;
  revision: string;
  source_url: "https://fantasy.premierleague.com/";
  player_count: number;
  team_count: number;
  declared_team_count: number;
  players: {
    player_id: number;
    name: string;
    team_name: string;
    status: string;
    source_chance_percent: number | null;
    source_added_at: string | null;
    news_state: "present" | "cleared" | "not_reported";
  }[];
}

export interface DecisionInformation {
  version: "football_decision_information_v1";
  revision: string;
  source_snapshot_id: string;
  observed_at: string | null;
  coach_news_bound: boolean;
  minute_components_bound: boolean;
}

const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const count = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0;
const digest = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const date = (v: unknown) => typeof v === "string" && Number.isFinite(Date.parse(v));

export function isDecisionInformation(v: unknown): v is DecisionInformation {
  return (
    record(v) &&
    Object.keys(v).length === 6 &&
    v.version === "football_decision_information_v1" &&
    digest(v.revision) &&
    typeof v.source_snapshot_id === "string" &&
    v.source_snapshot_id.length > 0 &&
    (v.observed_at === null || date(v.observed_at)) &&
    typeof v.coach_news_bound === "boolean" &&
    typeof v.minute_components_bound === "boolean"
  );
}

export function isOfficialInformation(v: unknown): v is OfficialInformation {
  return (
    record(v) &&
    Object.keys(v).length === 11 &&
    v.version === "fpl_information_v1" &&
    typeof v.season === "string" &&
    count(v.gameweek) &&
    Number(v.gameweek) > 0 &&
    typeof v.source_snapshot_id === "string" &&
    v.source_snapshot_id.length > 0 &&
    date(v.observed_at) &&
    digest(v.revision) &&
    v.source_url === "https://fantasy.premierleague.com/" &&
    count(v.player_count) &&
    count(v.team_count) &&
    count(v.declared_team_count) &&
    Number(v.team_count) <= Number(v.declared_team_count) &&
    Array.isArray(v.players) &&
    v.players.length <= Number(v.player_count) &&
    v.players.every(
      (p) =>
        record(p) &&
        Object.keys(p).length === 7 &&
        count(p.player_id) &&
        Number(p.player_id) > 0 &&
        typeof p.name === "string" &&
        typeof p.team_name === "string" &&
        typeof p.status === "string" &&
        (p.source_chance_percent === null ||
          (count(p.source_chance_percent) && Number(p.source_chance_percent) <= 100)) &&
        (p.source_added_at === null || date(p.source_added_at)) &&
        ["present", "cleared", "not_reported"].includes(String(p.news_state)),
    ) &&
    new Set(v.players.map((p: Record<string, unknown>) => p.player_id)).size === v.players.length
  );
}
