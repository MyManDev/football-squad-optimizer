/** The Python chip_forecast_v1 rule on explicit inputs, without display copy. */
export const CHIP_NAMES = ["wildcard", "freehit", "bboost", "3xc"] as const;
export type ChipName = (typeof CHIP_NAMES)[number];
export type ThresholdPolicy = "fixed" | "decaying";
export const MEASURED_THRESHOLD_POLICY = "decaying";
export const MEASURED_RESERVATION = false;
export const PROTOCOL_HOLDING_VALUES = { bboost: 20, "3xc": 18, wildcard: 12, freehit: 15 };

export interface HeldChip {
  name: ChipName;
  first_gameweek: number;
  last_gameweek: number;
  gain_this_week: number | null;
}
export interface SquadRow {
  player_id: number;
  club_id: number;
  position: "GK" | "DEF" | "MID" | "FWD";
  expected_points: number;
  bench_order: number | null;
  is_captain: boolean;
}
export interface GameweekFixtures {
  gameweek: number;
  fixture_count_by_club: Record<number, number>;
}
export interface ChipForecastInputs {
  decision_gameweek: number;
  chips: HeldChip[];
  squad: SquadRow[];
  calendar: GameweekFixtures[];
  holding_values: Partial<Record<ChipName, number>>;
  threshold: ThresholdPolicy;
  reserve: boolean;
}
export interface PointsAt {
  gameweek: number;
  estimated_gain: number;
  threshold: number;
  player_ids: number[];
}
export interface ChipReading {
  name: ChipName;
  window: { first_gameweek: number; last_gameweek: number };
  holding_value: number;
  verdict: "play_now" | "hold" | "unknown_this_week" | "window_not_open" | "expired_window";
  hold_reason: "gain_not_above_threshold" | "reserved_for_structured_gameweek" | null;
  gain_this_week: number | null;
  threshold_this_week: number | null;
  reservation_allows_this_week: boolean | null;
  points_at_gameweek: PointsAt | null;
  structured_gameweeks: { gameweek: number; clubs_doubling: number; clubs_blank: number }[] | null;
}

export class ChipForecastError extends Error {}

function requireInput(ok: boolean, message: string): void {
  if (!ok) throw new ChipForecastError(message);
}
function positiveInteger(value: number, label: string): void {
  requireInput(Number.isInteger(value) && value > 0, `${label} must be a positive integer.`);
}
function finite(value: number, label: string): void {
  requireInput(typeof value === "number" && Number.isFinite(value), `${label} must be finite.`);
}
function policy(value: string): void {
  requireInput(value === "fixed" || value === "decaying", "Unknown threshold policy.");
}
function clubKeys(week: GameweekFixtures): number[] {
  return Object.keys(week.fixture_count_by_club)
    .map(Number)
    .sort((a, b) => a - b);
}

function checked(inputs: ChipForecastInputs): ChipForecastInputs {
  positiveInteger(inputs.decision_gameweek, "decision_gameweek");
  policy(inputs.threshold);
  requireInput(typeof inputs.reserve === "boolean", "reserve must be a boolean.");
  const names = inputs.chips.map((chip) => chip.name);
  requireInput(new Set(names).size === names.length, "A chip is held once in a half.");
  for (const [name, value] of Object.entries(inputs.holding_values)) {
    requireInput(CHIP_NAMES.includes(name as ChipName), "Unknown holding-value chip.");
    finite(value, "holding_value");
    requireInput(value >= 0, "Holding value must not be negative.");
  }
  for (const chip of inputs.chips) {
    requireInput(CHIP_NAMES.includes(chip.name), "Unknown chip.");
    positiveInteger(chip.first_gameweek, "first_gameweek");
    positiveInteger(chip.last_gameweek, "last_gameweek");
    requireInput(chip.last_gameweek >= chip.first_gameweek, "Chip window ends before it starts.");
    requireInput(inputs.holding_values[chip.name] !== undefined, "Missing holding value.");
    if (chip.gain_this_week !== null) {
      finite(chip.gain_this_week, "gain_this_week");
      requireInput(
        chip.first_gameweek <= inputs.decision_gameweek &&
          inputs.decision_gameweek <= chip.last_gameweek,
        "A chip gain must be inside its window.",
      );
    }
  }
  const ids = inputs.squad.map((row) => row.player_id);
  requireInput(
    ids.length === 15 && new Set(ids).size === 15,
    "The squad must be 15 distinct players.",
  );
  for (const row of inputs.squad) {
    positiveInteger(row.player_id, "player_id");
    positiveInteger(row.club_id, "club_id");
    requireInput(["GK", "DEF", "MID", "FWD"].includes(row.position), "Unknown player position.");
    finite(row.expected_points, "expected_points");
    requireInput(
      row.bench_order === null ||
        (Number.isInteger(row.bench_order) && row.bench_order >= 1 && row.bench_order <= 4),
      "Bench order must be from 1 to 4.",
    );
    requireInput(typeof row.is_captain === "boolean", "Captain flag must be a boolean.");
  }
  const bench = inputs.squad
    .flatMap((row) => (row.bench_order === null ? [] : [row.bench_order]))
    .sort();
  requireInput(bench.join(",") === "1,2,3,4", "The bench must list each order once.");
  const captains = inputs.squad.filter((row) => row.is_captain);
  requireInput(
    captains.length === 1 && captains[0]!.bench_order === null,
    "The eleven must hold exactly one captain.",
  );
  const calendar = [...inputs.calendar].sort((a, b) => a.gameweek - b.gameweek);
  requireInput(
    calendar.length > 0 && calendar[0]!.gameweek === inputs.decision_gameweek,
    "Calendar must start at the decision gameweek.",
  );
  const clubs = clubKeys(calendar[0]!);
  for (const [index, week] of calendar.entries()) {
    positiveInteger(week.gameweek, "gameweek");
    requireInput(
      week.gameweek === inputs.decision_gameweek + index,
      "Calendar weeks must be consecutive and unique.",
    );
    const keys = clubKeys(week);
    requireInput(keys.length > 0, "Calendar lists no club.");
    for (const club of keys) {
      positiveInteger(club, "club_id");
      const count = week.fixture_count_by_club[club]!;
      requireInput(
        Number.isInteger(count) && count >= 0,
        "Fixture count must be a nonnegative integer.",
      );
    }
    requireInput(keys.join(",") === clubs.join(","), "Calendar weeks must list the same clubs.");
  }
  for (const row of inputs.squad) {
    requireInput(clubs.includes(row.club_id), "Calendar does not list a squad club.");
    requireInput(
      calendar[0]!.fixture_count_by_club[row.club_id] !== 0 || row.expected_points === 0,
      "Blank club must have zero projected points.",
    );
  }
  const needed = Math.max(
    inputs.decision_gameweek,
    ...inputs.chips
      .filter((chip) => chip.last_gameweek >= inputs.decision_gameweek)
      .map((chip) => chip.last_gameweek),
  );
  requireInput(calendar.at(-1)!.gameweek >= needed, "Calendar ends before a held window.");
  return { ...inputs, calendar };
}

export function holdingThreshold(
  policyName: ThresholdPolicy,
  holding: number,
  first: number,
  last: number,
  week: number,
): number {
  policy(policyName);
  requireInput(first <= week && week <= last, "Gameweek is outside the chip window.");
  if (policyName === "fixed") return holding;
  return last - first <= 0 ? 0 : (holding * (last - week)) / (last - first);
}
export function scaledExpectedPoints(points: number, now: number, later: number): number | null {
  return now <= 0 ? null : Math.max(0, (points * later) / now);
}
function structure(week: GameweekFixtures) {
  const counts = Object.values(week.fixture_count_by_club);
  return {
    gameweek: week.gameweek,
    clubs_doubling: counts.filter((count) => count >= 2).length,
    clubs_blank: counts.filter((count) => count === 0).length,
  };
}
function reservationAllows(chip: HeldChip, week: GameweekFixtures, reserve: boolean): boolean {
  if (!reserve || week.gameweek === chip.last_gameweek) return true;
  const counts = structure(week);
  if (chip.name === "bboost") return counts.clubs_doubling > 0;
  if (chip.name === "freehit") return counts.clubs_doubling > 0 || counts.clubs_blank > 0;
  return true;
}
function preciseSum(values: number[]): number {
  const partials: number[] = [];
  for (let value of values) {
    let index = 0;
    for (let part of partials) {
      if (Math.abs(value) < Math.abs(part)) [value, part] = [part, value];
      const high = value + part;
      const low = part - (high - value);
      if (low !== 0) partials[index++] = low;
      value = high;
    }
    partials.length = index;
    partials.push(value);
  }
  return partials.reduce((sum, value) => sum + value, 0);
}
function estimate(
  chip: HeldChip,
  inputs: ChipForecastInputs,
  week: GameweekFixtures,
): { gain: number; players: number[] } | null {
  const now = inputs.calendar[0]!.fixture_count_by_club;
  const rows = inputs.squad.flatMap((row) => {
    if (chip.name === "bboost" && row.bench_order === null) return [];
    const value = scaledExpectedPoints(
      row.expected_points,
      now[row.club_id]!,
      week.fixture_count_by_club[row.club_id]!,
    );
    return value === null ? [] : [{ value, player: row.player_id }];
  });
  if (rows.length === 0) return null;
  if (chip.name === "bboost")
    return {
      gain: preciseSum(rows.map((row) => row.value)),
      players: rows.map((row) => row.player).sort((a, b) => a - b),
    };
  rows.sort((a, b) => b.value - a.value || a.player - b.player);
  return { gain: rows[0]!.value, players: [rows[0]!.player] };
}
function pointsAt(
  chip: HeldChip,
  inputs: ChipForecastInputs,
  later: GameweekFixtures[],
): PointsAt | null {
  if (chip.name !== "3xc" && chip.name !== "bboost") return null;
  for (const week of later) {
    if (!reservationAllows(chip, week, inputs.reserve)) continue;
    const estimated = estimate(chip, inputs, week);
    const threshold = holdingThreshold(
      inputs.threshold,
      inputs.holding_values[chip.name]!,
      chip.first_gameweek,
      chip.last_gameweek,
      week.gameweek,
    );
    if (estimated !== null && estimated.gain > threshold)
      return {
        gameweek: week.gameweek,
        estimated_gain: estimated.gain,
        threshold,
        player_ids: estimated.players,
      };
  }
  return null;
}
function reading(chip: HeldChip, inputs: ChipForecastInputs): ChipReading {
  const now = inputs.decision_gameweek;
  const result: ChipReading = {
    name: chip.name,
    window: { first_gameweek: chip.first_gameweek, last_gameweek: chip.last_gameweek },
    holding_value: inputs.holding_values[chip.name]!,
    verdict: "expired_window",
    hold_reason: null,
    gain_this_week: chip.gain_this_week,
    threshold_this_week: null,
    reservation_allows_this_week: null,
    points_at_gameweek: null,
    structured_gameweeks: null,
  };
  if (now > chip.last_gameweek) return result;
  const later = inputs.calendar.filter(
    (week) =>
      now < week.gameweek &&
      chip.first_gameweek <= week.gameweek &&
      week.gameweek <= chip.last_gameweek,
  );
  result.points_at_gameweek = pointsAt(chip, inputs, later);
  if (chip.name === "freehit")
    result.structured_gameweeks = later
      .map(structure)
      .filter((week) => week.clubs_doubling > 0 || week.clubs_blank > 0);
  if (now < chip.first_gameweek) {
    result.verdict = "window_not_open";
    result.points_at_gameweek = null;
    return result;
  }
  result.threshold_this_week = holdingThreshold(
    inputs.threshold,
    result.holding_value,
    chip.first_gameweek,
    chip.last_gameweek,
    now,
  );
  result.reservation_allows_this_week = reservationAllows(
    chip,
    inputs.calendar[0]!,
    inputs.reserve,
  );
  if (!result.reservation_allows_this_week) {
    result.verdict = "hold";
    result.hold_reason = "reserved_for_structured_gameweek";
  } else if (chip.gain_this_week === null) result.verdict = "unknown_this_week";
  else if (chip.gain_this_week > result.threshold_this_week) {
    result.verdict = "play_now";
    result.points_at_gameweek = null;
  } else {
    result.verdict = "hold";
    result.hold_reason = "gain_not_above_threshold";
  }
  return result;
}

export function chipForecast(raw: ChipForecastInputs) {
  const inputs = checked(raw);
  const now = inputs.calendar[0]!.fixture_count_by_club;
  return {
    contract_version: "chip_forecast_v1",
    decision_gameweek: inputs.decision_gameweek,
    threshold_policy: inputs.threshold,
    reserve: inputs.reserve,
    later_week_basis: "this_week_projection_scaled_by_relative_fixture_count_v1",
    players_without_fixture_this_week: inputs.squad
      .filter((row) => now[row.club_id] === 0)
      .map((row) => row.player_id)
      .sort((a, b) => a - b),
    chips: CHIP_NAMES.flatMap((name) => {
      const chip = inputs.chips.find((held) => held.name === name);
      return chip ? [reading(chip, inputs)] : [];
    }),
  };
}
