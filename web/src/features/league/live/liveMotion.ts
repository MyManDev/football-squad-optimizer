/**
 * How LIVE moves when a read brings a change (the synthesis of 2026-11-11, section 3.4, and the
 * proposal the owner read: the points count to their new value, a goal's ball drops in and its
 * row flashes once while the points it brought rise beside it, a card turns in, the arrow and
 * the edge take a changed state, a row slides to its new group when its match starts or ends,
 * the ball of the duel rolls to the side of the one ahead, and the heading's light breathes
 * three times, then stands still).
 *
 * A plan is made only where the board the page draws is strictly newer than the one it last
 * drew, or the one the visitor last saw, for the same season, member and week (`planMotion`):
 * never for a first read with nothing seen before, a reread, an older or same-time copy, a
 * language, theme or width change, or another rival. The plan is data; the page's parts play
 * it once (`claimMotion`), only while the page is in view and clear, never under the
 * reduced-motion preference, and only with transform and opacity, in the motion tokens' times.
 *
 * Order on one read, from the render that draws it: the rows that change group or rise with
 * the armband slide at once; the rows' own changes, at most six rows, each a third of uiFast
 * after the one before: the glyphs, the flash and the points' rise first, the count a uiFast
 * later, the arrow and the edge after the data time, the substitution chips, the shirt and the
 * armband after data and ui; the duel's figures count after uiFast, its ball rolls after the data
 * time. Everything has ended within about 1.3 seconds; the light's three breaths take 4.2.
 */

import { countTo, type Count } from "../../../design/countMotion";
import { MOTION_EASE, motionDuration } from "../../../design/motion";
import { MODEL_POP } from "../advice/modelSwitch";
import { BOARD_EASE, INCOMING } from "../pages/boardMotion";
import {
  appearancePoints,
  rowPoints,
  rowTake,
  type LiveBoard,
  type LiveEvents,
  type LiveGroup,
  type LiveState,
} from "./liveBoard";
import { duelStatus } from "./liveDuel";
import { signedWhole, wholePoints } from "./liveFormat";
import styles from "./LivePage.module.css";

/** At most this many rows show their own changes on one read. */
export const MOVING_ROWS = 6;

/** A row as the visitor saw it. */
export interface RowLook {
  pick: number;
  /** FPL's points, before the armband. */
  points: number;
  /** The points the row shows: its points times its armband's. */
  shown: number;
  /** What the member's score takes of him. */
  take: number;
  /** What the score takes of his points: none, once, or the armband's two or three. */
  multiplier: number;
  minutes: number;
  started: boolean;
  /** The state the row draws; a pick the score does not count draws none. */
  state: LiveState | null;
  group: LiveGroup;
  /** His place in his group. */
  place: number;
  counted: boolean;
  autosub: "in" | "out" | null;
  armband: "captain" | "vice" | null;
}

/** The duel as it was drawn. */
export interface DuelLook {
  rivalId: number;
  rivalNet: number;
  memberNet: number;
  margin: number;
}

/** What LIVE drew of a member's week, read by read. */
export interface LiveLook {
  /** `season:entry:week`. */
  key: string;
  sourceTime: string;
  time: number;
  net: number;
  /** One of the member's own rows is in a match being played. */
  playing: boolean;
  /** By element id. */
  rows: Readonly<Record<string, RowLook>>;
  rival: DuelLook | null;
}

/** The look's key for a board: the season, the member and the week. */
export function lookKey(board: Pick<LiveBoard, "season" | "entryId" | "gameweek">): string {
  return `${board.season}:${board.entryId}:${board.gameweek}`;
}

/** The look of a drawn board, beside the duel drawn with it. */
export function lookOf(board: LiveBoard, rival: DuelLook | null): LiveLook {
  const rows: Record<string, RowLook> = {};
  for (const group of Object.keys(board.groups) as LiveGroup[]) {
    board.groups[group].forEach((row, place) => {
      rows[row.elementId] = {
        pick: row.pick,
        points: row.points,
        shown: rowPoints(row),
        take: rowTake(row),
        multiplier: row.multiplier,
        minutes: row.minutes,
        started: row.started,
        state: row.counted ? row.state : null,
        group,
        place,
        counted: row.counted,
        autosub: row.autosub,
        armband: row.armband,
      };
    });
  }
  return {
    key: lookKey(board),
    sourceTime: board.sourceTime,
    time: Date.parse(board.sourceTime),
    net: board.net,
    playing: board.rows.some((row) => row.phase === "playing"),
    rows,
    rival,
  };
}

/** Whether two duel looks draw the same duel. */
export function sameDuel(a: DuelLook | null, b: DuelLook | null): boolean {
  if (a === null || b === null) return a === b;
  return (
    a.rivalId === b.rivalId &&
    a.rivalNet === b.rivalNet &&
    a.memberNet === b.memberNet &&
    a.margin === b.margin
  );
}

/** What one row does on a read. */
export interface RowMotion {
  /** Its place among the rows that show their own changes, or null past the first six. */
  rank: number | null;
  /** The points it counts from, or null where they are written at once. */
  pointsFrom: number | null;
  /** The goals, assists and card the read brought him. */
  events: LiveEvents | null;
  /** The change in what the score takes of him, risen or fallen beside his points; 0 for none. */
  float: number;
  /** The state he took, when it is up or down and was not before. */
  state: "up" | "down" | null;
  /** A substitution chip came on his row. */
  chips: boolean;
  /** His shirt's opacity, from and to, where the score started or stopped counting him. */
  dim: { from: number; to: number } | null;
  /** The armband came to him. */
  armband: boolean;
  /** He changed group, or rose to the head of his own with the armband. */
  moved: boolean;
}

/** What the duel does on a read. */
export interface DuelMotion {
  rivalId: number;
  rivalNetFrom: number;
  memberNetFrom: number;
  marginFrom: number;
  /** Önde, Berabere or Geride changed. */
  statusChanged: boolean;
}

export interface MotionPlan {
  /** One per member, week and read: `season:entry:week:sourceTime`. */
  token: string;
  /** Made from the look the visitor last saw, on opening the page again. */
  reopen: boolean;
  /** Canlı puan before the read. */
  netFrom: number;
  rows: ReadonlyMap<number, RowMotion>;
  duel: DuelMotion | null;
  /** One of the member's own rows is in a match being played. */
  playing: boolean;
}

const UNCOUNTED_SHIRT = 0.55;

/**
 * What a read moves, from the look before it; null where nothing may move: no look before, a
 * look of another season, member or week, or a read that is not strictly newer.
 */
export function planMotion(
  previous: LiveLook | null,
  next: LiveLook,
  fresh: ReadonlyMap<number, LiveEvents>,
  reopen = false,
): MotionPlan | null {
  if (previous === null || previous.key !== next.key || !(next.time > previous.time)) return null;
  const rows = new Map<number, RowMotion>();
  const ranked: { id: number; weight: number[] }[] = [];
  for (const [key, after] of Object.entries(next.rows)) {
    const id = Number(key);
    const before = previous.rows[key];
    if (before === undefined) continue;
    const chips = after.autosub !== null && after.autosub !== before.autosub;
    // A pick the score counts neither before nor now moves nothing, but for his chip when the
    // scorer takes him off.
    if (!after.counted && !before.counted && !chips) continue;
    const events = after.counted ? (fresh.get(id) ?? null) : null;
    const both = before.started && after.started;
    const pointsFrom = both && before.shown !== after.shown ? before.shown : null;
    // Only what the score takes floats, never the minute that brings an appearance's point.
    const appearanceOnly =
      events === null &&
      after.multiplier === before.multiplier &&
      after.points - before.points ===
        appearancePoints(after.minutes) - appearancePoints(before.minutes);
    const float = both && !appearanceOnly ? after.take - before.take : 0;
    const state =
      after.state !== before.state && (after.state === "up" || after.state === "down")
        ? after.state
        : null;
    const dim =
      after.counted === before.counted
        ? null
        : {
            from: before.counted ? 1 : UNCOUNTED_SHIRT,
            to: after.counted ? 1 : UNCOUNTED_SHIRT,
          };
    const armband = after.armband === "captain" && before.armband !== "captain";
    const moved =
      after.group !== before.group || (armband && after.place < before.place && after.place === 0);
    const decorated =
      events !== null ||
      pointsFrom !== null ||
      float !== 0 ||
      state !== null ||
      chips ||
      dim !== null ||
      armband;
    if (!decorated && !moved) continue;
    rows.set(id, {
      rank: null,
      pointsFrom,
      events,
      float,
      state,
      chips,
      dim,
      armband,
      moved,
    });
    if (decorated) {
      ranked.push({
        id,
        weight: [
          events === null ? 0 : 1,
          Math.abs(float),
          state === null ? 0 : 1,
          chips || dim !== null || armband ? 1 : 0,
          -after.pick,
        ],
      });
    }
  }
  ranked.sort((a, b) => {
    for (let index = 0; index < a.weight.length; index += 1) {
      const difference = b.weight[index]! - a.weight[index]!;
      if (difference !== 0) return difference;
    }
    return 0;
  });
  ranked.forEach(({ id }, rank) => {
    const motion = rows.get(id)!;
    rows.set(
      id,
      rank < MOVING_ROWS
        ? { ...motion, rank }
        : // Past the first six, a row shows its end state at once; a slide is not capped.
          {
            ...motion,
            pointsFrom: null,
            events: null,
            float: 0,
            state: null,
            chips: false,
            dim: null,
            armband: false,
          },
    );
  });
  const was = previous.rival;
  const now = next.rival;
  const duel =
    was !== null && now !== null && was.rivalId === now.rivalId && !sameDuel(was, now)
      ? {
          rivalId: now.rivalId,
          rivalNetFrom: was.rivalNet,
          memberNetFrom: was.memberNet,
          marginFrom: was.margin,
          statusChanged: duelStatus(was.margin) !== duelStatus(now.margin),
        }
      : null;
  return {
    token: `${next.key}:${next.sourceTime}`,
    reopen,
    netFrom: previous.net,
    rows,
    duel,
    playing: next.playing,
  };
}

// ---- Plays: once each ----

const claimed = new Set<string>();

/** Takes a part of a plan to play; false where it has been taken already. */
export function claimMotion(key: string): boolean {
  if (claimed.has(key)) return false;
  claimed.add(key);
  return true;
}

/** Lets a part play again, for a play a remount stopped before it ended. */
export function releaseMotion(key: string): void {
  claimed.delete(key);
}

const counting = new WeakMap<Element, Count>();

/** Counts `element` from one value to another after `delay`, stopping any count already on it. */
export function countLive(
  element: HTMLElement,
  from: number,
  to: number,
  format: (value: number) => string,
  delay = 0,
): void {
  settleCount(element);
  const count = countTo(element, from, to, format, undefined, delay);
  if (count !== null) counting.set(element, count);
}

/** Stops a count on `element` where it is, so its owner can write the value it holds. */
export function settleCount(element: HTMLElement): void {
  const count = counting.get(element);
  if (count === undefined) return;
  counting.delete(element);
  if (count.running) count.stop();
}

/** For tests: every part of every plan may play again. */
export function forgetLiveMotion(): void {
  claimed.clear();
}

/** Whether the page may show motion: it is in view, clear, and the opening cover has gone. */
export type MotionGate = "wait" | "open" | "closed";

/** The times of one read's motion, or null under reduced motion or without the API. */
export interface MotionTimes {
  uiFast: number;
  ui: number;
  data: number;
  /** Between one moving row and the next. */
  step: number;
}

export function motionTimes(element: Element | null): MotionTimes | null {
  const data = motionDuration("data");
  if (data === 0 || element === null || typeof element.animate !== "function") return null;
  const uiFast = motionDuration("uiFast");
  return { uiFast, ui: motionDuration("ui"), data, step: uiFast / 3 };
}

export const LIVE_EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/** A goal's ball or an assist's A drops in, a little past its place, then settles. */
export const GLYPH_DROP: Keyframe[] = [
  { transform: "translateY(-8px)", opacity: 0 },
  { transform: "translateY(2px)", opacity: 1, offset: 0.7 },
  { transform: "translateY(0px)", opacity: 1 },
];

/** A card turns in about its upright. */
export const CARD_TURN: Keyframe[] = [
  { transform: "perspective(200px) rotateY(90deg)" },
  { transform: "perspective(200px) rotateY(0deg)" },
];

/** The row's flash, once. */
export const FLASH: Keyframe[] = [{ opacity: 0.35 }, { opacity: 0 }];

/** The points a read brought rise from the row's points; what it took falls. */
export const FLOAT_UP: Keyframe[] = [
  { transform: "translateY(0px)", opacity: 1 },
  { transform: "translateY(-14px)", opacity: 0 },
];
export const FLOAT_DOWN: Keyframe[] = [
  { transform: "translateY(0px)", opacity: 1 },
  { transform: "translateY(12px)", opacity: 0 },
];

/** The arrow of a state that went up comes up into place; one that went down comes down. */
export const ARROW_UP: Keyframe[] = [
  { transform: "translateY(8px)", opacity: 0 },
  { transform: "translateY(0px)", opacity: 1 },
];
export const ARROW_DOWN: Keyframe[] = [
  { transform: "translateY(-8px)", opacity: 0 },
  { transform: "translateY(0px)", opacity: 1 },
];

/** The edge's colour grows along it: from the bottom when up, from the top when down (CSS). */
export const EDGE_GROW: Keyframe[] = [{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }];

/** Something new comes into view in place. */
export const APPEAR: Keyframe[] = [{ opacity: 0 }, { opacity: 1 }];

const settle = (animation: Animation, then: () => void) => {
  animation.finished.then(then, then);
};

/** Plays one row's own changes; returns what it started. */
export function playRow(
  row: HTMLElement,
  motion: RowMotion,
  times: MotionTimes,
  locale: string,
): Animation[] {
  if (motion.rank === null) return [];
  const { uiFast, ui, data } = times;
  const start = motion.rank * times.step;
  const started: Animation[] = [];
  const play = (
    element: Element | null,
    keyframes: Keyframe[],
    duration: number,
    delay: number,
    easing = LIVE_EASE,
  ) => {
    if (element === null) return null;
    const animation = element.animate(keyframes, {
      duration,
      delay,
      easing,
      fill: delay > 0 ? "backwards" : "none",
    });
    started.push(animation);
    return animation;
  };
  const events = motion.events;
  if (events !== null) {
    const drop = (kind: "goal" | "assist", count: number) => {
      if (count === 0) return;
      const more = row.querySelector(`[data-live-glyph='${kind}-more']`);
      const glyphs = [...row.querySelectorAll(`[data-live-glyph='${kind}']`)];
      for (const glyph of more === null ? glyphs.slice(-count) : [more]) {
        play(glyph, GLYPH_DROP, data, start);
      }
    };
    drop("goal", events.goals);
    drop("assist", events.assists);
    if (events.card) play(row.querySelector("[data-live-glyph='card']"), CARD_TURN, data, start);
    // The row flashes once for an event, behind its content.
    const flash = document.createElement("span");
    flash.className = styles.flash ?? "";
    flash.setAttribute("aria-hidden", "true");
    row.prepend(flash);
    const lit = play(flash, FLASH, data * 2, start);
    if (lit === null) flash.remove();
    else settle(lit, () => flash.remove());
  }
  const points = row.querySelector<HTMLElement>("[data-live-points]");
  if (motion.float !== 0 && points !== null) {
    const float = document.createElement("span");
    float.className = styles.float ?? "";
    float.dataset.sign = motion.float > 0 ? "up" : "down";
    float.setAttribute("aria-hidden", "true");
    float.textContent = signedWhole(motion.float, locale);
    points.append(float);
    const risen = play(float, motion.float > 0 ? FLOAT_UP : FLOAT_DOWN, data * 2, start);
    if (risen === null) float.remove();
    else settle(risen, () => float.remove());
  }
  const figure = row.querySelector<HTMLElement>("[data-live-number]");
  if (motion.pointsFrom !== null && figure !== null) {
    const to = Number(figure.dataset.value);
    countLive(
      figure,
      motion.pointsFrom,
      to,
      (value) => wholePoints(Math.round(value), locale),
      uiFast + start,
    );
    const count = figure.getAnimations?.().at(-1);
    if (count !== undefined) started.push(count);
  }
  if (motion.state !== null) {
    play(
      row.querySelector("[data-live-arrow]"),
      motion.state === "up" ? ARROW_UP : ARROW_DOWN,
      ui,
      data + start,
    );
    play(row.querySelector("[data-live-edge]"), EDGE_GROW, data, data + start);
  }
  const late = data + ui + start;
  if (motion.chips) play(row.querySelector("[data-autosub]"), INCOMING, data, late, BOARD_EASE);
  if (motion.dim !== null) {
    play(
      row.querySelector("[data-live-body] > svg"),
      [{ opacity: motion.dim.from }, { opacity: motion.dim.to }],
      data,
      late,
    );
  }
  if (motion.armband) play(row.querySelector("[data-live-armband]"), MODEL_POP, data, late);
  return started;
}

/** Where the duel's ball rests: its offset from the middle, in hundredths of the bar's width. */
export function ballOffset(margin: number): number {
  return (-44 * margin) / (Math.abs(margin) + 20);
}

/** The lane's transform for a ball offset. */
export function laneTransform(offset: number): string {
  return `translateX(${offset}%)`;
}

/** Each side's fill for a ball offset: the side ahead fills from the middle to the ball. */
export function fillScales(offset: number): { member: number; rival: number } {
  return { member: Math.max(-offset, 0) / 50, rival: Math.max(offset, 0) / 50 };
}

/** The ball's radius as drawn, in pixels: a 24 px ball. */
const BALL_RADIUS = 12;

/**
 * The duel's roll, from the margin before the read to the one now: the ball rolls to the
 * leader's side, turning as far as it travels, and each side's fill keeps its end under the
 * ball (a fill that empties is empty by the time the ball crosses the middle).
 */
export function playDuel(
  bar: HTMLElement,
  marginFrom: number,
  marginTo: number,
  times: MotionTimes,
): Animation[] {
  const from = ballOffset(marginFrom);
  const to = ballOffset(marginTo);
  if (from === to) return [];
  const { data } = times;
  const timing = { duration: data * 2, delay: data, easing: LIVE_EASE, fill: "backwards" as const };
  const started: Animation[] = [];
  const lane = bar.querySelector("[data-live-lane]");
  const ball = bar.querySelector("[data-live-ball]");
  if (lane !== null) {
    started.push(
      lane.animate([{ transform: laneTransform(from) }, { transform: laneTransform(to) }], timing),
    );
  }
  if (ball !== null) {
    const travelled = ((to - from) / 100) * bar.getBoundingClientRect().width;
    const turn = (travelled / BALL_RADIUS) * (180 / Math.PI);
    started.push(
      ball.animate([{ transform: `rotate(${-turn}deg)` }, { transform: "rotate(0deg)" }], timing),
    );
  }
  const before = fillScales(from);
  const after = fillScales(to);
  // Where the ball crosses the middle, as a share of its way, when it changes side.
  const crossing =
    Math.sign(from) !== 0 && Math.sign(to) !== 0 && Math.sign(from) !== Math.sign(to)
      ? Math.abs(from) / (Math.abs(from) + Math.abs(to))
      : null;
  for (const side of ["member", "rival"] as const) {
    const fill = bar.querySelector(`[data-live-fill='${side}']`);
    if (fill === null || before[side] === after[side]) continue;
    const keyframes: Keyframe[] =
      crossing === null
        ? [{ transform: `scaleX(${before[side]})` }, { transform: `scaleX(${after[side]})` }]
        : [
            { transform: `scaleX(${before[side]})`, offset: 0 },
            { transform: "scaleX(0)", offset: crossing },
            { transform: `scaleX(${after[side]})`, offset: 1 },
          ];
    started.push(fill.animate(keyframes, timing));
  }
  return started;
}
