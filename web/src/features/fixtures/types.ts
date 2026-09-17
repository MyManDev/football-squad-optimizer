/** The `fixtures_v1` document (docs/contracts/fixtures_v1.schema.json), as the page reads it. */

export interface FixtureTeam {
  team_id: number;
  name: string;
  short_name: string;
}

export interface Fixture {
  fixture_id: number;
  kickoff_utc: string | null;
  home: FixtureTeam;
  away: FixtureTeam;
  finished: boolean;
  home_score: number | null;
  away_score: number | null;
}

export interface FixtureGameweek {
  gameweek: number;
  deadline_utc: string;
  fixtures: Fixture[];
}

export interface FixturesPayload {
  season: string;
  source_snapshot_id: string;
  captured_at_utc: string;
  current_gameweek: number | null;
  unscheduled_count: number;
  gameweeks: FixtureGameweek[];
}
