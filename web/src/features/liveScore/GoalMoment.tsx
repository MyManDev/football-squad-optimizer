/**
 * The GOL moment (the owner's Plan 1 of 2026-11-11): when a read brings a goal by one of the
 * member's players, the fourth official's board rises in the middle of the screen with the
 * shout in LED letters, the scorer on the green panel and the points in LED digits; for the
 * captain the digits show the goal's points, then the armband, then what the member receives.
 * The board goes down after a few seconds, or at once on a tap or Escape, and the points run
 * into the live score. An assist rises the same board with its own shout; a card, and an
 * event of a pick who does not count, pass along a single LED line at the top.
 *
 * The layer never holds the page: only the board takes taps, focus stays where it is, and a
 * status line says each moment once. Nothing plays while the opening cover is up. Under the
 * reduced-motion preference nothing moves: one still line names the read's moments and goes
 * after a few seconds, or on its close button. Every duration is a `--motion-*` token's
 * (motion.ts) and every animation moves only transform and opacity.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { MOTION_EASE, MOTION_MS, prefersReducedMotion } from "../../design/motion";
import { ASSIST_SHOUT, GOAL_SHOUT, MOMENT_TIMING } from "./goalMomentTiming";
import { useCoverGone } from "./openingCover";
import { useLanguage } from "../../i18n/context";
import type { LiveMoment } from "./liveMoments";
import type { Position } from "./weekLive";
import styles from "./GoalMoment.module.css";

const COPY = {
  tr: {
    shout: { goal: GOAL_SHOUT, assist: ASSIST_SHOUT.tr },
    goal: "Gol",
    assist: "Asist",
    card: "Kart",
    bench: "Yedekte",
    close: "Kapat",
    positions: { GK: "Kaleci", DEF: "Defans", MID: "Orta saha", FWD: "Forvet" },
    points: (value: string) => `${value} puan`,
  },
  en: {
    shout: { goal: GOAL_SHOUT, assist: ASSIST_SHOUT.en },
    goal: "Goal",
    assist: "Assist",
    card: "Card",
    bench: "On Bench",
    close: "Close",
    positions: { GK: "Goalkeeper", DEF: "Defender", MID: "Midfielder", FWD: "Forward" },
    points: (value: string) => `${value} points`,
  },
} satisfies Record<
  "tr" | "en",
  {
    shout: { goal: string; assist: string };
    goal: string;
    assist: string;
    card: string;
    bench: string;
    close: string;
    positions: Record<Position, string>;
    points: (value: string) => string;
  }
>;

type Copy = (typeof COPY)["tr"];

const EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/** One moment on its way: its place among the read's big moments. */
interface Queued {
  moment: LiveMoment;
  order: string;
}

interface Batch {
  id: number;
  items: LiveMoment[];
}

const signed = (value: number, locale: string) =>
  `${value > 0 ? "+" : ""}${value.toLocaleString(locale)}`;

function animate(
  element: Element | null,
  frames: Keyframe[],
  duration: number,
  extra: KeyframeAnimationOptions = {},
): Animation | null {
  if (element === null || typeof (element as HTMLElement).animate !== "function") return null;
  return (element as HTMLElement).animate(frames, {
    duration,
    easing: EASE,
    fill: "both",
    ...extra,
  });
}

export function GoalMomentLayer({ batch }: { batch: Batch | null }) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  const coverGone = useCoverGone();
  const [state, setState] = useState<{
    batch: number | null;
    queue: Queued[];
    still: LiveMoment[] | null;
  }>({ batch: null, queue: [], still: null });
  // A new read's moments join the queue once; under reduced motion they become the still line.
  if (batch !== null && batch.id !== state.batch) {
    const bigs = batch.items.filter((moment) => moment.size === "big").length;
    let big = 0;
    const queued = batch.items.map((moment) => ({
      moment,
      order: moment.size === "big" && bigs > 1 ? `${++big}/${bigs}` : "",
    }));
    setState((current) =>
      prefersReducedMotion()
        ? { batch: batch.id, queue: [], still: batch.items }
        : { batch: batch.id, queue: [...current.queue, ...queued], still: null },
    );
  }
  const next = () => setState((current) => ({ ...current, queue: current.queue.slice(1) }));
  const playing = coverGone ? state.queue[0] : undefined;
  const spoken =
    playing !== undefined
      ? announcement(playing.moment, copy, locale)
      : state.still !== null && coverGone
        ? state.still.map((moment) => announcement(moment, copy, locale)).join(". ")
        : "";
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className={styles.layer} lang={language} data-goal-moments>
      <p className="visually-hidden" role="status" aria-live="polite">
        {spoken}
      </p>
      {playing === undefined ? null : playing.moment.size === "small" ? (
        <SmallLine
          key={playing.moment.key}
          moment={playing.moment}
          copy={copy}
          locale={locale}
          onDone={next}
        />
      ) : (
        <Board
          key={playing.moment.key}
          queued={playing}
          copy={copy}
          locale={locale}
          onDone={next}
        />
      )}
      {state.still !== null && coverGone ? (
        <StillLine
          key={state.batch ?? 0}
          moments={state.still}
          copy={copy}
          locale={locale}
          onDone={() => setState((current) => ({ ...current, still: null }))}
        />
      ) : null}
    </div>,
    document.body,
  );
}

function word(moment: LiveMoment, copy: Copy): string {
  return moment.kind === "goal" ? copy.goal : moment.kind === "assist" ? copy.assist : copy.card;
}

/** A big goal's or assist's shout; nothing for any other moment. */
function shouted(moment: LiveMoment, copy: Copy): string | null {
  if (moment.size !== "big" || moment.kind === "card") return null;
  return copy.shout[moment.kind];
}

function announcement(moment: LiveMoment, copy: Copy, locale: string): string {
  const parts = [`${word(moment, copy)}: ${moment.name}`];
  if (moment.multiplier === 0) parts.push(copy.bench);
  else if (moment.points !== null) parts.push(copy.points(signed(moment.points, locale)));
  return parts.join(", ");
}

function Board({
  queued,
  copy,
  locale,
  onDone,
}: {
  queued: Queued;
  copy: Copy;
  locale: string;
  onDone: () => void;
}) {
  const { moment, order } = queued;
  const big = moment.size === "big";
  const doubled = big && moment.multiplier > 1 && moment.base !== null && moment.points !== null;
  const [digits, setDigits] = useState(() =>
    moment.points === null ? null : signed(doubled ? moment.base! : moment.points, locale),
  );
  const board = useRef<HTMLButtonElement>(null);
  const shout = useRef<HTMLSpanElement>(null);
  const head = useRef<HTMLSpanElement>(null);
  const number = useRef<HTMLSpanElement>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  const leaving = useRef<(() => void) | null>(null);
  const text = shouted(moment, copy) ?? word(moment, copy);

  // The whole shout fits the board at one size before its letters light.
  useLayoutEffect(() => {
    const letters = shout.current;
    const room = head.current;
    if (letters === null || room === null) return;
    letters.style.fontSize = "";
    const free = room.clientWidth - (letters.nextElementSibling?.clientWidth ?? 0);
    if (free > 0 && letters.scrollWidth > free) {
      const size = parseFloat(getComputedStyle(letters).fontSize);
      letters.style.fontSize = `${Math.floor((size * free) / letters.scrollWidth)}px`;
    }
  }, [text]);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const later = (ms: number, step: () => void) => timers.push(setTimeout(step, ms));
    let gone = false;
    const leave = () => {
      if (gone) return;
      gone = true;
      timers.forEach(clearTimeout);
      const received = moment.points === null ? null : signed(moment.points, locale);
      if (received !== null) setDigits(received);
      run(number.current, moment.points === 0 ? null : received);
      const fall = animate(
        board.current,
        [
          { transform: "perspective(700px) rotateX(0deg)", opacity: 1 },
          { transform: "perspective(700px) rotateX(-90deg)", opacity: 0 },
        ],
        MOMENT_TIMING.fall,
      );
      if (fall === null) done.current();
      else
        fall.finished.then(
          () => done.current(),
          () => done.current(),
        );
    };
    leaving.current = leave;
    animate(
      board.current,
      [
        { transform: "perspective(700px) rotateX(-90deg)", opacity: 0 },
        { transform: "perspective(700px) rotateX(0deg)", opacity: 1 },
      ],
      MOMENT_TIMING.rise,
    );
    shout.current?.querySelectorAll("span").forEach((letter, index) => {
      animate(letter, [{ opacity: 0 }, { opacity: 1 }], MOTION_MS.uiFast, {
        delay: MOMENT_TIMING.rise * 0.75 + index * MOMENT_TIMING.letter,
        easing: "linear",
      });
    });
    let hold = moment.kind === "goal" ? MOMENT_TIMING.holdGoal : MOMENT_TIMING.holdAssist;
    if (doubled) {
      // The goal's points, then the armband, then what the member receives.
      later(MOMENT_TIMING.rise + MOTION_MS.data, () => setDigits(`×${moment.multiplier}`));
      later(MOMENT_TIMING.rise + MOTION_MS.data * 3, () =>
        setDigits(signed(moment.points!, locale)),
      );
      hold += MOTION_MS.data;
    }
    later(MOMENT_TIMING.rise + hold, leave);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leave();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      timers.forEach(clearTimeout);
      document.removeEventListener("keydown", onKey);
    };
  }, [big, doubled, locale, moment]);

  // Each change of the digits pops them once.
  useEffect(() => {
    animate(
      number.current,
      [
        { transform: "scale(1)" },
        { transform: "scale(1.14)", offset: 0.5 },
        { transform: "scale(1)" },
      ],
      MOTION_MS.data,
      { fill: "none" },
    );
  }, [digits]);

  return (
    <div className={styles.place} data-size={moment.size}>
      <button
        ref={board}
        type="button"
        className={styles.board}
        aria-label={copy.close}
        data-goal-board={moment.kind}
        onClick={() => leaving.current?.()}
      >
        <span ref={head} className={styles.head}>
          <span ref={shout} className={styles.shout} data-long={text.length > 4 || undefined}>
            {shouted(moment, copy) === null
              ? text
              : [...text].map((letter, index) => <span key={index}>{letter}</span>)}
          </span>
          {order || moment.count > 1 ? (
            <span className={styles.order}>
              {[moment.count > 1 ? `×${moment.count}` : "", order].filter(Boolean).join(" · ")}
            </span>
          ) : null}
        </span>
        <span className={styles.panel}>
          <span className={styles.name}>
            {moment.name}
            {moment.multiplier >= 2 ? <span className={styles.captain}>C</span> : null}
          </span>
          <span className={styles.meta}>
            {moment.team} · {copy.positions[moment.position]}
          </span>
        </span>
        {digits === null ? null : (
          <span ref={number} className={styles.digits} data-goal-points>
            {digits}
          </span>
        )}
      </button>
    </div>
  );
}

/** The points run from the board's digits into the live score, which then pops once. */
function run(from: HTMLElement | null, points: string | null) {
  const target = document.querySelector<HTMLElement>("[data-live-total]");
  if (from === null || target === null || points === null) return;
  const start = from.getBoundingClientRect();
  const end = target.getBoundingClientRect();
  if (end.bottom < 0 || end.top > window.innerHeight || typeof from.animate !== "function") return;
  const chip = document.createElement("span");
  chip.className = styles.runner!;
  chip.textContent = points;
  chip.setAttribute("aria-hidden", "true");
  chip.style.left = `${start.left}px`;
  chip.style.top = `${start.top}px`;
  document.body.append(chip);
  const dx = end.left + end.width / 2 - (start.left + start.width / 2);
  const dy = end.top + end.height / 2 - (start.top + start.height / 2);
  chip
    .animate(
      [
        { transform: "translate(0, 0) scale(1)", opacity: 1 },
        { transform: `translate(${dx}px, ${dy}px) scale(0.55)`, opacity: 0.85 },
      ],
      { duration: MOMENT_TIMING.run, easing: EASE, fill: "forwards" },
    )
    .finished.then(
      () => {
        chip.remove();
        animate(
          target,
          [
            { transform: "scale(1)" },
            { transform: "scale(1.12)", offset: 0.5 },
            { transform: "scale(1)" },
          ],
          MOTION_MS.data,
          { fill: "none" },
        );
      },
      () => chip.remove(),
    );
}

function lineText(moment: LiveMoment, copy: Copy, locale: string): string {
  const parts = [word(moment, copy), moment.name];
  if (moment.multiplier !== 0 && moment.points !== null) parts.push(signed(moment.points, locale));
  return parts.join(" · ");
}

function SmallLine({
  moment,
  copy,
  locale,
  onDone,
}: {
  moment: LiveMoment;
  copy: Copy;
  locale: string;
  onDone: () => void;
}) {
  const line = useRef<HTMLDivElement>(null);
  const leaving = useRef<(() => void) | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  useEffect(() => {
    animate(
      line.current,
      [
        { transform: "translateY(-8px)", opacity: 0 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      MOTION_MS.ui,
    );
    let gone = false;
    const leave = () => {
      if (gone) return;
      gone = true;
      clearTimeout(timer);
      const away = animate(line.current, [{ opacity: 1 }, { opacity: 0 }], MOTION_MS.ui);
      if (away === null) done.current();
      else
        away.finished.then(
          () => done.current(),
          () => done.current(),
        );
    };
    leaving.current = leave;
    const timer = setTimeout(leave, MOMENT_TIMING.line);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div
      ref={line}
      className={styles.line}
      data-goal-line={moment.kind}
      data-negative={moment.kind === "card" || undefined}
      onClick={() => leaving.current?.()}
    >
      {moment.multiplier === 0 ? <span className={styles.tag}>{copy.bench}</span> : null}
      <span aria-hidden="true">{lineText(moment, copy, locale)}</span>
    </div>
  );
}

function StillLine({
  moments,
  copy,
  locale,
  onDone,
}: {
  moments: LiveMoment[];
  copy: Copy;
  locale: string;
  onDone: () => void;
}) {
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  useEffect(() => {
    const timer = setTimeout(() => done.current(), MOMENT_TIMING.still);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div className={styles.still} data-goal-still>
      <p className={styles.stillText}>
        {moments.map((moment) => (
          <span key={moment.key} data-negative={moment.kind === "card" || undefined}>
            {shouted(moment, copy) ?? word(moment, copy)} · {moment.name}
            {moment.multiplier === 0
              ? ` · ${copy.bench}`
              : moment.points === null
                ? ""
                : ` · ${signed(moment.points, locale)}`}
          </span>
        ))}
      </p>
      <button
        type="button"
        className={styles.close}
        aria-label={copy.close}
        onClick={() => done.current()}
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}
