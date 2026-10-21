import { rememberCount } from "../../../design/countMotion";
import { MOTION_EASE, motionDuration } from "../../../design/motion";
import type { EntryAdvice } from "../types";

/**
 * What a switch of prediction model changed in the shown plan (#1131): the players the new
 * plan brings into the eleven and the players it brings onto the bench from outside the
 * squad, against the plan shown just before it, and the difference in the week's net expected
 * points. Only a model switch counts: the plan shown just before must answer the same
 * selection under the other model. A switch of strategy, window, rival, weight, word or chip
 * is a different selection, and a new plan under the same model is a new publish, not a
 * model's doing.
 */
export interface ModelChange {
  from: PlanModel;
  to: PlanModel;
  /**
   * Player ids the new plan brings into the eleven, from the bench or from outside, and the
   * ids it brings onto the bench from outside the other plan's fifteen. Every one of them is
   * marked on the pitch or the bench, so the line's count is the number of marks.
   */
  changed: ReadonlySet<number>;
  /** New net minus old net, in expected points; null where either is not stated. */
  difference: number | null;
  /** Names this change for the page session, so its difference counts once from zero. */
  key: string;
}

export type PlanModel = "current" | "football";

interface Shown {
  selection: string;
  model: PlanModel;
  players: string;
  eleven: number[];
  bench: number[];
  net: number | null;
  change: ModelChange | null;
}

// The plan shown last for each member's week, for the page's life: one entry per league,
// entry and gameweek, whatever the selection, so a change is read only against the plan the
// viewer saw just before.
const shown = new Map<string, Shown>();

export function planModel(view: EntryAdvice): PlanModel {
  return view.prediction_model?.id === "football" ? "football" : "current";
}

/** The member's week: the plans a viewer sees one after another on one page. */
function week(view: EntryAdvice): string {
  return [view.league_id, view.entry_id, view.gameweek].join(":");
}

/** The selection a plan answers, the model left out. */
function selection(view: EntryAdvice): string {
  return [
    view.mode,
    view.window,
    view.rival_entry_id ?? "-",
    view.top100?.weight ?? 0,
    view.evidence === undefined ? 0 : 1,
    view.chip ?? "-",
  ].join(":");
}

const ids = (players: EntryAdvice["starting_xi"]): number[] =>
  (players ?? []).map((player) => player.player_id);

/** The first week's net expected points, the figure the plan's own counter shows. */
function net(view: EntryAdvice): number | null {
  const points = view.expected_own_points;
  const hit = view.transfer_hit_points ?? 0;
  return typeof points === "number" && Number.isFinite(points) && Number.isFinite(hit)
    ? points - hit
    : null;
}

/** The players the new plan brings into the eleven, and onto the bench from outside. */
export function changedPlayers(
  before: { eleven: readonly number[]; bench: readonly number[] },
  after: { eleven: readonly number[]; bench: readonly number[] },
): Set<number> {
  const eleven = new Set(before.eleven);
  const fifteen = new Set([...before.eleven, ...before.bench]);
  return new Set([
    ...after.eleven.filter((id) => !eleven.has(id)),
    ...after.bench.filter((id) => !fifteen.has(id)),
  ]);
}

/**
 * The model change the shown plan answers, or null. Asking again for the same plan gives the
 * same answer, so the pitch, the bench and the decision can all ask in one render; the change
 * stays until the member's week shows another plan. The first change of a key primes its
 * difference's counter at zero and lets its plates move again, so the difference counts up
 * from nothing and the plates rise once for every switch, a repeat of an earlier pair too.
 */
export function modelChangeOf(view: EntryAdvice | null | undefined): ModelChange | null {
  if (!view) return null;
  const eleven = ids(view.starting_xi);
  const bench = ids(view.bench);
  if (eleven.length + bench.length === 0) return null;
  const slot = week(view);
  const current = selection(view);
  const model = planModel(view);
  const players = [...eleven, ...bench].sort((a, b) => a - b).join(",");
  const last = shown.get(slot);
  if (last && last.selection === current && last.model === model && last.players === players)
    return last.change;
  let change: ModelChange | null = null;
  if (last && last.selection === current && last.model !== model) {
    const now = net(view);
    const key = `model-diff:${slot}:${current}:${last.model}>${model}:${last.players}>${players}`;
    change = {
      from: last.model,
      to: model,
      changed: changedPlayers(last, { eleven, bench }),
      difference: now !== null && last.net !== null ? now - last.net : null,
      key,
    };
    // Primed at zero and released: the counter's next showing of this key counts up to the
    // difference, and the plates rise again, so a switch back and forth to the same pair
    // counts and moves each time.
    rememberCount(key, 0);
    popped.delete(key);
  }
  shown.set(slot, {
    selection: current,
    model,
    players,
    eleven,
    bench,
    net: net(view),
    change,
  });
  return change;
}

/** For tests: every member's week starts unseen. */
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
