import { checkedScenario } from "../advice/decisionPreferences";
import { isAdvicePayload } from "../advice/adviceShape";
import type { AdvicePlayer, AdvicePlanWeek, EntryAdvice, EntrySquad } from "../types";
import { plannedWeeks } from "./planComparison";

export const PLAN_HISTORY_LIMIT = 12;
const DIGEST = /^[0-9a-f]{64}$/;
export interface SavedPlan {
  id: string;
  plan: EntryAdvice;
}
export interface PlanHistory {
  explicit?: boolean;
  items: SavedPlan[];
  navigation: string[];
  cursor: number;
}
export const EMPTY_HISTORY: PlanHistory = { items: [], navigation: [], cursor: -1 };
export interface PlanCommand {
  plan_id: string;
  action: "select" | "freeze_transfer" | "freeze_week" | "substitute";
  week?: 1 | 2 | 3;
  player_id?: number;
  replacement_id?: number;
}
export interface PlanContext {
  data_id: string;
  kind: "device" | "server";
  selected_plan_id: string | null;
  plans: {
    plan_id: string;
    data_id: string;
    weeks: {
      week: number;
      transfers_in: number[];
      transfers_out: number[];
      chip: string | null;
      captain: number | null;
      players: number[];
    }[];
  }[];
}

function player(p: AdvicePlayer): AdvicePlayer {
  return {
    player_id: p.player_id,
    name: p.name,
    short_name: p.short_name,
    position: p.position,
    team: p.team,
    ...(p.expected_points === undefined ? {} : { expected_points: p.expected_points }),
  };
}
function lineup(p: {
  starting_xi: AdvicePlayer[];
  bench: AdvicePlayer[];
  captain: AdvicePlayer;
  vice_captain: AdvicePlayer;
}) {
  return {
    starting_xi: p.starting_xi.map(player),
    bench: p.bench.map(player),
    captain: player(p.captain),
    vice_captain: player(p.vice_captain),
  };
}
function expectation(p: NonNullable<EntryAdvice["lineup_expectation"]>) {
  return {
    version: p.version,
    expected_net_points: p.expected_net_points,
    starting_points: p.starting_points,
    autosub_points: p.autosub_points,
    captain_bonus_points: p.captain_bonus_points,
    vice_bonus_points: p.vice_bonus_points,
    bench_boost_points: p.bench_boost_points,
    assumptions: [],
  };
}
function week(w: AdvicePlanWeek): AdvicePlanWeek {
  return {
    gameweek: w.gameweek,
    transfers_in: w.transfers_in.map(player),
    transfers_out: w.transfers_out.map(player),
    chip: w.chip,
    transfer_hit_points: w.transfer_hit_points,
    expected_points: w.expected_points,
    free_transfers_before: w.free_transfers_before,
    free_transfers_after: w.free_transfers_after,
    ...(w.bank_after_tenths === undefined ? {} : { bank_after_tenths: w.bank_after_tenths }),
    ...(w.lineup ? { lineup: lineup(w.lineup) } : {}),
    ...(w.lineup_expectation ? { lineup_expectation: expectation(w.lineup_expectation) } : {}),
  };
}

/** Explicitly copied computed fields; unknown fields and credentials cannot reach storage. */
export function retainedPlan(p: EntryAdvice): EntryAdvice {
  const result: EntryAdvice = {
    league_id: p.league_id,
    entry_id: p.entry_id,
    season: p.season,
    gameweek: p.gameweek,
    source_snapshot_id: p.source_snapshot_id,
    mode: p.mode,
    window: p.window,
    moves: p.moves.map((m) => ({
      move_id: m.move_id,
      player_in: m.player_in && player(m.player_in),
      player_out: m.player_out && player(m.player_out),
      reason_code: m.reason_code,
      expected_points_delta: m.expected_points_delta,
    })),
    data_quality: p.data_quality,
    missing_fields: [],
  };
  for (const key of [
    "bank_after_tenths",
    "free_transfers_after",
    "transfer_hit_points",
    "expected_own_points",
    "expected_gain_vs_hold",
    "chip",
  ] as const)
    if (p[key] !== undefined) Object.assign(result, { [key]: p[key] });
  for (const key of ["plan_data_id", "device_input_fingerprint"] as const)
    if (typeof p[key] === "string" && DIGEST.test(p[key])) result[key] = p[key];
  for (const key of ["starting_xi", "bench"] as const) if (p[key]) result[key] = p[key].map(player);
  for (const key of ["captain", "vice_captain"] as const) if (p[key]) result[key] = player(p[key]);
  if (p.prediction_model)
    result.prediction_model = {
      id: p.prediction_model.id,
      version: p.prediction_model.version,
      experimental: p.prediction_model.experimental,
      fingerprint: p.prediction_model.fingerprint,
    };
  if (p.preferences?.scenario)
    result.preferences = {
      keep_players: [],
      avoid_players: [],
      no_hits: false,
      save_chips: false,
      scenario: checkedScenario(p.preferences.scenario),
    };
  if (p.lineup_expectation) result.lineup_expectation = expectation(p.lineup_expectation);
  if (p.plan_weeks) result.plan_weeks = p.plan_weeks.map(week);
  return result;
}

export function planData(plan: EntryAdvice) {
  if (
    typeof plan.device_input_fingerprint === "string" &&
    DIGEST.test(plan.device_input_fingerprint)
  )
    return { kind: "device" as const, id: plan.device_input_fingerprint };
  if (typeof plan.plan_data_id === "string" && DIGEST.test(plan.plan_data_id))
    return { kind: "server" as const, id: plan.plan_data_id };
  return null;
}

function canonical(value: unknown, key = ""): unknown {
  if (typeof value === "number") return Math.round(value * 1e8) / 1e8;
  if (Array.isArray(value)) {
    const items = value.map((v) => canonical(v));
    if (["starting_xi", "transfers_in", "transfers_out"].includes(key))
      items.sort(
        (a, b) =>
          Number((a as { player_id: number }).player_id) -
          Number((b as { player_id: number }).player_id),
      );
    if (key === "plan_weeks")
      items.sort(
        (a, b) =>
          Number((a as { gameweek: number }).gameweek) -
          Number((b as { gameweek: number }).gameweek),
      );
    if (key === "moves")
      items.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b), "en"));
    return items;
  }
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .filter(
          ([k, v]) =>
            v !== undefined &&
            ![
              "name",
              "short_name",
              "team",
              "move_id",
              "reason_code",
              "data_quality",
              "missing_fields",
              "assumptions",
            ].includes(k),
        )
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => [k, canonical(v, k)]),
    );
  return value;
}
export function planContent(plan: EntryAdvice): string {
  return JSON.stringify(canonical(retainedPlan(plan)));
}
export async function planIdentity(plan: EntryAdvice): Promise<string> {
  const bytes = new TextEncoder().encode(planContent(plan));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function checkedHistory(value: unknown, squad: EntrySquad): PlanHistory {
  if (!value || typeof value !== "object") return EMPTY_HISTORY;
  const h = value as PlanHistory;
  if (
    (h.explicit !== undefined && typeof h.explicit !== "boolean") ||
    !Array.isArray(h.items) ||
    h.items.length > PLAN_HISTORY_LIMIT ||
    !Array.isArray(h.navigation) ||
    h.navigation.length > 40 ||
    !Number.isInteger(h.cursor) ||
    h.cursor < -1 ||
    h.cursor >= h.navigation.length
  )
    return EMPTY_HISTORY;
  const items = h.items.flatMap((item) => {
    const p = item?.plan;
    if (
      !DIGEST.test(item?.id ?? "") ||
      !isAdvicePayload(p) ||
      p.entry_id !== squad.entry.entry_id ||
      p.league_id !== squad.league_id ||
      p.season !== squad.season ||
      p.gameweek !== squad.gameweek ||
      p.source_snapshot_id !== squad.source_snapshot_id ||
      (p.window !== 1 && p.window !== 3)
    )
      return [];
    return [{ id: item.id, plan: retainedPlan(p) }];
  });
  if (
    items.length !== h.items.length ||
    new Set(items.map((i) => i.id)).size !== items.length ||
    !h.navigation.every((id) => typeof id === "string" && items.some((i) => i.id === id))
  )
    return EMPTY_HISTORY;
  return {
    items,
    navigation: [...h.navigation],
    cursor: h.cursor,
    ...(h.explicit === undefined ? {} : { explicit: h.explicit }),
  };
}
export async function verifiedHistory(h: PlanHistory): Promise<PlanHistory> {
  const valid = await Promise.all(h.items.map(async (i) => (await planIdentity(i.plan)) === i.id));
  return valid.every(Boolean) ? h : EMPTY_HISTORY;
}
export function selectHistory(h: PlanHistory, id: string, explicit = true): PlanHistory {
  if (!h.items.some((item) => item.id === id)) return h;
  if (h.navigation[h.cursor] === id) return h.explicit === explicit ? h : { ...h, explicit };
  const navigation = [...h.navigation.slice(0, h.cursor + 1), id].slice(-40);
  return { ...h, navigation, cursor: navigation.length - 1, explicit };
}
export function addHistory(h: PlanHistory, plans: SavedPlan[]): PlanHistory {
  const items = [...h.items];
  for (const item of plans) if (!items.some((old) => old.id === item.id)) items.push(item);
  const retained = items.slice(-PLAN_HISTORY_LIMIT);
  const navigation = h.navigation.filter((id) => retained.some((i) => i.id === id));
  const selected = h.navigation[h.cursor];
  const current = {
    items: retained,
    navigation,
    ...(h.explicit === undefined ? {} : { explicit: h.explicit }),
    cursor: selected ? navigation.lastIndexOf(selected) : -1,
  };
  const first = plans.find((p) => retained.some((i) => i.id === p.id));
  return current.cursor < 0 && first ? selectHistory(current, first.id, false) : current;
}
/** Resolve only the labels presented in this message's catalogue. */
export function planIdForLabel(context: PlanContext, label: unknown): string | undefined {
  return context.plans.find(
    (plan, index) => label === `P${index + 1}` && plan.data_id === context.data_id,
  )?.plan_id;
}

export function currentPlanCommand(
  sent: PlanContext | undefined,
  current: PlanContext | undefined,
  id: string,
): boolean {
  if (!sent || !current || current.kind !== sent.kind || current.data_id !== sent.data_id)
    return false;
  const index = sent.plans.findIndex(
    (plan) => plan.plan_id === id && plan.data_id === sent.data_id,
  );
  return index >= 0 && planIdForLabel(current, `P${index + 1}`) === id;
}

export function planCatalogue(
  h: PlanHistory,
  shown: EntryAdvice[],
  allowWindow: (window: number) => boolean = () => true,
): PlanContext | undefined {
  const eligible = h.items.filter((i) => allowWindow(i.plan.window));
  const selected = eligible.find((i) => i.id === h.navigation[h.cursor]);
  const data = selected && planData(selected.plan);
  if (!data) return undefined;
  const order = shown.map(planContent);
  const items = eligible
    .filter((i) => {
      const d = planData(i.plan);
      return d?.kind === data.kind && d.id === data.id;
    })
    .sort((a, b) => {
      const ai = order.indexOf(planContent(a.plan)),
        bi = order.indexOf(planContent(b.plan));
      return (ai < 0 ? 100 : ai) - (bi < 0 ? 100 : bi);
    });
  const plans = items.flatMap((item) => {
    const p = item.plan;
    const weeks =
      plannedWeeks(p) ??
      (p.window === 1
        ? [
            {
              gameweek: p.gameweek,
              transfers_in: p.moves.flatMap((m) => (m.player_in ? [m.player_in] : [])),
              transfers_out: p.moves.flatMap((m) => (m.player_out ? [m.player_out] : [])),
              chip: p.chip ?? null,
              lineup: p.captain ? { captain: p.captain } : undefined,
            },
          ]
        : []);
    if (weeks.length !== p.window) return [];
    return [
      {
        plan_id: item.id,
        data_id: data.id,
        weeks: weeks.map((w, index) => ({
          week: index + 1,
          transfers_in: w.transfers_in.map((p) => p.player_id),
          transfers_out: w.transfers_out.map((p) => p.player_id),
          chip: w.chip,
          captain: w.lineup?.captain.player_id ?? null,
          players: [
            ...(w.lineup && "starting_xi" in w.lineup
              ? w.lineup.starting_xi
              : (p.starting_xi ?? [])),
            ...(w.lineup && "bench" in w.lineup ? w.lineup.bench : (p.bench ?? [])),
          ].map((player) => player.player_id),
        })),
      },
    ];
  });
  return plans.length && plans.some((i) => i.plan_id === selected.id)
    ? { data_id: data.id, kind: data.kind, selected_plan_id: selected.id, plans }
    : undefined;
}
