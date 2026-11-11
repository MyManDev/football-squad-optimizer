/**
 * The GOL moment (the owner's Plan 1 of 2026-11-11): when a read brings a goal by one of the
 * member's players, the fourth official's board rises in the middle of the screen with the
 * shout in LED letters, the scorer on the green panel and the points in LED digits; for the
 * captain the digits show the goal's points, then the armband, then what the member receives.
 * The board goes down after a few seconds, or at once on a tap or Escape, and the points run
 * into the live score. An assist rises the same board with its own shout, and an automatic
 * substitution the board as it is meant; a card passes along a single LED line at the foot of
 * the screen. A pick the official scorer does not count raises nothing.
 *
 * The layer never holds the page: only the board takes taps, focus stays where it is, and a
 * status line says each moment once. The board stands inside the screen, clear of the live
 * score's head, and nothing plays while the opening cover, a dialog or a modal panel is up.
 * Under the reduced-motion preference nothing moves: one still line names the read's moments
 * and goes after a few seconds, or on a tap. Every duration is a `--motion-*` token's
 * (motion.ts) and every animation moves only transform and opacity.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  MOTION_EASE,
  MOTION_MS,
  prefersReducedMotion,
  REDUCED_MOTION_QUERY,
} from "../../design/motion";
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

/** The room a board keeps from the screen's edges, the phone bar and the live score. */
const EDGE = 12;

/**
 * Where a board stands: 38% down the screen, wholly inside it and below the phone bar, and
 * clear of the live score's head (its refresh button and total) while that is in view, so a
 * tap meant for the button reaches it and the points have somewhere to run. Where the head
 * leaves no room above or below, the board keeps at least the refresh button clear. Beside a
 * sidebar it stands over the page's own column, not the middle of the window.
 */
function placeBoard(place: HTMLElement | null, board: HTMLElement | null): void {
  if (place === null || board === null) return;
  // Each placing starts from the stylesheet's, so a turned phone or a closed sidebar leaves
  // nothing of the place before.
  place.style.left = "";
  place.style.right = "";
  place.style.transform = "";
  const column = document.getElementById("main")?.getBoundingClientRect();
  if (column !== undefined && column.left > EDGE && column.width > 0) {
    place.style.left = `${Math.round(column.left + EDGE)}px`;
    place.style.right = `${Math.round(Math.max(EDGE, window.innerWidth - column.right + EDGE))}px`;
  }
  const view = window.innerHeight;
  // Below the phone bar, and below the section strip pinned under it while that is shown.
  let cover = 0;
  const bar = document.querySelector("[data-phone-bar]")?.getBoundingClientRect();
  if (bar !== undefined && bar.height > 0) cover = bar.bottom;
  const strip = document.querySelector("[data-pinned-strip]");
  if (strip !== null && strip.closest("[data-shown]") !== null) {
    const pinned = strip.getBoundingClientRect();
    if (pinned.height > 0) cover = Math.max(cover, pinned.bottom);
  }
  const ceiling = cover + EDGE;
  // A board taller than the room below the bars (a phone on its side) stands smaller, whole.
  const natural = board.offsetHeight;
  const room = view - ceiling - EDGE;
  const scale = natural > room && natural > 0 ? Math.max(0.5, room / natural) : 1;
  if (scale < 1) place.style.transform = `scale(${scale.toFixed(3)})`;
  // The board's height on the screen, before any turn of its rise.
  const height = natural * scale;
  const floor = Math.max(ceiling, view - height - EDGE);
  let top = Math.min(Math.max(Math.round(view * 0.38), ceiling), floor);
  const total = document.querySelector("[data-live-total]");
  const card = total?.closest("[data-live-head], [data-member-live-score]");
  if (total && card) {
    const from = card.getBoundingClientRect().top;
    const to = total.getBoundingClientRect().bottom;
    const over = (at: number, low: number, high: number) => high > at && low < at + height;
    if (over(top, from, to) && to > 0 && from < view) {
      if (to + EDGE <= floor) top = to + EDGE;
      else if (from - EDGE - height >= ceiling) top = from - EDGE - height;
      else {
        // No room for the board beside the head: it keeps the refresh button clear if it can.
        const button = card.querySelector("[data-live-refresh]")?.getBoundingClientRect();
        const clear = [floor, ceiling].find(
          (at) => button === undefined || !over(at, button.top, button.bottom),
        );
        if (clear !== undefined) top = clear;
      }
    }
  }
  place.style.top = `${Math.round(top)}px`;
}

/**
 * Fits a standing board's LED words and places it again whenever the screen or the page's
 * column changes (a phone turned, the iOS bars shown or hidden, the sidebar opened or closed),
 * so it never stays outside the screen or wider than it; the returned cleanup stops it.
 */
function keepPlaced(
  place: { current: HTMLElement | null },
  board: { current: HTMLElement | null },
  refit: () => void,
) {
  const again = () => {
    refit();
    placeBoard(place.current, board.current);
  };
  window.addEventListener("resize", again);
  window.visualViewport?.addEventListener("resize", again);
  const column = document.getElementById("main");
  const watch =
    column !== null && typeof ResizeObserver === "function" ? new ResizeObserver(again) : null;
  if (column !== null) watch?.observe(column);
  return () => {
    window.removeEventListener("resize", again);
    window.visualViewport?.removeEventListener("resize", again);
    watch?.disconnect();
  };
}

/**
 * Fits LED letters to their room at one size, never under the smallest LED size. With
 * `beside`, the order chip next to the letters keeps its room.
 */
function fitLed(letters: HTMLElement | null, room: HTMLElement | null, beside: boolean): void {
  if (letters === null || room === null) return;
  letters.style.fontSize = "";
  const chip = beside ? (letters.nextElementSibling as HTMLElement | null) : null;
  const free = room.clientWidth - (chip === null ? 0 : chip.offsetWidth + FIT_GAP);
  if (free > 0 && letters.scrollWidth > free) {
    const size = parseFloat(getComputedStyle(letters).fontSize);
    letters.style.fontSize = `${Math.max(LED_MIN, Math.floor((size * free) / letters.scrollWidth))}px`;
  }
}

/**
 * Runs `fit` now and again once the page's fonts have loaded, since a Turkish letter's face
 * (İ, Ğ, Ş) can arrive after the first fit; the returned cleanup cancels the second run.
 */
function fitNowAndOnFonts(fit: () => void): () => void {
  fit();
  let mounted = true;
  // Absent where the page has no font loading (the tests' document).
  document.fonts?.ready.then(
    () => {
      if (mounted) fit();
    },
    () => undefined,
  );
  return () => {
    mounted = false;
  };
}

/** One moment on its way: its place among the read's big moments, and the stream it came in. */
interface Queued {
  moment: BoardMoment;
  order: string;
  source: string;
}

interface Batch {
  /** One stream per source (`live:`, `replay:`), so the two never stand for each other. */
  id: string;
  items: BoardMoment[];
}

interface LayerState {
  /** Every batch taken: a batch plays once, whichever stream the page shows in between. */
  taken: ReadonlySet<string>;
  /** The stream the page shows; a queued moment of another plays no more. */
  source: string | null;
  queue: Queued[];
  still: BoardMoment[] | null;
  /** The still line's revision: each read added to it gives it its full time again. */
  stillRevision: number;
  /** What the live region says: the moment playing, kept while a panel holds it back. */
  voice: { key: string | null; text: string };
  /** Moments that will not play (another stream, or turned into the still line), in order. */
  dropped: string[];
}

const sourceOf = (id: string) => id.split(":")[0] ?? "";

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

/**
 * The reduced-motion preference as it is now, read again whenever the visitor changes it, so a
 * page left open follows the setting.
 */
function useReducedMotion(): boolean {
  const [, changed] = useState(0);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const update = () => changed((count) => count + 1);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return prefersReducedMotion();
}

/**
 * Gives focus back where it was before a board or line rose, when it is on the board as it
 * goes (a screen reader's double tap focuses a button even with tabIndex -1), so it never falls
 * to the page's body.
 */
function giveBackFocus(owner: HTMLElement | null, before: Element | null): void {
  if (owner === null || !owner.contains(document.activeElement)) return;
  if (before instanceof HTMLElement && before.isConnected && before !== document.body) {
    before.focus({ preventScroll: true });
  } else {
    (document.activeElement as HTMLElement | null)?.blur();
  }
}

export function GoalMomentLayer({
  batch,
  source = batch === null ? "live" : sourceOf(batch.id),
  onLanded,
}: {
  batch: Batch | null;
  /**
   * The stream the page shows now (`live` or `replay`): when it changes, the other stream's
   * moments still queued play no more.
   */
  source?: string;
  /**
   * Told when a moment has played out: a goal's or assist's points have reached the live score
   * (or will not run there), a substitution's board or a card's line has gone, or the moment
   * will not play (another stream, or reduced motion turned on with it still queued).
   */
  onLanded?: (key: string) => void;
}) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  const layer = useRef<HTMLDivElement>(null);
  // Nothing plays under the opening cover, a modal dialog or panel, or a cover over the page.
  const clear = usePageClear(layer);
  const reduce = useReducedMotion();
  const landed = useRef(onLanded);
  useEffect(() => {
    landed.current = onLanded;
  });
  const [state, setState] = useState<LayerState>({
    taken: new Set(),
    source: null,
    queue: [],
    still: null,
    stillRevision: 0,
    voice: { key: null, text: "" },
    dropped: [],
  });
  // One pass over what changed, settled into one state for this render.
  let next = state;
  // The page shows another stream: its queued moments go, and the page is told.
  if (source !== next.source) {
    const gone = next.queue.filter((queued) => queued.source !== source);
    next = {
      ...next,
      source,
      queue: next.queue.filter((queued) => queued.source === source),
      still: next.source === null ? next.still : null,
      voice: gone.length > 0 ? { key: null, text: "" } : next.voice,
      dropped: [...next.dropped, ...gone.map((queued) => queued.moment.key)],
    };
  }
  // A new read's moments join the queue once; under reduced motion they join the still line.
  if (batch !== null && !next.taken.has(batch.id)) {
    // Only what brings the member points: a reserve the scorer does not count raises nothing.
    const items = batch.items.filter(shownOnBoard);
    const bigs = items.filter((moment) => moment.size === "big").length;
    let big = 0;
    const queued = items.map((moment) => ({
      moment,
      order: moment.size === "big" && bigs > 1 ? `${++big}/${bigs}` : "",
      source: sourceOf(batch.id),
    }));
    const taken = new Set(next.taken).add(batch.id);
    next = reduce
      ? {
          ...next,
          taken,
          still: items.length > 0 ? [...(next.still ?? []), ...items] : next.still,
          stillRevision: items.length > 0 ? next.stillRevision + 1 : next.stillRevision,
        }
      : { ...next, taken, queue: [...next.queue, ...queued], still: null };
  }
  // Reduced motion turned on with moments still queued: they join the still line at once.
  if (reduce && next.queue.length > 0) {
    const moments = next.queue.map((queued) => queued.moment);
    next = {
      ...next,
      queue: [],
      still: [...(next.still ?? []), ...moments],
      stillRevision: next.stillRevision + 1,
      voice: { key: null, text: "" },
      dropped: [...next.dropped, ...moments.map((moment) => moment.key)],
    };
  }
  const playing = clear ? next.queue[0] : undefined;
  // Each moment is said once: when it starts, and not again if a panel held it back.
  if (playing !== undefined && next.voice.key !== playing.moment.key) {
    next = {
      ...next,
      voice: { key: playing.moment.key, text: announcement(playing.moment, copy, locale) },
    };
  }
  if (next !== state) setState(next);
  // The page hears about the moments that will not play after this render, not during it.
  const told = useRef(0);
  useEffect(() => {
    const keys = state.dropped.slice(told.current);
    told.current = state.dropped.length;
    for (const key of keys) landed.current?.(key);
  }, [state.dropped]);
  const played = () =>
    setState((current) => ({
      ...current,
      queue: current.queue.slice(1),
      voice: { key: null, text: "" },
    }));
  const spoken =
    next.still !== null && clear
      ? next.still.map((moment) => announcement(moment, copy, locale)).join(". ")
      : next.voice.text;
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
          onLanded={(key) => landed.current?.(key)}
          onDone={played}
        />
      ) : playing.moment.size === "small" ? (
        <SmallLine
          key={playing.moment.key}
          moment={playing.moment}
          copy={copy}
          locale={locale}
          onLanded={(key) => landed.current?.(key)}
          onDone={played}
        />
      ) : (
        <Board
          key={playing.moment.key}
          queued={{ moment: playing.moment, order: playing.order }}
          copy={copy}
          locale={locale}
          onLanded={(key) => landed.current?.(key)}
          onDone={played}
        />
      )}
      {next.still !== null && clear ? (
        <StillLine
          key={next.stillRevision}
          moments={next.still}
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
  const place = useRef<HTMLDivElement>(null);
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
  useLayoutEffect(() => fitNowAndOnFonts(() => fitLed(shout.current, head.current, true)), [text]);

  useLayoutEffect(() => {
    // Where focus was when the board rose, to give it back if a tap or a screen reader put it
    // on the board.
    const before = document.activeElement;
    const owner = board.current;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const later = (ms: number, step: () => void) => timers.push(setTimeout(step, ms));
    let gone = false;
    const leave = () => {
      if (gone) return;
      gone = true;
      timers.forEach(clearTimeout);
      giveBackFocus(board.current, before);
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
    placeBoard(place.current, board.current);
    const unplace = keepPlaced(place, board, () => fitLed(shout.current, head.current, true));
    // Risen, the board and its letters let go of their motion: no 3D turn stays on them.
    animate(
      board.current,
      [
        { transform: "perspective(700px) rotateX(-90deg)", opacity: 0 },
        { transform: "perspective(700px) rotateX(0deg)", opacity: 1 },
      ],
      MOMENT_TIMING.rise,
      { fill: "backwards" },
    );
    shout.current?.querySelectorAll("span").forEach((letter, index) => {
      animate(letter, [{ opacity: 0 }, { opacity: 1 }], MOTION_MS.uiFast, {
        delay: MOMENT_TIMING.rise * 0.75 + index * MOMENT_TIMING.letter,
        easing: "linear",
        fill: "backwards",
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
      unplace();
      // Taken down unplayed (a panel opened, the stream changed): focus does not fall with it.
      giveBackFocus(owner, before);
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
    <div ref={place} className={styles.place} data-size={moment.size}>
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
 * goal's board and goes down by itself, or at once on a tap or Escape. Once it has gone the
 * page is told (`onLanded`), so the live card takes the read that brought it.
 */
function SubstitutionBoard({
  moment,
  copy,
  onLanded,
  onDone,
}: {
  moment: SubstitutionMoment;
  copy: Copy;
  onLanded?: (key: string) => void;
  onDone: () => void;
}) {
  const place = useRef<HTMLDivElement>(null);
  const board = useRef<HTMLButtonElement>(null);
  const word = useRef<HTMLSpanElement>(null);
  const head = useRef<HTMLSpanElement>(null);
  const done = useRef(onDone);
  const told = useRef(onLanded);
  useEffect(() => {
    done.current = onDone;
    told.current = onLanded;
  });
  const leaving = useRef<(() => void) | null>(null);
  useLayoutEffect(
    () => fitNowAndOnFonts(() => fitLed(word.current, head.current, false)),
    [copy.substitution],
  );
  useLayoutEffect(() => {
    const before = document.activeElement;
    const owner = board.current;
    let gone = false;
    const finish = () => {
      told.current?.(moment.key);
      done.current();
    };
    const leave = () => {
      if (gone) return;
      gone = true;
      clearTimeout(timer);
      giveBackFocus(board.current, before);
      const fall = animate(
        board.current,
        [
          { transform: "perspective(700px) rotateX(0deg)", opacity: 1 },
          { transform: "perspective(700px) rotateX(-90deg)", opacity: 0 },
        ],
        MOMENT_TIMING.fall,
      );
      if (fall === null) finish();
      else fall.finished.then(finish, finish);
    };
    leaving.current = leave;
    placeBoard(place.current, board.current);
    const unplace = keepPlaced(place, board, () => fitLed(word.current, head.current, false));
    animate(
      board.current,
      [
        { transform: "perspective(700px) rotateX(-90deg)", opacity: 0 },
        { transform: "perspective(700px) rotateX(0deg)", opacity: 1 },
      ],
      MOMENT_TIMING.rise,
      { fill: "backwards" },
    );
    const timer = setTimeout(leave, MOMENT_TIMING.rise + MOMENT_TIMING.holdAssist);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leave();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      unplace();
      giveBackFocus(owner, before);
    };
  }, [moment.key]);
  return (
    <div ref={place} className={styles.place} data-size="big">
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

/** A card's LED line: it goes after a while, on a tap or on Escape, and then tells the page. */
function SmallLine({
  moment,
  copy,
  locale,
  onLanded,
  onDone,
}: {
  moment: LiveMoment;
  copy: Copy;
  locale: string;
  onLanded?: (key: string) => void;
  onDone: () => void;
}) {
  const line = useRef<HTMLDivElement>(null);
  const leaving = useRef<(() => void) | null>(null);
  const done = useRef(onDone);
  const told = useRef(onLanded);
  useEffect(() => {
    done.current = onDone;
    told.current = onLanded;
  });
  useLayoutEffect(() => {
    animate(
      line.current,
      [
        { transform: "translateY(-8px)", opacity: 0 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      MOTION_MS.ui,
      { fill: "backwards" },
    );
    let gone = false;
    const finish = () => {
      told.current?.(moment.key);
      done.current();
    };
    const leave = () => {
      if (gone) return;
      gone = true;
      clearTimeout(timer);
      const away = animate(line.current, [{ opacity: 1 }, { opacity: 0 }], MOTION_MS.ui);
      if (away === null) finish();
      else away.finished.then(finish, finish);
    };
    leaving.current = leave;
    const timer = setTimeout(leave, MOMENT_TIMING.line);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leave();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
    };
  }, [moment.key]);
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
  const line = useRef<HTMLDivElement>(null);
  // Where focus was when the line came: its close button gives it back as the line goes.
  const before = useRef<Element | null>(null);
  const close = useRef(() => {
    giveBackFocus(line.current, before.current);
    done.current();
  });
  useLayoutEffect(() => {
    before.current = document.activeElement;
    const owner = line.current;
    const timer = setTimeout(() => close.current(), MOMENT_TIMING.still);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      giveBackFocus(owner, before.current);
    };
  }, []);
  return (
    <div ref={line} className={styles.still} data-goal-still onClick={() => close.current()}>
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
        onClick={(event) => {
          // The line's own tap closes it once.
          event.stopPropagation();
          close.current();
        }}
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}
