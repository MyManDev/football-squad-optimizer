/**
 * A figure LIVE writes itself, so a count can run on it (`countLive`): an empty span whose text
 * is written after each render, as `design/CountingNumber.tsx` does. It never counts on its first
 * showing, but where it is told to (`start`): from the value last seen, once. A following figure
 * (Canlı puan) counts from what it showed to each new value, as the GOL board's points land;
 * any other figure is written at once, and the read's motion counts it (`playRow`, the duel),
 * from the value the plan holds to the one written here (`data-value`).
 */

import { useLayoutEffect, useRef } from "react";

import { claimMotion, countLive, settleCount } from "./liveMotion";

/** A first showing that counts: from `from`, once (`key`), as soon as `ready`. */
export interface FirstCount {
  from: number;
  key: string;
  ready: boolean;
}

export function LiveNumber({
  value,
  format,
  follow = false,
  start = null,
  className,
}: {
  value: number;
  /** The figure's words; the figure is written again only when its value or its words change. */
  format: (value: number) => string;
  /** Counts from what it showed to each new value. */
  follow?: boolean;
  /** Its first showing counts from the value last seen; until `ready`, it shows that value. */
  start?: FirstCount | null;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  const counted = useRef<string | null>(null);
  const formatRef = useRef(format);
  const text = format(value);
  useLayoutEffect(() => {
    formatRef.current = format;
  });
  const from = start?.from ?? null;
  const key = start?.key ?? null;
  const ready = start?.ready ?? false;
  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const previous = shown.current;
    const words = (figure: number) => formatRef.current(Math.round(figure));
    const write = (figure: number) => {
      settleCount(element);
      element.textContent = formatRef.current(figure);
      shown.current = figure;
    };
    if (from !== null && key !== null && counted.current !== key) {
      if (previous === null || previous === from) {
        // Held at what was last seen until the page is clear, then counted on, once.
        if (!ready) {
          write(from);
          return;
        }
        counted.current = key;
        if (claimMotion(key)) {
          shown.current = value;
          countLive(element, from, value, words);
          return;
        }
      }
    }
    if (follow && previous !== null && previous !== value) {
      shown.current = value;
      countLive(element, previous, value, words);
      return;
    }
    write(value);
    // `text` changes with the language: the figure is written again, not counted.
  }, [value, follow, text, from, key, ready]);
  useLayoutEffect(
    () => () => {
      const element = ref.current;
      if (element !== null) settleCount(element);
    },
    [],
  );
  return <span ref={ref} className={className} data-live-number="" data-value={value} />;
}
