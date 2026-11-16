/// <reference types="node" />
/**
 * The usage event as it leaves the browser: only when the build names this page's own
 * origin, only words of the Worker's lists, nothing of the address, and never an error for
 * the page.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LANGUAGE_STORAGE_KEY } from "../i18n/LanguageProvider";
import { MEMBER_TOOLS } from "../lib/leagueAddresses";
import { recordUsage, sendUsage, usagePlace, type UsagePlace, type UsageStep } from "./usage";
import { isUsageAdmin, markUsageAdmin, USAGE_ADMIN_KEY } from "./usageAdminFlag";
import {
  USAGE_DWELLS,
  USAGE_ERRORS,
  USAGE_KINDS,
  USAGE_MARKS,
  USAGE_METRICS,
  USAGE_RATINGS,
  USAGE_SOURCES,
  USAGE_TARGETS,
  USAGE_VISITS,
  USAGE_ZONES,
} from "./usageBehaviour";

const ORIGIN = window.location.origin;
const LEAGUE = 352490;
const ENTRY = 35249001;
const SESSION_KEY = "squadopt.usage.session";
const ADDRESS = `/league/${LEAGUE}/members/${ENTRY}/what-if`;

const beacon = vi.fn<(url: string, body: string) => boolean>();

function pointer(coarse: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: coarse && query.includes("coarse") }));
}

function screenOf(width: number, height: number) {
  vi.spyOn(window.screen, "width", "get").mockReturnValue(width);
  vi.spyOn(window.screen, "height", "get").mockReturnValue(height);
}

const sent = (call = 0) => JSON.parse(beacon.mock.calls[call]![1]) as Record<string, unknown>;

beforeEach(() => {
  beacon.mockReset();
  beacon.mockReturnValue(true);
  Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
  vi.stubEnv("VITE_USAGE_ORIGIN", ORIGIN);
  pointer(false);
  window.history.pushState({}, "", ADDRESS);
  localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  localStorage.removeItem(USAGE_ADMIN_KEY);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "sendBeacon");
  window.history.pushState({}, "", "/");
});

describe("what is sent", () => {
  it("sends nothing when the build names no origin", () => {
    vi.stubEnv("VITE_USAGE_ORIGIN", "");
    recordUsage({ step: "open" });
    expect(beacon).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it.each(["https://squadopt.example", "not an origin", `${ORIGIN}/some/path`])(
    "sends nothing from a page on another origin than the build names: %s",
    (configured) => {
      vi.stubEnv("VITE_USAGE_ORIGIN", configured);
      recordUsage({ step: "open" });
      expect(beacon).not.toHaveBeenCalled();
      expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    },
  );

  it("posts the event to the origin's route, as a string", () => {
    vi.stubEnv("VITE_USAGE_ORIGIN", `${ORIGIN}/`);
    recordUsage({ step: "tool" });
    expect(beacon.mock.calls[0]![0]).toBe(`${ORIGIN}/api/v1/usage/events`);
    expect(typeof beacon.mock.calls[0]![1]).toBe("string");
    expect(sent()).toEqual({
      page: "member",
      tool: "what-if",
      step: "tool",
      lang: "tr",
      device: "desktop",
      session: expect.stringMatching(/^[0-9a-f]{16}$/),
      v: 1,
    });
  });

  it("carries no league number, entry number or address", () => {
    recordUsage({ step: "picker_claimed" });
    const body = beacon.mock.calls[0]![1];
    for (const secret of [String(LEAGUE), String(ENTRY), "/league"]) {
      expect(body).not.toContain(secret);
    }
  });

  it("keeps one token per tab and makes another for a new one", () => {
    recordUsage({ step: "open" });
    recordUsage({ step: "tool" });
    expect(sent(0).session).toBe(sent(1).session);
    expect(sessionStorage.getItem(SESSION_KEY)).toBe(sent(0).session);
    sessionStorage.clear();
    recordUsage({ step: "open" });
    expect(sent(2).session).not.toBe(sent(0).session);
  });

  it("reads the language the provider will start from", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    recordUsage({ step: "open" });
    expect(sent().lang).toBe("en");
  });
});

describe("the device class", () => {
  it("is desktop for a fine pointer, whatever the screen", () => {
    screenOf(390, 844);
    recordUsage({ step: "open" });
    expect(sent().device).toBe("desktop");
  });

  it("tells a phone from a tablet by the short side, in either orientation", () => {
    pointer(true);
    screenOf(844, 390);
    recordUsage({ step: "open" });
    expect(sent(0).device).toBe("phone");
    vi.mocked(Object.getOwnPropertyDescriptor(window.screen, "width")!.get!).mockReturnValue(1024);
    vi.mocked(Object.getOwnPropertyDescriptor(window.screen, "height")!.get!).mockReturnValue(768);
    recordUsage({ step: "open" });
    expect(sent(1).device).toBe("tablet");
  });

  it("is unknown where the browser cannot say", () => {
    vi.stubGlobal("matchMedia", undefined);
    recordUsage({ step: "open" });
    expect(sent().device).toBe("unknown");
  });
});

describe("a failure never reaches the page", () => {
  it("survives a browser with no beacon, and one that throws", () => {
    Reflect.deleteProperty(navigator, "sendBeacon");
    expect(() => recordUsage({ step: "open" })).not.toThrow();
    Object.defineProperty(navigator, "sendBeacon", {
      value: () => {
        throw new TypeError("refused");
      },
      configurable: true,
    });
    expect(() => recordUsage({ step: "open" })).not.toThrow();
  });

  it("still counts the step, with a steady token, where storage refuses", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    recordUsage({ step: "open" });
    recordUsage({ step: "tool" });
    expect(sent(0).session).toMatch(/^[0-9a-f]{16}$/);
    expect(sent(1).session).toBe(sent(0).session);
    expect(sent(0).lang).toBe("tr");
  });
});

describe("an admin's browser (ADR 0016)", () => {
  it("is marked by the one value the admin page keeps", () => {
    expect(isUsageAdmin()).toBe(false);
    markUsageAdmin();
    expect(localStorage.getItem(USAGE_ADMIN_KEY)).toBe("1");
    expect(isUsageAdmin()).toBe(true);
    localStorage.setItem(USAGE_ADMIN_KEY, "yes");
    expect(isUsageAdmin()).toBe(false);
  });

  it("sends no event of either version, and makes no token", () => {
    markUsageAdmin();
    const event = vi.fn(() => ({ v: 2, kind: "click" }));
    recordUsage({ step: "open" });
    sendUsage(event);
    expect(beacon).not.toHaveBeenCalled();
    expect(event).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it("sends again once the mark is gone", () => {
    markUsageAdmin();
    recordUsage({ step: "open" });
    localStorage.removeItem(USAGE_ADMIN_KEY);
    recordUsage({ step: "open" });
    sendUsage(() => ({ v: 2, kind: "error", error: "script" }));
    expect(beacon).toHaveBeenCalledTimes(2);
    expect(sent(1)).toMatchObject({ v: 2, kind: "error" });
  });

  it("never throws where storage refuses, and is then a counted visitor", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(() => markUsageAdmin()).not.toThrow();
    expect(isUsageAdmin()).toBe(false);
    recordUsage({ step: "open" });
    expect(beacon).toHaveBeenCalledTimes(1);
  });
});

/** Every address the router has, with the place it should read as. */
const member = `/league/${LEAGUE}/members/${ENTRY}`;
const PLACES: [string, UsagePlace][] = [
  ["/", { page: "entry", tool: "" }],
  [`/entry/${ENTRY}`, { page: "team", tool: "week" }],
  [`/entry/${ENTRY}/live`, { page: "team", tool: "live" }],
  [`/entry/${ENTRY}/llmopt`, { page: "llmopt", tool: "llmopt" }],
  ["/fixtures", { page: "fixtures", tool: "fixtures" }],
  ["/contribute", { page: "contribute", tool: "" }],
  ["/league", { page: "league", tool: "" }],
  [`/league/${LEAGUE}`, { page: "league", tool: "" }],
  ["/league/members", { page: "members", tool: "" }],
  [`/league/${LEAGUE}/members`, { page: "members", tool: "" }],
  [`/league/${LEAGUE}/members/`, { page: "members", tool: "" }],
  [`/league/members/${ENTRY}`, { page: "member", tool: "week" }],
  [member, { page: "member", tool: "week" }],
  ...MEMBER_TOOLS.map((tool): [string, UsagePlace] => [
    `${member}/${tool}`,
    { page: "member", tool },
  ]),
  [`${member}/history`, { page: "history", tool: "history" }],
  [`${member}/vs`, { page: "vs", tool: "vs" }],
  [`${member}/live`, { page: "live", tool: "live" }],
  [`/league/members/${ENTRY}/live`, { page: "live", tool: "live" }],
  [`${member}/llmopt`, { page: "llmopt", tool: "llmopt" }],
  [`/league/members/${ENTRY}/llmopt`, { page: "llmopt", tool: "llmopt" }],
  [`${member}/reminder`, { page: "reminder", tool: "" }],
  [`${member}/nothing`, { page: "other", tool: "" }],
  [`/nothing/${ENTRY}`, { page: "other", tool: "" }],
];

describe("the kind of page an address is", () => {
  it.each(PLACES)("%s", (address, place) => {
    expect(usagePlace(address)).toEqual(place);
  });
});

const WORKER_RULES = resolve(process.cwd(), "../workers/usage/src/rules.js");

describe.runIf(existsSync(WORKER_RULES))("the Worker's lists", () => {
  const STEPS: UsageStep[] = ["open", "tool", "picker_shown", "picker_claimed", "device_solve"];
  const words = (list: Iterable<string>) => [...new Set(list)].sort();
  const worker = (name: string) => {
    const source = readFileSync(WORKER_RULES, "utf8");
    const list = new RegExp(`export const ${name} = new Set\\(\\[([^\\]]*)\\]\\)`).exec(source);
    expect(list, name).not.toBeNull();
    return words([...list![1]!.matchAll(/"([^"]*)"/g)].map((match) => match[1]!));
  };

  // A word only one side knows is an event refused and never seen, so both directions count.
  it("are exactly the words this module can send", () => {
    expect(words(PLACES.map(([, place]) => place.page))).toEqual(worker("PAGES"));
    expect(words(PLACES.map(([, place]) => place.tool))).toEqual(worker("TOOLS"));
    expect(words(STEPS)).toEqual(worker("STEPS"));
    expect(words(["tr", "en"])).toEqual(worker("LANGUAGES"));
    expect(words(["phone", "tablet", "desktop", "unknown"])).toEqual(worker("DEVICES"));
  });

  it("are exactly the words the behaviour module can send", () => {
    expect(words(USAGE_KINDS)).toEqual(worker("KINDS"));
    expect(words(USAGE_ZONES)).toEqual(worker("ZONES"));
    expect(words(USAGE_TARGETS)).toEqual(worker("TARGETS"));
    expect(words(USAGE_MARKS)).toEqual(worker("MARKS"));
    expect(words(USAGE_DWELLS)).toEqual(worker("DWELLS"));
    expect(words(USAGE_METRICS)).toEqual(worker("METRICS"));
    expect(words(USAGE_RATINGS)).toEqual(worker("RATINGS"));
    expect(words(USAGE_ERRORS)).toEqual(worker("ERRORS"));
    expect(words(USAGE_SOURCES)).toEqual(worker("SOURCES"));
    expect(words(USAGE_VISITS)).toEqual(worker("VISITS"));
  });
});
