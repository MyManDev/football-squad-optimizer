import { flushSync } from "react-dom";

import { MOTION_MS, MOTION_ROUTE_EASE, REDUCED_MOTION_QUERY, prefersReducedMotion } from "./motion";

/** What a started transition hands back: three promises the browser may reject. */
type StartedTransition = Partial<Pick<ViewTransition, "ready" | "finished" | "updateCallbackDone">>;

type TransitionDocument = Document & {
  startViewTransition?: (update: () => Promise<void> | void) => StartedTransition | undefined;
};

type MediaSource =
  (Pick<Window, "matchMedia"> & { navigator?: Pick<Navigator, "userAgent"> }) | undefined;

function canSnapshotPage(source: MediaSource, document: TransitionDocument | undefined) {
  const agent = source?.navigator?.userAgent ?? "";
  const webkit =
    /AppleWebKit\//.test(agent) &&
    /Safari\//.test(agent) &&
    !/(?:Chrome|Chromium|Edg)\//.test(agent);
  return typeof document?.startViewTransition === "function" && !webkit;
}

/** Called before paint where native snapshots are unsafe or unavailable.
 * Cancelling this live-DOM arrival never blocks navigation or input. */
export function arriveWithoutSnapshot(
  main: HTMLElement | null,
  source: MediaSource = globalThis.window,
  document: TransitionDocument | undefined = globalThis.document,
): (() => void) | undefined {
  if (canSnapshotPage(source, document) || prefersReducedMotion(source) || !main?.animate) return;
  const animation = main.animate(
    [
      { opacity: 0.25, transform: "translateY(6px)" },
      { opacity: 1, transform: "none" },
    ],
    { duration: MOTION_MS.page, easing: `cubic-bezier(${MOTION_ROUTE_EASE.join(", ")})` },
  );
  const preference = source?.matchMedia?.(REDUCED_MOTION_QUERY);
  const stopIfReduced = (event: MediaQueryListEvent) => {
    if (event.matches) animation.cancel();
  };
  const unwatch = () => preference?.removeEventListener?.("change", stopIfReduced);
  preference?.addEventListener?.("change", stopIfReduced);
  void animation.finished.then(unwatch, unwatch);
  return () => {
    unwatch();
    animation.cancel();
  };
}

/**
 * A page change as one short crossfade (#1131): the View Transitions API snapshots the page
 * as it is, `update` runs and is committed at once, and the browser fades the old picture
 * into the new one in the motion tokens' page time (`transitions.css`). Where `ready` is
 * given, the new picture is taken once it resolves, or after the data time at the latest,
 * so a step that draws its page a moment later fades into that page and not into a
 * loading screen. A browser without the API, or a viewer who asked for reduced motion,
 * gets the change at once. PageShell adds a live-DOM arrival where motion is allowed.
 *
 * The transition is kept so its three promises are handled. A browser skips a transition
 * when another starts before it is drawn and rejects its `ready` with an AbortError, though
 * the update still runs: that is quiet. An update that throws rejects all three; its error
 * is reported once, as an uncaught error would be, and not three times as unhandled
 * rejections.
 */
export function crossfade(
  update: () => void,
  ready?: () => Promise<void>,
  source: MediaSource = globalThis.window,
  document: TransitionDocument | undefined = globalThis.document,
): void {
  // Keep WebKit's snapshot guard: its route updates can stall or crash the engine.
  if (!document || !canSnapshotPage(source, document) || prefersReducedMotion(source)) {
    update();
    return;
  }
  const transition: StartedTransition | undefined = document.startViewTransition!(async () => {
    flushSync(update);
    if (ready) {
      await Promise.race([
        ready(),
        new Promise<void>((resolve) => setTimeout(resolve, MOTION_MS.data)),
      ]);
    }
  });
  transition?.ready?.catch(() => {});
  transition?.finished?.catch(() => {});
  transition?.updateCallbackDone?.catch((error: unknown) => {
    if (!(error instanceof DOMException && error.name === "AbortError"))
      globalThis.reportError?.(error);
  });
}
