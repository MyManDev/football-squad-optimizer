/**
 * The page-change crossfade (#1131): the View Transitions API where the browser has it and
 * the viewer has not asked for reduced motion, the change at once otherwise; the update is
 * committed inside the transition, and a `ready` the transition waits for is capped at the
 * data time so a page that never says it is drawn cannot hold the old picture.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { MOTION_MS, REDUCED_MOTION_QUERY } from "./motion";
import { crossfade } from "./viewTransition";

afterEach(() => vi.useRealTimers());

const media = (reduced: boolean) => ({
  matchMedia: (query: string) =>
    ({ matches: reduced && query === REDUCED_MOTION_QUERY }) as MediaQueryList,
});

function transitions() {
  const started: Array<Promise<void> | void> = [];
  const document = {
    startViewTransition: vi.fn((update: () => Promise<void> | void) => {
      started.push(update());
      return {};
    }),
  } as unknown as Document;
  return { document, started };
}

describe("the crossfade", () => {
  it("runs the update inside a view transition where the browser has one", async () => {
    const { document, started } = transitions();
    const update = vi.fn();
    crossfade(update, undefined, media(false), document);
    expect(document.startViewTransition).toHaveBeenCalledOnce();
    await started[0];
    expect(update).toHaveBeenCalledOnce();
  });

  it("makes the change at once under reduced motion, starting no transition", () => {
    const { document } = transitions();
    const update = vi.fn();
    crossfade(update, undefined, media(true), document);
    expect(update).toHaveBeenCalledOnce();
    expect(document.startViewTransition).not.toHaveBeenCalled();
  });

  it("makes the change at once where the browser has no View Transitions", () => {
    const update = vi.fn();
    crossfade(update, undefined, media(false), {} as Document);
    expect(update).toHaveBeenCalledOnce();
  });

  it("takes the new picture once the page says it is drawn", async () => {
    const { document, started } = transitions();
    let drawn: () => void = () => {};
    const ready = () =>
      new Promise<void>((resolve) => {
        drawn = resolve;
      });
    let done = false;
    crossfade(() => {}, ready, media(false), document);
    void Promise.resolve(started[0]).then(() => (done = true));
    await Promise.resolve();
    expect(done).toBe(false);
    drawn();
    await started[0];
    expect(done).toBe(true);
  });

  it("takes it after the data time at the latest", async () => {
    vi.useFakeTimers();
    const { document, started } = transitions();
    let done = false;
    crossfade(
      () => {},
      () => new Promise<void>(() => {}),
      media(false),
      document,
    );
    void Promise.resolve(started[0]).then(() => (done = true));
    await vi.advanceTimersByTimeAsync(MOTION_MS.data - 1);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(done).toBe(true);
  });
});

describe("the crossfade's stylesheet", () => {
  it("times the browser's crossfade with the card time and the motion easing", () => {
    const css = readFileSync(join(__dirname, "transitions.css"), "utf-8");
    expect(css).toMatch(
      /::view-transition-old\(root\),\s*::view-transition-new\(root\)\s*\{[^}]*animation-duration: var\(--motion-ui\);[^}]*animation-timing-function: var\(--motion-ease\)/,
    );
  });

  it("is loaded with the tokens", () => {
    const main = readFileSync(join(__dirname, "../main.tsx"), "utf-8");
    expect(main).toMatch(
      /import "\.\/design\/tokens\.css";\nimport "\.\/design\/transitions\.css";/,
    );
  });
});
