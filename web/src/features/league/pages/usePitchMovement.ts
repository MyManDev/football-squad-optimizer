import { useLayoutEffect, useRef, type RefObject } from "react";

import { MOTION_EASE, motionDuration } from "../../../design/motion";

interface Layout {
  context: string;
  key: string;
  width: number;
  hasPlan: boolean;
  positions: Map<string, { x: number; y: number }>;
}

/** Move the same player between two shown plans, without changing their final layout. */
export function usePitchMovement(
  field: RefObject<HTMLDivElement | null>,
  context: string | null,
  key: string,
  visible: boolean,
  planned = true,
) {
  const previous = useRef<Layout | null>(null);
  useLayoutEffect(() => {
    const root = field.current;
    if (!root || !context || !visible) {
      previous.current = null;
      return;
    }
    const nodes = [...root.querySelectorAll<HTMLElement>("[data-player-motion]")];
    const measure = (): Layout => {
      const bounds = root.getBoundingClientRect();
      return {
        context,
        key,
        width: bounds.width,
        hasPlan: planned || (previous.current?.context === context && previous.current.hasPlan),
        positions: new Map(
          nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            return [
              node.dataset.playerMotion!,
              { x: rect.left - bounds.left, y: rect.top - bounds.top },
            ];
          }),
        ),
      };
    };
    const before = previous.current;
    const after = measure();
    previous.current = after;
    const running: Animation[] = [];
    const duration = motionDuration("data");
    if (
      duration > 0 &&
      planned &&
      before?.hasPlan &&
      before?.context === context &&
      before.key !== key &&
      after.width > 0 &&
      Math.abs(before.width - after.width) < 1
    ) {
      for (const node of nodes) {
        const old = before.positions.get(node.dataset.playerMotion!);
        const next = after.positions.get(node.dataset.playerMotion!);
        if (!old || !next || typeof node.animate !== "function") continue;
        const x = old.x - next.x;
        const y = old.y - next.y;
        if (Math.abs(x) + Math.abs(y) < 1) continue;
        running.push(
          node.animate(
            [{ transform: `translate(${x}px, ${y}px)` }, { transform: "translate(0px, 0px)" }],
            { duration, easing: `cubic-bezier(${MOTION_EASE.join(",")})` },
          ),
        );
      }
    }
    // A resized pitch establishes a new baseline; resizing itself is never a plan change.
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (previous.current?.context !== context) return;
            if (Math.abs(root.getBoundingClientRect().width - previous.current!.width) < 1) return;
            running.forEach((animation) => animation.cancel());
            previous.current = measure();
          });
    observer?.observe(root);
    return () => {
      observer?.disconnect();
      running.forEach((animation) => animation.cancel());
    };
  }, [field, context, key, visible, planned]);
}
