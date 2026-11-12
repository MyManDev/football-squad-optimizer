/**
 * What a read moves on LIVE: only a strictly newer read of the same season, member and week;
 * the rows it changed, the first six by what changed most; slides for every row that changed
 * group; the duel for the same rival; and only transform and opacity, in the tokens' times.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { MOTION_MS } from "../../../design/motion";
import { liveBeats, type BeatName } from "../../../testSupport/liveBeats";
import { advanceRecap, liveBoard, type LiveBoard, type LiveRecap } from "./liveBoard";
import {
  APPEAR,
  ARROW_DOWN,
  ARROW_UP,
  CARD_TURN,
  EDGE_GROW,
  FLASH,
  FLOAT_DOWN,
  FLOAT_UP,
  GLYPH_DROP,
  MOVING_ROWS,
  ballOffset,
  claimMotion,
  fillScales,
  forgetLiveMotion,
  lookKey,
  lookOf,
  planMotion,
  playDuel,
  playRow,
  releaseMotion,
  type DuelLook,
  type LiveLook,
  type MotionPlan,
  type RowMotion,
} from "./liveMotion";

afterEach(() => {
  forgetLiveMotion();
  delete (Element.prototype as { animate?: unknown }).animate;
  document.body.innerHTML = "";
});

const beats = liveBeats();
const boardOf = (name: BeatName): LiveBoard =>
  liveBoard(beats.find((beat) => beat.name === name)!.input)!;

/** The looks and recaps of the beats from `from` to `to`, taken in in order. */
function told(names: BeatName[], duel: (board: LiveBoard) => DuelLook | null = () => null) {
  let recap: LiveRecap | null = null;
  return names.map((name) => {
    const board = boardOf(name);
    recap = advanceRecap(recap, board);
    return { board, recap, look: lookOf(board, duel(board)) };
  });
}

/** The plan of the read `to`, against the read `from` before it (with every beat in between). */
function plan(from: BeatName, to: BeatName): MotionPlan {
  const order = beats.map((beat) => beat.name);
  const names = order.slice(order.indexOf(from), order.indexOf(to) + 1);
  const steps = told(names);
  const before = steps.at(-2)!;
  const after = steps.at(-1)!;
  return planMotion(before.look, after.look, after.recap.fresh)!;
}

const motionOf = (made: MotionPlan, id: number): RowMotion | undefined => made.rows.get(id);

describe("when a read moves the page", () => {
  it("moves nothing without a look before, for another week or member, or for a read not newer", () => {
    const [kickoff, goal] = told(["kickoff", "goal"]);
    const fresh = goal!.recap.fresh;
    expect(planMotion(null, goal!.look, fresh)).toBeNull();
    expect(planMotion(goal!.look, goal!.look, fresh)).toBeNull();
    expect(planMotion(goal!.look, kickoff!.look, fresh)).toBeNull();
    const otherWeek: LiveLook = { ...kickoff!.look, key: "2026-27:101:11" };
    expect(planMotion(otherWeek, goal!.look, fresh)).toBeNull();
    expect(planMotion(kickoff!.look, goal!.look, fresh)).not.toBeNull();
  });

  it("keys each read's plan by season, member, week and source time", () => {
    const made = plan("kickoff", "goal");
    const board = boardOf("goal");
    expect(lookKey(board)).toBe("2026-27:101:10");
    expect(made.token).toBe(`2026-27:101:10:${board.sourceTime}`);
    expect(made.netFrom).toBe(boardOf("kickoff").net);
    expect(made.reopen).toBe(false);
    expect(made.playing).toBe(true);
  });
});

describe("what a read moves on a row", () => {
  it("slides the rows a kickoff moves to Oynuyor, with nothing to count from a dash", () => {
    const made = plan("before", "kickoff");
    for (const id of [1, 2, 3, 6, 7, 10]) {
      expect(motionOf(made, id)).toMatchObject({
        moved: true,
        pointsFrom: null,
        float: 0,
        events: null,
        rank: null,
      });
    }
    // The rows still to play stay where their group keeps them.
    expect(motionOf(made, 4)).toBeUndefined();
  });

  it("drops the captain's ball and the vice's A, counts their points and floats what they brought", () => {
    const made = plan("kickoff", "goal");
    expect(motionOf(made, 10)).toMatchObject({
      events: { goals: 1, assists: 0, card: false },
      pointsFrom: 2,
      float: 8,
      state: "up",
      moved: false,
    });
    expect(motionOf(made, 7)).toMatchObject({
      events: { goals: 0, assists: 1, card: false },
      pointsFrom: 1,
      float: 3,
      state: "up",
    });
    // The goal first: it changed most.
    expect(motionOf(made, 10)!.rank).toBe(0);
    expect(motionOf(made, 7)!.rank).toBe(1);
  });

  it("turns a card in, counts the point it took down and lets it fall", () => {
    const made = plan("goal", "card");
    expect(motionOf(made, 2)).toMatchObject({
      events: { goals: 0, assists: 0, card: true },
      pointsFrom: 1,
      float: -1,
      state: "down",
    });
  });

  it("counts an appearance's point without floating it, and floats an unconceded match's", () => {
    const made = plan("card", "over");
    // The keeper: 1 to 2 at ninety minutes, the appearance alone.
    expect(motionOf(made, 1)).toMatchObject({ pointsFrom: 1, float: 0, events: null });
    // A defender: 1 to 6, his appearance and his side's unconceded match.
    expect(motionOf(made, 3)).toMatchObject({ pointsFrom: 1, float: 5, state: "up" });
  });

  it("shows its own changes on six rows at most, the rest at once, and slides them all", () => {
    // The 15:00 match already under way in the look before: seven counted rows change at once.
    const [over, bonus] = told(["over", "bonus"]);
    const rows = { ...over!.look.rows };
    for (const id of ["4", "5", "8"]) rows[id] = { ...rows[id]!, started: true };
    const made = planMotion({ ...over!.look, rows }, bonus!.look, bonus!.recap.fresh)!;
    const ranked = [...made.rows.values()].filter((motion) => motion.rank !== null);
    expect(ranked).toHaveLength(MOVING_ROWS);
    expect(ranked.map((motion) => motion.rank).sort()).toEqual([0, 1, 2, 3, 4, 5]);
    const rest = [...made.rows.values()].filter((motion) => motion.rank === null);
    expect(rest.length).toBeGreaterThan(0);
    for (const motion of rest) {
      expect(motion).toMatchObject({ pointsFrom: null, float: 0, events: null, state: null });
    }
    // The second match's kickoff: every row that changed group slides.
    for (const id of [4, 5, 8, 11]) expect(motionOf(made, id)!.moved).toBe(true);
  });

  it("brings the reserve on and takes the starter off: chips, shirts and what the score takes", () => {
    const made = plan("second", "final");
    // He had not played before this read: his points appear, his chip and his shirt move.
    expect(motionOf(made, 13)).toMatchObject({
      chips: true,
      dim: { from: 0.55, to: 1 },
      float: 0,
      pointsFrom: null,
    });
    // The forward who never played was uncounted already: only his chip comes.
    expect(motionOf(made, 11)).toMatchObject({ chips: true, dim: null, float: 0 });
    // A reserve the score does not count moves nothing.
    expect(motionOf(made, 14)).toBeUndefined();
  });

  it("pops the armband the vice takes from a captain who did not play, and raises his row", () => {
    const [before] = told(["second"]);
    const look = before!.look;
    const rows = { ...look.rows };
    rows["10"] = { ...rows["10"]!, armband: "captain", multiplier: 0, take: 0, place: 0 };
    rows["7"] = { ...rows["7"]!, armband: "vice", place: 3 };
    const after: LiveLook = {
      ...look,
      time: look.time + 60_000,
      sourceTime: new Date(look.time + 60_000).toISOString(),
      rows: {
        ...rows,
        "10": { ...rows["10"]!, armband: null, place: 1 },
        "7": {
          ...rows["7"]!,
          armband: "captain",
          multiplier: 2,
          take: rows["7"]!.points * 2,
          shown: rows["7"]!.points * 2,
          place: 0,
        },
      },
    };
    const made = planMotion({ ...look, rows }, after, new Map())!;
    expect(motionOf(made, 7)).toMatchObject({
      armband: true,
      moved: true,
      float: rows["7"]!.points,
    });
  });
});

describe("what a read moves on the duel", () => {
  const duel =
    (margin: number, rivalId = 7): ((board: LiveBoard) => DuelLook) =>
    (board) => ({
      rivalId,
      rivalNet: board.net - margin,
      memberNet: board.net,
      margin,
    });

  it("rolls the duel for the same rival, and says when Önde, Berabere or Geride changed", () => {
    const [kickoff] = told(["kickoff"], duel(0));
    const [, goal] = told(["kickoff", "goal"], duel(3));
    const made = planMotion(kickoff!.look, goal!.look, goal!.recap.fresh)!;
    expect(made.duel).toEqual({
      rivalId: 7,
      rivalNetFrom: kickoff!.board.net,
      memberNetFrom: kickoff!.board.net,
      marginFrom: 0,
      statusChanged: true,
    });
  });

  it("moves no duel for another rival, or where the duel did not change", () => {
    const [kickoff] = told(["kickoff"], duel(0, 7));
    const [, goal] = told(["kickoff", "goal"], duel(3, 8));
    expect(planMotion(kickoff!.look, goal!.look, goal!.recap.fresh)!.duel).toBeNull();
    const same = { ...goal!.look, rival: kickoff!.look.rival };
    const shifted = { ...kickoff!.look, time: kickoff!.look.time - 1 };
    expect(planMotion(shifted, same, new Map())!.duel).toBeNull();
  });

  it("puts the ball on the leader's side and fills that side from the middle to it", () => {
    expect(ballOffset(0)).toBeCloseTo(0);
    expect(ballOffset(10)).toBeLessThan(0);
    expect(ballOffset(-10)).toBeGreaterThan(0);
    expect(Math.abs(ballOffset(500))).toBeLessThan(44);
    expect(fillScales(ballOffset(10))).toEqual({ member: -ballOffset(10) / 50, rival: 0 });
    expect(fillScales(ballOffset(-10))).toEqual({ member: 0, rival: ballOffset(-10) / 50 });
  });
});

describe("the motion itself", () => {
  const keys = (frames: Keyframe[]) =>
    new Set(frames.flatMap((frame) => Object.keys(frame).filter((key) => key !== "offset")));

  it("moves transform and opacity only", () => {
    for (const frames of [
      GLYPH_DROP,
      CARD_TURN,
      FLASH,
      FLOAT_UP,
      FLOAT_DOWN,
      ARROW_UP,
      ARROW_DOWN,
      EDGE_GROW,
      APPEAR,
    ]) {
      for (const key of keys(frames)) expect(["transform", "opacity"]).toContain(key);
    }
  });

  it("plays each part of a plan once, and again only where a remount stopped it", () => {
    expect(claimMotion("a:rows")).toBe(true);
    expect(claimMotion("a:rows")).toBe(false);
    releaseMotion("a:rows");
    expect(claimMotion("a:rows")).toBe(true);
  });

  /** Records every animate() call; each animation ends when the test says. */
  function recordAnimations() {
    const started: {
      element: Element;
      keyframes: Keyframe[];
      options: KeyframeAnimationOptions;
      end: () => void;
    }[] = [];
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      writable: true,
      value(this: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions) {
        let end: () => void = () => undefined;
        const finished = new Promise<void>((resolve) => {
          end = resolve;
        });
        started.push({ element: this, keyframes, options, end });
        return {
          finished,
          playState: "running",
          effect: { getComputedTiming: () => ({ progress: 0 }) },
          addEventListener() {},
          cancel() {},
        } as unknown as Animation;
      },
    });
    return started;
  }

  function rowElement() {
    document.body.innerHTML = `
      <ul><li data-live-row="10">
        <span data-live-edge></span>
        <span data-live-body><svg></svg>
          <svg data-live-glyph="goal"></svg><svg data-live-glyph="goal"></svg>
          <span data-live-armband>C</span><span data-autosub="in">Giren</span>
          <span data-live-points><span data-live-number data-value="10"></span><span data-live-arrow></span></span>
        </span>
      </li></ul>`;
    return document.querySelector<HTMLElement>("[data-live-row]")!;
  }

  const times = {
    uiFast: MOTION_MS.uiFast,
    ui: MOTION_MS.ui,
    data: MOTION_MS.data,
    step: MOTION_MS.uiFast / 3,
  };

  it("plays a row's changes in order: the glyph, the flash and the rise, the count, the state, the chips", () => {
    const started = recordAnimations();
    const row = rowElement();
    const motion: RowMotion = {
      rank: 1,
      pointsFrom: 2,
      events: { goals: 1, assists: 0, card: false },
      float: 8,
      state: "up",
      chips: true,
      dim: { from: 0.55, to: 1 },
      armband: true,
      moved: false,
    };
    playRow(row, motion, times, "tr-TR");
    const step = times.step;
    const on = (selector: string) =>
      started.find(({ element }) => element.matches(selector))?.options;
    // Only the newest ball drops.
    const balls = started.filter(({ element }) => element.matches("[data-live-glyph='goal']"));
    expect(balls).toHaveLength(1);
    expect(balls[0]!.element).toBe(row.querySelectorAll("[data-live-glyph='goal']")[1]);
    expect(balls[0]!.options).toMatchObject({ duration: times.data, delay: step });
    expect(
      on("[class*='flash'], span:not([data-live-edge]):not([data-autosub])[aria-hidden]"),
    ).toBeDefined();
    expect(on("[data-live-arrow]")).toMatchObject({ duration: times.ui, delay: times.data + step });
    expect(on("[data-live-edge]")).toMatchObject({
      duration: times.data,
      delay: times.data + step,
    });
    expect(on("[data-autosub]")).toMatchObject({ delay: times.data + times.ui + step });
    expect(on("[data-live-armband]")).toMatchObject({ delay: times.data + times.ui + step });
    expect(on("[data-live-body] > svg")).toMatchObject({ fill: "backwards" });
    // The flash and the rise are the row's while they play, and go when they end.
    const float = row.querySelector("[data-sign]");
    expect(float?.textContent).toBe("+8");
    for (const animation of started) {
      expect(animation.options.iterations ?? 1).not.toBe(Infinity);
      for (const key of keys(animation.keyframes)) expect(["transform", "opacity"]).toContain(key);
    }
  });

  it("removes the flash and the rise once they have played", async () => {
    const started = recordAnimations();
    const row = rowElement();
    playRow(
      row,
      {
        rank: 0,
        pointsFrom: null,
        events: { goals: 0, assists: 0, card: true },
        float: -1,
        state: null,
        chips: false,
        dim: null,
        armband: false,
        moved: false,
      },
      times,
      "tr-TR",
    );
    expect(row.querySelector("[data-sign='down']")?.textContent).toBe("−1");
    const before = row.querySelectorAll("[aria-hidden]").length;
    for (const animation of started) animation.end();
    await vi.waitFor(() => expect(row.querySelector("[data-sign]")).toBeNull());
    expect(row.querySelectorAll("[aria-hidden]").length).toBe(before - 2);
  });

  it("plays nothing on a row past the first six", () => {
    const started = recordAnimations();
    playRow(
      rowElement(),
      {
        rank: null,
        pointsFrom: null,
        events: null,
        float: 0,
        state: null,
        chips: false,
        dim: null,
        armband: false,
        moved: true,
      },
      times,
      "tr-TR",
    );
    expect(started).toHaveLength(0);
  });

  it("keeps each fill's end under the ball when the lead changes side", () => {
    const started = recordAnimations();
    document.body.innerHTML = `
      <div data-bar>
        <span data-live-fill="member"></span><span data-live-fill="rival"></span>
        <span data-live-lane><span data-live-ball></span></span>
      </div>`;
    const bar = document.querySelector<HTMLElement>("[data-bar]")!;
    playDuel(bar, -4, 3, times);
    const fill = (side: string) =>
      started.find(({ element }) => element.matches(`[data-live-fill='${side}']`))!;
    const from = ballOffset(-4);
    const to = ballOffset(3);
    const crossing = Math.abs(from) / (Math.abs(from) + Math.abs(to));
    expect(fill("rival").keyframes.map((frame) => frame.offset)).toEqual([0, crossing, 1]);
    expect(fill("rival").keyframes[1]!.transform).toBe("scaleX(0)");
    expect(fill("member").keyframes.at(-1)!.transform).toBe(`scaleX(${fillScales(to).member})`);
    const lane = started.find(({ element }) => element.matches("[data-live-lane]"))!;
    expect(lane.options).toMatchObject({
      duration: times.data * 2,
      delay: times.data,
      fill: "backwards",
    });
    // A member's lead puts the ball left: it rolls left, turning anticlockwise.
    const ball = started.find(({ element }) => element.matches("[data-live-ball]"))!;
    expect(ball.keyframes.at(-1)!.transform).toBe("rotate(0deg)");
  });
});

describe("LIVE's stylesheet", () => {
  const css = readFileSync(join(__dirname, "LivePage.module.css"), "utf-8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );

  it("moves nothing by itself but the light, three breaths, and that only where motion is wanted", () => {
    // Every motion is played by script; the stylesheet has no transition at all.
    expect(css).not.toMatch(/transition/);
    expect(css).not.toMatch(/infinite|animation-iteration-count/);
    const animations = [...css.matchAll(/animation\s*:[^;]*;/g)].map((match) => match[0]);
    expect(animations).toEqual([
      "animation: live-breath var(--motion-pulse) var(--motion-ease) 3;",
    ]);
    const wanted = css.indexOf("@media (prefers-reduced-motion: no-preference)");
    expect(wanted).toBeGreaterThan(-1);
    expect(css.indexOf("animation:")).toBeGreaterThan(wanted);
  });

  it("breathes with opacity alone", () => {
    const keyframes = [...css.matchAll(/@keyframes\s+([\w-]+)\s*{([\s\S]*?)\n}/g)];
    expect(keyframes.map((match) => match[1])).toEqual(["live-breath"]);
    const properties = [...keyframes[0]![2]!.matchAll(/([a-z-]+)\s*:/g)].map((match) => match[1]);
    expect(new Set(properties)).toEqual(new Set(["opacity"]));
  });
});
