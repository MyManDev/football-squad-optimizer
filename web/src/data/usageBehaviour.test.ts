/// <reference types="node" />
/**
 * The behaviour events as they leave the browser (ADR 0015): only when the build names this
 * page's own origin, only words of the Worker's lists and integers in their ranges, at most
 * as often as the throttles let them, and never an error for the page.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("web-vitals", () => ({
  onLCP: vi.fn(),
  onINP: vi.fn(),
  onCLS: vi.fn(),
  onFCP: vi.fn(),
  onTTFB: vi.fn(),
}));

const ORIGIN = window.location.origin;
const LEAGUE = 352490;
const ENTRY = 35249001;
const MEMBER = `/league/${LEAGUE}/members/${ENTRY}`;
const ARRIVED_KEY = "squadopt.usage.arrived";
const WEEK_KEY = "squadopt.usage.week";

type Behaviour = typeof import("./usageBehaviour");
let behaviour: Behaviour;

const beacon = vi.fn<(url: string, body: string) => boolean>();
type Sent = Record<string, unknown>;
const sent = (kind?: string): Sent[] =>
  beacon.mock.calls
    .map(([, body]) => JSON.parse(body) as Sent)
    .filter((event) => kind === undefined || event.kind === kind);

/** Properties a test sets on the window or the document, restored after it. */
const restores: (() => void)[] = [];
function setProperty(target: object, key: string, value: unknown) {
  const own = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { value, configurable: true, writable: true });
  restores.push(() => {
    if (own) Object.defineProperty(target, key, own);
    else Reflect.deleteProperty(target, key);
  });
}

function boxOf(element: Element, left: number, top: number, width: number, height: number) {
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue(
    DOMRect.fromRect({ x: left, y: top, width, height }),
  );
}

function click(element: Element, x: number, y: number) {
  element.dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true, clientX: x, clientY: y, detail: 1 }),
  );
}

/** The half second a click is watched, and the rest of the rage window it may wait for. */
const settle = () => vi.advanceTimersByTime(800);

function start(path = `${MEMBER}/what-if`) {
  window.history.pushState({}, "", path);
  behaviour.watchUsageBehaviour();
}

function move(path: string) {
  window.history.pushState({}, "", path);
  behaviour.watchUsageBehaviour();
}

function zone(word: string, inner = "<button type='button'>go</button><span>text</span>") {
  const element = document.createElement("section");
  element.dataset.zone = word;
  element.innerHTML = inner;
  document.body.append(element);
  return element;
}

function page(scrollHeight: number, innerHeight: number, scrollY = 0) {
  setProperty(document.documentElement, "scrollHeight", scrollHeight);
  setProperty(document.documentElement, "scrollWidth", 1000);
  setProperty(window, "innerHeight", innerHeight);
  setProperty(window, "scrollY", scrollY);
}

function scrollTo(y: number) {
  (window as { scrollY: number }).scrollY = y;
  window.dispatchEvent(new Event("scroll"));
}

beforeEach(async () => {
  vi.useFakeTimers({ now: new Date(2026, 10, 18, 12) });
  vi.resetModules();
  behaviour = await import("./usageBehaviour");
  beacon.mockReset();
  beacon.mockReturnValue(true);
  Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
  vi.stubEnv("VITE_USAGE_ORIGIN", ORIGIN);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  sessionStorage.clear();
  localStorage.clear();
  page(1000, 1000);
});

afterEach(async () => {
  // The measurement library is imported once listening starts; it settles inside its test.
  await vi.dynamicImportSettled();
  behaviour.stopUsageBehaviour();
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  while (restores.length > 0) restores.pop()!();
  Reflect.deleteProperty(navigator, "sendBeacon");
  document.body.innerHTML = "";
  window.history.pushState({}, "", "/");
});

describe("where a click landed", () => {
  it("names the nearest known zone and the cell of its 20 by 20 grid", () => {
    const pitch = zone("pitch");
    boxOf(pitch, 100, 200, 400, 200);
    start();
    click(pitch.querySelector("span")!, 300, 250);
    settle();
    expect(sent("click")).toEqual([
      expect.objectContaining({ zone: "pitch", cell: 5 * 20 + 10, target: "plain" }),
    ]);
  });

  it("passes over a word it does not know to the known zone around it", () => {
    const squad = zone("squad", "<div data-zone='bogus'><span>text</span></div>");
    boxOf(squad, 0, 0, 200, 200);
    start();
    click(squad.querySelector("span")!, 199, 0);
    settle();
    expect(sent("click")[0]).toMatchObject({ zone: "squad", cell: 19 });
  });

  it("clamps a point outside the zone's box to its edge", () => {
    const squad = zone("squad");
    boxOf(squad, 100, 100, 200, 200);
    start();
    click(squad.querySelector("span")!, 50, 1000);
    settle();
    expect(sent("click")[0]).toMatchObject({ cell: 19 * 20 });
  });

  it("is the page, over the whole document, where no zone holds it", () => {
    page(4000, 800, 1000);
    const plain = document.createElement("p");
    document.body.append(plain);
    start();
    click(plain, 999, 500);
    settle();
    // Page y 1500 of 4000 is row 7; x 999 of 1000 is column 19.
    expect(sent("click")[0]).toMatchObject({ zone: "page", cell: 7 * 20 + 19 });
  });

  it("puts a click from the keyboard in its target's middle", () => {
    const pitch = zone("pitch");
    boxOf(pitch, 0, 0, 200, 200);
    const button = pitch.querySelector("button")!;
    boxOf(button, 100, 100, 20, 20);
    start();
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 0 }));
    settle();
    expect(sent("click")[0]).toMatchObject({ cell: 11 * 20 + 11, target: "control" });
  });

  it("cuts an empty box into one cell", () => {
    expect(behaviour.cellOf(10, 10, { left: 0, top: 0, width: 0, height: 0 })).toBe(0);
  });

  it.each([
    ["<a href='/x'><span id='t'>x</span></a>", "control"],
    ["<button id='t' type='button'>x</button>", "control"],
    ["<label><input id='t'></label>", "control"],
    ["<select id='t'></select>", "control"],
    ["<textarea id='t'></textarea>", "control"],
    ["<details><summary id='t'>x</summary></details>", "control"],
    ["<label id='t'>x</label>", "control"],
    ...["button", "link", "tab", "switch", "checkbox", "radio", "menuitem", "option"].map(
      (role): [string, string] => [`<div role='${role}'><b id='t'>x</b></div>`, "control"],
    ),
    ["<a id='t'>no address</a>", "plain"],
    ["<div role='presentation'><b id='t'>x</b></div>", "plain"],
    ["<p id='t'>text</p>", "plain"],
  ])("%s is a %s", (inner, target) => {
    zone("pitch", inner);
    start();
    click(document.getElementById("t")!, 1, 1);
    settle();
    expect(sent("click")[0]).toMatchObject({ target });
  });
});

describe("what a click did", () => {
  it("is dead when for half a second nothing changed", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("span")!, 10, 10);
    vi.advanceTimersByTime(499);
    expect(sent("click")).toEqual([]);
    settle();
    expect(sent("click")).toEqual([expect.objectContaining({ mark: "dead" })]);
  });

  it("is none when the document changed in that half second", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("button")!, 10, 10);
    vi.advanceTimersByTime(300);
    pitch.append(document.createElement("div"));
    settle();
    expect(sent("click")).toEqual([expect.objectContaining({ mark: "none" })]);
  });

  it("is none when an attribute changed", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("button")!, 10, 10);
    pitch.querySelector("button")!.setAttribute("aria-expanded", "true");
    settle();
    expect(sent("click")[0]).toMatchObject({ mark: "none" });
  });

  it("is dead when the change came after the half second", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("button")!, 10, 10);
    vi.advanceTimersByTime(600);
    pitch.append(document.createElement("div"));
    settle();
    expect(sent("click")[0]).toMatchObject({ mark: "dead" });
  });

  it("is none, and counted for the page it was made on, when the address moved", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("button")!, 10, 10);
    window.history.pushState({}, "", "/fixtures");
    settle();
    expect(sent("click")[0]).toMatchObject({ mark: "none", page: "member", tool: "what-if" });
  });

  it("tells one rage event for a burst of three, and nothing for the burst's other clicks", () => {
    const pitch = zone("pitch");
    boxOf(pitch, 0, 0, 400, 400);
    const span = pitch.querySelector("span")!;
    start();
    click(span, 100, 100);
    vi.advanceTimersByTime(150);
    click(span, 110, 105);
    vi.advanceTimersByTime(150);
    click(span, 120, 110);
    vi.advanceTimersByTime(150);
    click(span, 100, 120);
    vi.advanceTimersByTime(2000);
    expect(sent("click")).toEqual([
      expect.objectContaining({ mark: "rage", cell: 5 * 20 + 5, zone: "pitch" }),
    ]);
  });

  it.each([
    ["past 800 milliseconds", [0, 400, 450], [0, 0, 0]],
    ["past 30 pixels", [0, 100, 100], [0, 10, 40]],
  ])("is no rage when the third click is %s", (_, waits, offsets) => {
    const pitch = zone("pitch");
    const span = pitch.querySelector("span")!;
    start();
    for (const [index, wait] of waits.entries()) {
      vi.advanceTimersByTime(wait);
      click(span, 100 + offsets[index]!, 100);
    }
    vi.advanceTimersByTime(2000);
    const marks = sent("click").map((event) => event.mark);
    expect(marks.length).toBeGreaterThan(0);
    expect(marks).not.toContain("rage");
  });
});

describe("a click on a label", () => {
  it("is one click, though the label passes it on to its field", () => {
    const pitch = zone("pitch", "<label id='t'>name <input type='checkbox'></label>");
    const label = pitch.querySelector("label")!;
    const field = pitch.querySelector("input")!;
    const passed = vi.fn();
    field.addEventListener("click", passed);
    start();
    click(label, 10, 10);
    vi.advanceTimersByTime(300);
    click(label, 10, 10);
    vi.advanceTimersByTime(2000);
    // The field's own click, passed on by the label, is not a third click of a burst.
    expect(passed).toHaveBeenCalledTimes(2);
    expect(sent("click")).toEqual([expect.objectContaining({ target: "control" })]);
    expect(sent("click")[0]!.mark).not.toBe("rage");
  });
});

describe("how often clicks are told", () => {
  it("drops a click told within a quarter second of the last", () => {
    const pitch = zone("pitch");
    const span = pitch.querySelector("span")!;
    start();
    click(span, 0, 0);
    vi.advanceTimersByTime(100);
    click(span, 100, 0);
    vi.advanceTimersByTime(250);
    click(span, 0, 100);
    vi.advanceTimersByTime(2000);
    expect(sent("click")).toHaveLength(2);
  });

  it("tells at most 150 a page view, and starts again on the next address", () => {
    const pitch = zone("pitch");
    const span = pitch.querySelector("span")!;
    start();
    for (let index = 0; index < 160; index += 1) {
      click(span, (index % 2) * 100, 0);
      vi.advanceTimersByTime(300);
    }
    vi.advanceTimersByTime(2000);
    expect(sent("click")).toHaveLength(150);
    move(`${MEMBER}/chips`);
    click(span, 0, 0);
    settle();
    expect(sent("click")).toHaveLength(151);
    expect(sent("click")[150]).toMatchObject({ tool: "chips" });
  });

  it("tells a waiting click at once when the page is unloaded", () => {
    const pitch = zone("pitch");
    start();
    click(pitch.querySelector("button")!, 10, 10);
    window.dispatchEvent(new Event("pagehide"));
    expect(sent("click")).toEqual([expect.objectContaining({ mark: "none" })]);
    settle();
    expect(sent("click")).toHaveLength(1);
  });
});

describe("how far down a page was read", () => {
  it("tells the deepest tenth seen and the stay's bucket once, on page hide", () => {
    page(2000, 500);
    start();
    scrollTo(700);
    scrollTo(0);
    vi.advanceTimersByTime(20_000);
    window.dispatchEvent(new Event("pagehide"));
    setProperty(document, "visibilityState", "hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(sent("scroll")).toEqual([
      expect.objectContaining({ depth: 60, dwell: "s30", page: "member", tool: "what-if" }),
    ]);
  });

  it("rounds down and stops at 100", () => {
    page(1000, 500);
    start();
    scrollTo(90);
    setProperty(document, "visibilityState", "hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(sent("scroll")[0]).toMatchObject({ depth: 50, dwell: "s5" });
    move("/fixtures");
    scrollTo(5000);
    window.dispatchEvent(new Event("pagehide"));
    expect(sent("scroll")[1]).toMatchObject({ depth: 100, page: "fixtures" });
  });

  it("tells the page that ends, for its own place, when the address moves", () => {
    page(2000, 1000);
    start(`${MEMBER}/llmopt`);
    scrollTo(1000);
    vi.advanceTimersByTime(65_000);
    move("/fixtures");
    expect(sent("scroll")).toEqual([
      expect.objectContaining({ depth: 100, dwell: "s180", page: "llmopt", tool: "llmopt" }),
    ]);
    move("/fixtures");
    expect(sent("scroll")).toHaveLength(1);
    window.dispatchEvent(new Event("pagehide"));
    expect(sent("scroll")[1]).toMatchObject({ page: "fixtures", dwell: "s5" });
  });

  it.each([
    [0, "s5"],
    [4999, "s5"],
    [5000, "s15"],
    [29_999, "s30"],
    [59_999, "s60"],
    [179_999, "s180"],
    [599_999, "s600"],
    [600_000, "long"],
  ])("a stay of %i ms is %s", (milliseconds, bucket) => {
    expect(behaviour.dwellBucket(milliseconds)).toBe(bucket);
  });
});

describe("errors", () => {
  function scriptError(message: string) {
    window.dispatchEvent(new ErrorEvent("error", { message, error: new Error(message) }));
  }
  function rejection(reason: unknown) {
    window.dispatchEvent(Object.assign(new Event("unhandledrejection"), { reason }));
  }

  it("tells the kind of each and never its message", () => {
    start();
    scriptError("secret 35249001 boom");
    rejection(new Error("secret rejection"));
    const failed = document.createElement("script");
    document.head.append(failed);
    failed.dispatchEvent(new Event("error"));
    failed.remove();
    expect(sent("error").map((event) => event.error)).toEqual(["script", "promise", "chunk"]);
    for (const [, body] of beacon.mock.calls) expect(body).not.toMatch(/secret|35249001|boom/);
  });

  it.each([
    "Failed to fetch dynamically imported module: https://squadopt/assets/Page-abc.js",
    "error loading dynamically imported module",
    "Importing a module script failed.",
    "Loading chunk 12 failed.",
    "Unable to preload CSS for /assets/Page.css",
  ])("is a chunk for: %s", (message) => {
    start();
    scriptError(message);
    vi.advanceTimersByTime(1000);
    rejection(new TypeError(message));
    expect(sent("error").map((event) => event.error)).toEqual(["chunk", "chunk"]);
  });

  it("takes a failed stylesheet or preload as a chunk, and leaves an image alone", () => {
    start();
    const link = document.createElement("link");
    document.head.append(link);
    link.dispatchEvent(new Event("error"));
    link.remove();
    const image = document.createElement("img");
    document.body.append(image);
    vi.advanceTimersByTime(1000);
    image.dispatchEvent(new Event("error"));
    expect(sent("error")).toEqual([expect.objectContaining({ error: "chunk" })]);
  });

  it("tells one of each kind a second and five a page view", () => {
    start();
    scriptError("a");
    scriptError("b");
    rejection("c");
    expect(sent("error")).toHaveLength(2);
    for (let second = 0; second < 6; second += 1) {
      vi.advanceTimersByTime(1000);
      scriptError("again");
    }
    expect(sent("error")).toHaveLength(5);
    move("/fixtures");
    scriptError("next page");
    expect(sent("error")).toHaveLength(6);
  });
});

describe("speed", () => {
  async function watched() {
    start();
    await vi.dynamicImportSettled();
    const vitals = await import("web-vitals");
    const callback = (watch: unknown) =>
      vi.mocked(watch as (report: (metric: object) => void) => void).mock.lastCall![0];
    return {
      lcp: callback(vitals.onLCP),
      inp: callback(vitals.onINP),
      cls: callback(vitals.onCLS),
      fcp: callback(vitals.onFCP),
      ttfb: callback(vitals.onTTFB),
    };
  }

  it("tells each measurement once, rounded, clamped and with the place it came at", async () => {
    const report = await watched();
    report.lcp({ name: "LCP", value: 2512.6, rating: "needs-improvement" });
    report.lcp({ name: "LCP", value: 3000, rating: "poor" });
    move("/fixtures");
    report.cls({ name: "CLS", value: 0.1234, rating: "needs-improvement" });
    report.inp({ name: "INP", value: 120, rating: "good" });
    report.fcp({ name: "FCP", value: 0.4, rating: "good" });
    report.ttfb({ name: "TTFB", value: 99_999, rating: "poor" });
    expect(sent("vital")).toEqual([
      expect.objectContaining({ metric: "lcp", rating: "needs", value: 2513, page: "member" }),
      expect.objectContaining({ metric: "cls", rating: "needs", value: 123, page: "fixtures" }),
      expect.objectContaining({ metric: "inp", rating: "good", value: 120 }),
      expect.objectContaining({ metric: "fcp", rating: "good", value: 0 }),
      expect.objectContaining({ metric: "ttfb", rating: "poor", value: 60_000 }),
    ]);
  });
});

describe("where a visit came from", () => {
  it.each([
    ["", "", "direct"],
    [`${ORIGIN}/league`, "", "internal"],
    ["https://wa.me/", "", "whatsapp"],
    ["https://web.whatsapp.com/", "", "whatsapp"],
    ["https://t.me/somechannel", "", "telegram"],
    ["https://web.telegram.org/", "", "telegram"],
    ["https://www.google.com/", "", "google"],
    ["https://www.google.com.tr/", "", "google"],
    ["https://www.bing.com/", "", "bing"],
    ["https://x.com/", "", "x"],
    ["https://t.co/abc", "", "x"],
    ["https://twitter.com/", "", "x"],
    ["https://l.instagram.com/", "", "instagram"],
    ["https://m.facebook.com/", "", "facebook"],
    ["https://fb.me/", "", "facebook"],
    ["https://old.reddit.com/r/FantasyPL", "", "reddit"],
    ["https://fantasy.premierleague.com/", "", "fpl"],
    ["https://www.premierleague.com/", "", "fpl"],
    ["https://example.com/", "", "other"],
    ["https://googleapis.example.com/", "", "other"],
    ["not an address", "", "other"],
    ["", "?utm_source=whatsapp", "whatsapp"],
    ["https://www.google.com/", "?utm_source=Telegram", "telegram"],
    ["", "?utm_source=newsletter", "other"],
    ["", "?utm_source=", "direct"],
  ])("%s with %s is %s", (referrer, search, source) => {
    expect(behaviour.arrivalSource(referrer, search, ORIGIN)).toBe(source);
  });

  it.each([
    [null, "new"],
    ["2026-W47", "same_week"],
    ["2026-W46", "last_week"],
    ["2026-W45", "weeks_2_4"],
    ["2026-W43", "weeks_2_4"],
    ["2026-W42", "older"],
    ["2025-W47", "older"],
    ["2026-W48", "unknown"],
    ["garbled", "unknown"],
  ])("a last visit in %s is %s", (stored, visit) => {
    expect(behaviour.visitBucket(stored, "2026-W47")).toBe(visit);
  });

  it("counts weeks across a year's end", () => {
    expect(behaviour.visitBucket("2026-W53", "2027-W01")).toBe("last_week");
    expect(behaviour.visitBucket("2025-W52", "2026-W01")).toBe("last_week");
  });

  it.each([
    [new Date(2026, 10, 16), "2026-W47"],
    [new Date(2026, 10, 22), "2026-W47"],
    [new Date(2027, 0, 1), "2026-W53"],
    [new Date(2024, 11, 30), "2025-W01"],
    [new Date(2021, 0, 3), "2020-W53"],
  ])("%s is in %s", (date, week) => {
    expect(behaviour.isoWeek(date)).toBe(week);
  });

  it("is told once a tab, with its first page, and keeps this week", () => {
    setProperty(document, "referrer", "https://wa.me/");
    localStorage.setItem(WEEK_KEY, "2026-W46");
    start("/fixtures?utm_source=nobody");
    expect(sent("arrival")).toEqual([
      expect.objectContaining({ source: "other", visit: "last_week", page: "fixtures" }),
    ]);
    expect(localStorage.getItem(WEEK_KEY)).toBe("2026-W47");
    expect(sessionStorage.getItem(ARRIVED_KEY)).not.toBeNull();
    behaviour.stopUsageBehaviour();
    start("/");
    expect(sent("arrival")).toHaveLength(1);
  });

  it("is a new visit on a device with no week kept", () => {
    start();
    expect(sent("arrival")[0]).toMatchObject({ source: "direct", visit: "new" });
  });

  it("is unknown where storage refuses, and still told once", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    start();
    behaviour.stopUsageBehaviour();
    start();
    expect(sent("arrival")).toEqual([expect.objectContaining({ visit: "unknown" })]);
  });
});

describe("a page that may not send", () => {
  it.each(["", "https://squadopt.example", `${ORIGIN}/some/path`])(
    "listens to nothing and sends nothing for %j",
    async (configured) => {
      vi.stubEnv("VITE_USAGE_ORIGIN", configured);
      const listening = vi.spyOn(document, "addEventListener");
      const windowListening = vi.spyOn(window, "addEventListener");
      const pitch = zone("pitch");
      start();
      click(pitch.querySelector("span")!, 1, 1);
      window.dispatchEvent(new ErrorEvent("error", { message: "x" }));
      window.dispatchEvent(new Event("pagehide"));
      settle();
      await vi.dynamicImportSettled();
      expect(listening).not.toHaveBeenCalled();
      expect(windowListening).not.toHaveBeenCalled();
      expect(beacon).not.toHaveBeenCalled();
      expect(sessionStorage.length).toBe(0);
      expect(localStorage.length).toBe(0);
    },
  );
});

describe("every event", () => {
  const COMMON = ["device", "kind", "lang", "page", "session", "tool", "v"];
  const FIELDS: Record<string, Record<string, readonly string[] | [number, number, number]>> = {
    click: {
      zone: [] as string[],
      cell: [0, 399, 1],
      target: [] as string[],
      mark: [] as string[],
    },
    scroll: { depth: [0, 100, 10], dwell: [] as string[] },
    vital: { metric: [] as string[], rating: [] as string[], value: [0, 60_000, 1] },
    error: { error: [] as string[] },
    arrival: { source: [] as string[], visit: [] as string[] },
  };

  it("carries only its kind's fields, words of the lists and integers in range, in 512 bytes", async () => {
    const words: Record<string, readonly string[]> = {
      zone: behaviour.USAGE_ZONES,
      target: behaviour.USAGE_TARGETS,
      mark: behaviour.USAGE_MARKS,
      dwell: behaviour.USAGE_DWELLS,
      metric: behaviour.USAGE_METRICS,
      rating: behaviour.USAGE_RATINGS,
      error: behaviour.USAGE_ERRORS,
      source: behaviour.USAGE_SOURCES,
      visit: behaviour.USAGE_VISITS,
    };
    setProperty(document, "referrer", "https://fantasy.premierleague.com/leagues/352490");
    for (const word of behaviour.USAGE_ZONES) zone(word);
    start(`/league/${LEAGUE}/members/${ENTRY}/current-squad?entry=${ENTRY}`);
    await vi.dynamicImportSettled();
    const vitals = await import("web-vitals");
    vi.mocked(vitals.onLCP).mock.lastCall![0]({
      name: "LCP",
      value: 1234,
      rating: "good",
    } as never);
    for (const [index, element] of [...document.querySelectorAll("[data-zone] span")].entries()) {
      click(element, (index % 2) * 100, 5);
      vi.advanceTimersByTime(300);
    }
    vi.advanceTimersByTime(2000);
    window.dispatchEvent(new ErrorEvent("error", { message: `entry ${ENTRY}` }));
    window.dispatchEvent(new Event("pagehide"));
    vi.advanceTimersByTime(2000);

    const events = sent();
    expect(new Set(events.map((event) => event.kind))).toEqual(
      new Set(["click", "scroll", "vital", "error", "arrival"]),
    );
    expect(new Set(sent("click").map((event) => event.zone))).toEqual(
      new Set(behaviour.USAGE_ZONES),
    );
    for (const [, body] of beacon.mock.calls) {
      expect(body.length).toBeLessThanOrEqual(512);
      expect(body).not.toContain(String(ENTRY));
      expect(body).not.toContain(String(LEAGUE));
    }
    for (const event of events) {
      const fields = FIELDS[event.kind as string]!;
      expect(Object.keys(event).sort()).toEqual([...COMMON, ...Object.keys(fields)].sort());
      expect(event).toMatchObject({ v: 2, page: "member", tool: "current-squad" });
      expect(event.session).toMatch(/^[0-9a-f]{16}$/);
      for (const [field, rule] of Object.entries(fields)) {
        const value = event[field];
        if (typeof rule[0] === "number") {
          const [low, high, step] = rule as [number, number, number];
          expect(Number.isInteger(value), field).toBe(true);
          expect(value as number).toBeGreaterThanOrEqual(low);
          expect(value as number).toBeLessThanOrEqual(high);
          expect((value as number) % step).toBe(0);
        } else {
          expect(words[field], field).toContain(value);
        }
      }
    }
  });
});

describe("a failure never reaches the page", () => {
  it("survives a beacon that throws and a box that cannot be read", () => {
    Object.defineProperty(navigator, "sendBeacon", {
      value: () => {
        throw new TypeError("refused");
      },
      configurable: true,
    });
    const pitch = zone("pitch");
    vi.spyOn(pitch, "getBoundingClientRect").mockImplementation(() => {
      throw new Error("detached");
    });
    expect(() => {
      start();
      click(pitch.querySelector("span")!, 1, 1);
      settle();
      window.dispatchEvent(new Event("pagehide"));
    }).not.toThrow();
  });

  it("installs once however often the address is told", () => {
    const listening = vi.spyOn(document, "addEventListener");
    start();
    behaviour.watchUsageBehaviour();
    move("/fixtures");
    expect(listening.mock.calls.filter(([type]) => type === "click")).toHaveLength(1);
    expect(sent("arrival")).toHaveLength(1);
  });
});

describe("the zones the components carry", () => {
  /** Every `data-zone` word in the site's components, with the tool pages' map and a card's. */
  function placed(): Set<string> {
    const found = new Set<string>();
    const visit = (directory: string) => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) visit(path);
        else if (entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx")) {
          const source = readFileSync(path, "utf8");
          for (const match of source.matchAll(/\b(?:data-zone|zone)="([^"]*)"/g)) {
            found.add(match[1]!);
          }
          const tools = /const TOOL_ZONES[^{]*\{([^}]*)\}/.exec(source);
          for (const match of tools?.[1]!.matchAll(/:\s*"([^"]*)"/g) ?? []) found.add(match[1]!);
        }
      }
    };
    visit(resolve(process.cwd(), "src"));
    return found;
  }

  it("are words of the list, and every word but the page is placed", () => {
    const words = placed();
    for (const word of words) expect(behaviour.USAGE_ZONES, word).toContain(word);
    for (const word of behaviour.USAGE_ZONES) {
      if (word !== "page") expect(words.has(word), word).toBe(true);
    }
  });
});
