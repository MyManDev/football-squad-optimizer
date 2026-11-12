/**
 * A figure LIVE writes itself, so a count can run on it (`countLive`): an empty span whose text
 * is written after each render, as `design/CountingNumber.tsx` does. It never counts on its first
 * showing. A following figure (Canlı puan) counts from what it showed to each new value, as the
 * GOL board's points land; any other figure is written at once, and the read's motion counts it
 * (`playRow`, the duel), from the value the plan holds to the one written here (`data-value`).
 */

import { useLayoutEffect, useRef } from "react";

import { countLive, settleCount } from "./liveMotion";

export function LiveNumber({
  value,
  format,
  follow = false,
  className,
}: {
  value: number;
  /** The figure's words; read again only when `value` or the language changes. */
  format: (value: number) => string;
  /** Counts from what it showed to each new value. */
  follow?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  const formatRef = useRef(format);
  const text = format(value);
  useLayoutEffect(() => {
    formatRef.current = format;
  });
  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return undefined;
    const previous = shown.current;
    shown.current = value;
    if (follow && previous !== null && previous !== value) {
      countLive(element, previous, value, (figure) => formatRef.current(Math.round(figure)));
    } else {
      settleCount(element);
      element.textContent = formatRef.current(value);
    }
    return undefined;
    // `text` changes with the language: the figure is written again, not counted.
  }, [value, follow, text]);
  useLayoutEffect(
    () => () => {
      const element = ref.current;
      if (element !== null) settleCount(element);
    },
    [],
  );
  return <span ref={ref} className={className} data-live-number="" data-value={value} />;
}
