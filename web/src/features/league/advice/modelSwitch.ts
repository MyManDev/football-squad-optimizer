import { rememberCount } from "../../../design/countMotion";
import { MOTION_EASE, motionDuration } from "../../../design/motion";
import type { EntryAdvice } from "../types";

/**
 * What a switch of prediction model changed in the shown plan (#1131): the players who are in
 * the new plan and were not in the plan the other model gave for the same selection, and the
 * difference in the week's net expected points. Only a model switch counts. A switch of
 * strategy, window, rival, weight, word or chip is a different selection, and a new plan under
 * the same model is a new publish, not a model's doing.
 */
export interface ModelChange {
  from: PlanModel;
  to: PlanModel;
  /** Player ids in the new plan's eleven and bench that the other model's plan did not have. */
  changed: ReadonlySet<number>;
  /** New net minus old net, in expected points; null where either is not stated. */
  difference: number | null;
  /** Names this change for the page session, so its difference counts once from zero. */
  key: string;
}

export type PlanModel = "current" | "football";

interface Shown {
  model: PlanModel;
  players: string;
  ids: number[];
  net: number | null;
  change: ModelChange | null;
}

// The plan last shown for each selection, for the page's life.
const shown = new Map<string, Shown>();

export function planModel(view: EntryAdvice): PlanModel {
  return view.prediction_model?.id === "football" ? "football" : "current";
}

/** The selection a plan answers, the model left out. */
function selection(view: EntryAdvice): string {
  return [
    view.league_id,
    view.entry_id,
    view.gameweek,
    view.mode,
    view.window,
    view.rival_entry_id ?? "-",
    view.top100?.weight ?? 0,
    view.evidence === undefined ? 0 : 1,
    view.chip ?? "-",
  ].join(":");
}

function playerIds(view: EntryAdvice): number[] {
  return [...(view.starting_xi ?? []), ...(view.bench ?? [])].map((player) => player.player_id);
}

/** The first week's net expected points, the figure the plan's own counter shows. */
function net(view: EntryAdvice): number | null {
  const points = view.expected_own_points;
  const hit = view.transfer_hit_points ?? 0;
  return typeof points === "number" && Number.isFinite(points) && Number.isFinite(hit)
    ? points - hit
    : null;
}

/**
 * The model change the shown plan answers, or null. Asking again for the same plan gives the
 * same answer, so the pitch and the decision can both ask in one render; the change stays
 * until the selection shows another plan. The first change of a key primes its difference's
 * counter at zero, so the difference counts up from nothing once.
 */
export function modelChangeOf(view: EntryAdvice | null | undefined): ModelChange | null {
  if (!view) return null;
  const ids = playerIds(view);
  if (ids.length === 0) return null;
  const slot = selection(view);
  const model = planModel(view);
  const players = [...ids].sort((a, b) => a - b).join(",");
  const last = shown.get(slot);
  if (last && last.model === model && last.players === players) return last.change;
  let change: ModelChange | null = null;
  if (last && last.model !== model) {
    const before = new Set(last.ids);
    const now = net(view);
    const key = `model-diff:${slot}:${last.model}>${model}:${last.players}>${players}`;
    change = {
      from: last.model,
      to: model,
      changed: new Set(ids.filter((id) => !before.has(id))),
      difference: now !== null && last.net !== null ? now - last.net : null,
      key,
    };
    // Primed at zero: the counter's next showing of this key counts up to the difference,
    // and a switch back and forth to the same pair counts it again.
    rememberCount(key, 0);
  }
  shown.set(slot, { model, players, ids, net: net(view), change });
  return change;
}

/** For tests: every selection starts unseen. */
export function forgetShownPlans(): void {
  shown.clear();
  popped.clear();
}

/** A changed player's plate rises a little and settles, once per change: transform only. */
export const MODEL_POP: Keyframe[] = [
  { transform: "scale(1)" },
  { transform: "scale(1.08)", offset: 0.4 },
  { transform: "scale(1)" },
];

// The changes whose plates have moved, for the page's life.
const popped = new Set<string>();

/**
 * Moves the changed players' plates once for a change: the first time its pitch is drawn,
 * not on a re-render or a remount. Returns the animations, none under reduced motion or
 * without the Web Animations API, where the static mark alone shows the change.
 */
export function popChanged(key: string, plates: HTMLElement[]): Animation[] {
  if (popped.has(key)) return [];
  popped.add(key);
  const duration = motionDuration("data");
  if (duration === 0) return [];
  return plates
    .filter((plate) => typeof plate.animate === "function")
    .map((plate) =>
      plate.animate(MODEL_POP, {
        duration,
        easing: `cubic-bezier(${MOTION_EASE.join(", ")})`,
      }),
    );
}

/** Lets a change's plates move again, for a motion a remount stopped before it ended. */
export function releasePop(key: string): void {
  popped.delete(key);
}
