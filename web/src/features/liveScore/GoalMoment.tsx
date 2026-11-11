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
import { usePageClear } from "./openingCover";
import { useLanguage } from "../../i18n/context";
import { shownOnBoard, type BoardMoment, type SubstitutionMoment } from "./boardMoments";
import type { LiveMoment } from "./liveMoments";
import type { Position } from "./weekLive";
import styles from "./GoalMoment.module.css";

const COPY = {
  tr: {
    shout: { goal: GOAL_SHOUT.tr, assist: ASSIST_SHOUT.tr },
    goal: "Gol",
    assist: "Asist",
    card: "Kart",
    substitution: "Değişiklik",
    out: "Çıkan",
    in: "Giren",
    bench: "Yedekte",
    close: "Kapat",
    positions: { GK: "Kaleci", DEF: "Defans", MID: "Orta saha", FWD: "Forvet" },
    points: (value: string) => `${value} puan`,
  },
  en: {
    shout: { goal: GOAL_SHOUT.en, assist: ASSIST_SHOUT.en },
    goal: "Goal",
    assist: "Assist",
    card: "Card",
    substitution: "Substitution",
    out: "Out",
    in: "In",
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
    substitution: string;
    out: string;
    in: string;
    bench: string;
    close: string;
    positions: Record<Position, string>;
    points: (value: string) => string;
  }
>;

type Copy = (typeof COPY)["tr"];

const EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/** The flex gap beside the order (var(--space-2)), and the smallest LED letters. */
const FIT_GAP = 8;
const LED_MIN = 30;

/** One moment on its way: its place among the read's big moments. */
interface Queued {
  moment: BoardMoment;
  order: string;
}

interface Batch {
  /** One stream per source (`live:`, `replay:`), so the two never stand for each other. */
  id: string;
  items: BoardMoment[];
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

export function GoalMomentLayer({
  batch,
  onLanded,
}: {
  batch: Batch | null;
  /** Told when a moment's points have reached the live score (or will not run there). */
  onLanded?: (key: string) => void;
}) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  const layer = useRef<HTMLDivElement>(null);
  // Nothing plays under the opening cover, a modal dialog or a cover over the page.
  const clear = usePageClear(layer);
  const landed = useRef(onLanded);
  useEffect(() => {
    landed.current = onLanded;
  });
  const [state, setState] = useState<{
    batch: string | null;
    queue: Queued[];
    still: BoardMoment[] | null;
  }>({ batch: null, queue: [], still: null });
  // A new read's moments join the queue once; under reduced motion they become the still line.
  if (batch !== null && batch.id !== state.batch) {
    // Only what brings the member points: a reserve the scorer does not count raises nothing.
    const items = batch.items.filter(shownOnBoard);
    const bigs = items.filter((moment) => moment.size === "big").length;
    let big = 0;
    const queued = items.map((moment) => ({
      moment,
      order: moment.size === "big" && bigs > 1 ? `${++big}/${bigs}` : "",
    }));
    setState((current) =>
      prefersReducedMotion()
        ? { batch: batch.id, queue: [], still: items.length > 0 ? items : null }
        : { batch: batch.id, queue: [...current.queue, ...queued], still: null },
    );
  }
  const next = () => setState((current) => ({ ...current, queue: current.queue.slice(1) }));
  const playing = clear ? state.queue[0] : undefined;
  const spoken =
    playing !== undefined
      ? announcement(playing.moment, copy, locale)
      : state.still !== null && clear
        ? state.still.map((moment) => announcement(moment, copy, locale)).join(". ")
        : "";
  if (typeof document === "undefined") return null;
  return createPortal(
    <div ref={layer} className={styles.layer} lang={language} data-goal-moments>
      <p className="visually-hidden" role="status" aria-live="polite">
        {spoken}
      </p>
      {playing === undefined ? null : playing.moment.kind === "substitution" ? (
        <SubstitutionBoard
          key={playing.moment.key}
          moment={playing.moment}
          copy={copy}
          onDone={next}
        />
      ) : playing.moment.size === "small" ? (
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
          queued={{ moment: playing.moment, order: playing.order }}
          copy={copy}
          locale={locale}
          onLanded={(key) => landed.current?.(key)}
          onDone={next}
        />
      )}
      {state.still !== null && clear ? (
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
  const name =
    moment.kind === "goal" ? copy.goal : moment.kind === "assist" ? copy.assist : copy.card;
  // Two goals of one player in one read are one moment: "Gol ×2".
  return moment.count > 1 ? `${name} ×${moment.count}` : name;
}

/** A big goal's or assist's shout; nothing for any other moment. */
function shouted(moment: LiveMoment, copy: Copy): string | null {
  if (moment.size !== "big" || moment.kind === "card") return null;
  return copy.shout[moment.kind];
}

function announcement(moment: BoardMoment, copy: Copy, locale: string): string {
  if (moment.kind === "substitution") {
    return `${copy.substitution}: ${copy.out} ${moment.out}, ${copy.in} ${moment.in}`;
  }
  const parts = [`${word(moment, copy)}: ${moment.name}`];
  if (moment.multiplier === 0) parts.push(copy.bench);
  else if (moment.points !== null) parts.push(copy.points(signed(moment.points, locale)));
  return parts.join(", ");
}

function Board({
  queued,
  copy,
  locale,
  onLanded,
  onDone,
}: {
  queued: { moment: LiveMoment; order: string };
  copy: Copy;
  locale: string;
  onLanded?: (key: string) => void;
  onDone: () => void;
}) {
  const onLandedRef = useRef(onLanded);
  useEffect(() => {
    onLandedRef.current = onLanded;
  });
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
    const beside = letters.nextElementSibling as HTMLElement | null;
    const free = room.clientWidth - (beside === null ? 0 : beside.offsetWidth + FIT_GAP);
    if (free > 0 && letters.scrollWidth > free) {
      const size = parseFloat(getComputedStyle(letters).fontSize);
      letters.style.fontSize = `${Math.max(LED_MIN, Math.floor((size * free) / letters.scrollWidth))}px`;
    }
  }, [text]);

  useLayoutEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const later = (ms: number, step: () => void) => timers.push(setTimeout(step, ms));
    let gone = false;
    const leave = () => {
      if (gone) return;
      gone = true;
      timers.forEach(clearTimeout);
      const received = moment.points === null ? null : signed(moment.points, locale);
      if (received !== null) setDigits(received);
      const release = () => onLandedRef.current?.(moment.key);
      if (!run(number.current, moment.points === 0 ? null : received, release)) release();
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
        tabIndex={-1}
        onMouseDown={(event) => event.preventDefault()}
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

/**
 * The fourth official's board as it is meant: DEĞİŞİKLİK in LED letters, the starter going off on
 * the red panel and the reserve coming on on the green one. It rises, stays a step less than a
 * goal's board and goes down by itself, or at once on a tap or Escape.
 */
function SubstitutionBoard({
  moment,
  copy,
  onDone,
}: {
  moment: SubstitutionMoment;
  copy: Copy;
  onDone: () => void;
}) {
  const board = useRef<HTMLButtonElement>(null);
  const word = useRef<HTMLSpanElement>(null);
  const head = useRef<HTMLSpanElement>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  const leaving = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    const letters = word.current;
    const room = head.current;
    if (letters === null || room === null) return;
    letters.style.fontSize = "";
    if (room.clientWidth > 0 && letters.scrollWidth > room.clientWidth) {
      const size = parseFloat(getComputedStyle(letters).fontSize);
      letters.style.fontSize = `${Math.max(LED_MIN, Math.floor((size * room.clientWidth) / letters.scrollWidth))}px`;
    }
  }, []);
  useLayoutEffect(() => {
    let gone = false;
    const leave = () => {
      if (gone) return;
      gone = true;
      clearTimeout(timer);
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
    const timer = setTimeout(leave, MOMENT_TIMING.rise + MOMENT_TIMING.holdAssist);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leave();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return (
    <div className={styles.place} data-size="big">
      <button
        ref={board}
        type="button"
        className={`${styles.board} ${styles.swap}`}
        tabIndex={-1}
        onMouseDown={(event) => event.preventDefault()}
        aria-label={copy.close}
        data-goal-board="substitution"
        onClick={() => leaving.current?.()}
      >
        <span ref={head} className={styles.head}>
          <span ref={word} className={styles.shout} data-long="">
            {copy.substitution}
          </span>
        </span>
        <span className={`${styles.panel} ${styles.off}`}>
          <span className={styles.side}>{copy.out}</span>
          <span className={styles.name}>{moment.out}</span>
        </span>
        <span className={styles.panel}>
          <span className={styles.side}>{copy.in}</span>
          <span className={styles.name}>{moment.in}</span>
        </span>
      </button>
    </div>
  );
}

/** The points run from the board's digits into the live score, which then pops once. */
function run(from: HTMLElement | null, points: string | null, onLanded: () => void): boolean {
  const target = document.querySelector<HTMLElement>("[data-live-total]");
  if (from === null || target === null || points === null) return false;
  const start = from.getBoundingClientRect();
  const end = target.getBoundingClientRect();
  if (end.bottom < 0 || end.top > window.innerHeight || typeof from.animate !== "function") {
    return false;
  }
  const chip = document.createElement("span");
  chip.className = styles.runner!;
  chip.textContent = points;
  chip.setAttribute("aria-hidden", "true");
  document.body.append(chip);
  // The chip starts centred on the digits and ends centred on the score.
  const size = chip.getBoundingClientRect();
  const fromX = start.left + start.width / 2;
  const fromY = start.top + start.height / 2;
  chip.style.left = `${fromX - size.width / 2}px`;
  chip.style.top = `${fromY - size.height / 2}px`;
  const dx = end.left + end.width / 2 - fromX;
  const dy = end.top + end.height / 2 - fromY;
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
        onLanded();
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
      () => {
        chip.remove();
        onLanded();
      },
    );
  return true;
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
  useLayoutEffect(() => {
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
      aria-hidden="true"
      onClick={() => leaving.current?.()}
    >
      <span>{lineText(moment, copy, locale)}</span>
    </div>
  );
}

function StillLine({
  moments,
  copy,
  locale,
  onDone,
}: {
  moments: BoardMoment[];
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
    <div className={styles.still} data-goal-still onClick={() => done.current()}>
      <p className={styles.stillText}>
        {moments.map((moment) => (
          <span key={moment.key} data-negative={moment.kind === "card" || undefined}>
            {moment.kind === "substitution"
              ? `${copy.substitution} · ${copy.out} ${moment.out} · ${copy.in} ${moment.in}`
              : `${shouted(moment, copy) === null ? word(moment, copy) : `${shouted(moment, copy)}${moment.count > 1 ? ` ×${moment.count}` : ""}`} · ${moment.name}${
                  moment.multiplier === 0
                    ? ` · ${copy.bench}`
                    : moment.points === null
                      ? ""
                      : ` · ${signed(moment.points, locale)}`
                }`}
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
