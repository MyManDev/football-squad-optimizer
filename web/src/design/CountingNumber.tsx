import { useLayoutEffect, useRef } from "react";

import { countTo, rememberCount } from "./countMotion";

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
  // A new language or locale rewrites the same value in its own format, without a count.
  const text = format(value);

  useLayoutEffect(() => {
    const figure = element.current;
    if (figure === null) return undefined;
    const from = rememberCount(countKey, value);
    if (from === null || from === value) {
      figure.textContent = text;
      return undefined;
    }
    const animation = countTo(figure, from, value, (current) => formatRef.current(current));
    return () => animation?.cancel();
  }, [countKey, value, text]);

  return <span ref={element} className={className} data-counting-number="" />;
}
