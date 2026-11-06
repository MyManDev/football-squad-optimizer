import { weekLive, WeekLiveError, type WeekLive } from "./weekLive";

export interface LiveAppearance {
  element_id: number;
  fixture_id: number;
  minutes: number;
  goals: number;
  assists: number;
}

export interface LiveActivity {
  in_play_fixtures: number[];
  appearances: LiveAppearance[];
}

export interface WeekActivity {
  contract_version: "week_activity_v1";
  week: WeekLive;
  activity: LiveActivity | null;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) >= 0;
const id = (value: unknown): value is number => count(value) && value > 0;
const only = (row: Record<string, unknown>, keys: string[]) =>
  Object.keys(row).every((key) => keys.includes(key));
const need = (valid: unknown) => {
  if (!valid) throw new WeekLiveError("invalid_activity");
};

/** Activity is optional evidence; the embedded score retains the existing strict contract. */
export function weekActivity(value: unknown): WeekActivity {
  need(record(value));
  const row = value as Record<string, unknown>;
  need(
    row.contract_version === "week_activity_v1" &&
      only(row, ["contract_version", "week", "activity"]),
  );
  const week = weekLive(row.week);
  if (row.activity === null) return { contract_version: "week_activity_v1", week, activity: null };
  need(record(row.activity));
  const activity = row.activity as Record<string, unknown>;
  need(
    only(activity, ["in_play_fixtures", "appearances"]) &&
      Array.isArray(activity.in_play_fixtures) &&
      Array.isArray(activity.appearances),
  );
  const fixtures = new Map(week.fixtures.map((fixture) => [fixture.id, fixture]));
  const elements = new Map(week.elements.map((element) => [element.element_id, element]));
  const playing = activity.in_play_fixtures as unknown[];
  need(
    playing.every((fixture) => id(fixture) && fixtures.get(fixture)?.finished === false) &&
      new Set(playing).size === playing.length,
  );
  const seen = new Set<string>();
  const minutes = new Map<number, number>();
  for (const value of activity.appearances as unknown[]) {
    need(record(value));
    const appearance = value as Record<string, unknown>;
    need(
      only(appearance, ["element_id", "fixture_id", "minutes", "goals", "assists"]) &&
        id(appearance.element_id) &&
        elements.has(appearance.element_id) &&
        id(appearance.fixture_id) &&
        fixtures.has(appearance.fixture_id) &&
        count(appearance.minutes) &&
        count(appearance.goals) &&
        count(appearance.assists),
    );
    const known = value as LiveAppearance;
    const key = `${known.element_id}:${known.fixture_id}`;
    need(!seen.has(key));
    seen.add(key);
    minutes.set(known.element_id, (minutes.get(known.element_id) ?? 0) + known.minutes);
  }
  need(
    week.elements.every((element) => (minutes.get(element.element_id) ?? 0) === element.minutes),
  );
  return value as WeekActivity;
}
