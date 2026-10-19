import { useLayoutEffect, useRef } from "react";

import { countTo, rememberCount, type Count } from "./countMotion";

type Props = {
  /** Names the figure for this page session, so a remounted figure counts from its last value. */
  countKey: string;
  value: number;
  format: (value: number) => string;
  className?: string;
};

/**
 * A figure that counts from its previous value to a new one, once per change (#1131 step 3).
 *
 * The first time a key is shown the value is written as it is, and showing the same value
 * again starts nothing. The text is written here rather than rendered as a child, so the count
 * and React never write the same text node. The figure is not a live region, so the values in
 * between are not announced; the final value is the element's text once the count ends.
 */
export function CountingNumber({ countKey, value, format, className }: Props) {
  const element = useRef<HTMLSpanElement>(null);
  // The latest format, read by a running count; a new function each render must not restart it.
  const formatRef = useRef(format);
  useLayoutEffect(() => {
    formatRef.current = format;
  });
  // The count in flight, if any.
  const count = useRef<Count | null>(null);
  const text = format(value);

  useLayoutEffect(() => {
    const figure = element.current;
    if (figure === null) return undefined;
    const from = rememberCount(countKey, value);
    if (from === null || from === value) {
      figure.textContent = formatRef.current(value);
      return undefined;
    }
    const running = countTo(figure, from, value, (current) => formatRef.current(current));
    if (running === null) return undefined;
    count.current = running;
    // A new value, or an unmount, mid-count: the next count starts from the number on screen,
    // and this one writes nothing more.
    return () => {
      count.current = null;
      rememberCount(countKey, running.stop());
    };
  }, [countKey, value]);

  // A new language or locale rewrites the figure in its own format, without a count. A count in
  // flight reads the format on each frame, so it carries on in the new one and ends on its value.
  useLayoutEffect(() => {
    if (count.current?.running) return;
    if (element.current !== null) element.current.textContent = text;
  }, [text]);

  return <span ref={element} className={className} data-counting-number="" />;
}
