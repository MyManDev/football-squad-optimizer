/**
 * One step of a visit, told to the usage record (ADR 0014). The event names the kind of page
 * and the tool, never the address; the language; a class of device; and a random token that
 * joins one tab's steps and goes when the tab closes. No league or entry number, no name, no
 * cookie and no measurement of the device leave the browser.
 *
 * Nothing here can reach a page: every failure is swallowed, the beacon is queued by the
 * browser. A page sends only when `VITE_USAGE_ORIGIN` names its own origin: an empty value
 * (the default) sends nothing, and neither does a build with the variable set served from
 * anywhere else, such as a preview address or the end-to-end suite's local server.
 */
import { LANGUAGE_STORAGE_KEY } from "../i18n/LanguageProvider";
import { isMemberTool } from "../lib/leagueAddresses";

export type UsageStep = "open" | "tool" | "picker_shown" | "picker_claimed" | "device_solve";

/** The event's kind of page and tool, as `workers/usage/src/rules.js` lists them. */
export interface UsagePlace {
  page: string;
  tool: string;
}

const SESSION_KEY = "squadopt.usage.session";
const SESSION_SHAPE = /^[0-9a-f]{16}$/;

/** A touch screen whose short side is below this is a phone, in CSS pixels. */
const PHONE_SHORT_SIDE = 600;

const LEAGUE_ADDRESS = /^\/league(?:\/\d+)?(\/members(?:\/([^/]+)(?:\/([^/]+))?)?)?$/;

/** The kind of page and tool an address is, with the numbers in it left behind. */
export function usagePlace(pathname: string): UsagePlace {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/") return { page: "entry", tool: "" };
  if (path === "/fixtures") return { page: "fixtures", tool: "fixtures" };
  if (path === "/contribute") return { page: "contribute", tool: "" };
  if (/^\/entry\/[^/]+$/.test(path)) return { page: "team", tool: "week" };
  if (/^\/entry\/[^/]+\/live$/.test(path)) return { page: "team", tool: "live" };
  const league = LEAGUE_ADDRESS.exec(path);
  if (league === null) return { page: "other", tool: "" };
  const [, members, entry, last] = league;
  if (members === undefined) return { page: "league", tool: "" };
  if (entry === undefined) return { page: "members", tool: "" };
  if (last === undefined) return { page: "member", tool: "week" };
  if (last === "history" || last === "vs" || last === "live") return { page: last, tool: last };
  if (last === "reminder") return { page: "reminder", tool: "" };
  return isMemberTool(last) ? { page: "member", tool: last } : { page: "other", tool: "" };
}

/** The address under the site's base path. */
function currentAddress(): string {
  const base = import.meta.env.BASE_URL.replace(/\/+$/, "");
  const { pathname } = window.location;
  return base !== "" && pathname.startsWith(base) ? pathname.slice(base.length) : pathname;
}

/**
 * The language the provider starts from. Read from storage rather than the document, whose
 * `lang` the provider sets in an effect that runs after this first page's own.
 */
function usageLanguage(): "tr" | "en" {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "tr";
  } catch {
    return "tr";
  }
}

/** A phone or a tablet has a coarse main pointer; the screen's short side tells them apart. */
function deviceClass(): "phone" | "tablet" | "desktop" | "unknown" {
  if (typeof window.matchMedia !== "function") return "unknown";
  if (!window.matchMedia("(pointer: coarse)").matches) return "desktop";
  return Math.min(window.screen.width, window.screen.height) < PHONE_SHORT_SIDE
    ? "phone"
    : "tablet";
}

function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// For a tab whose storage refuses: the token then lasts as long as the page does.
let unstoredToken: string | null = null;

/** This tab's token, made on its first step. */
function sessionToken(): string {
  try {
    const kept = window.sessionStorage.getItem(SESSION_KEY);
    if (kept !== null && SESSION_SHAPE.test(kept)) return kept;
    const made = randomToken();
    window.sessionStorage.setItem(SESSION_KEY, made);
    return made;
  } catch {
    unstoredToken ??= randomToken();
    return unstoredToken;
  }
}

/** Tells the record a step was taken at the current address. Never throws. */
export function recordUsage({ step }: { step: UsageStep }): void {
  try {
    const origin = ((import.meta.env.VITE_USAGE_ORIGIN as string | undefined) ?? "").replace(
      /\/+$/,
      "",
    );
    // The Worker refuses every other origin, so a beacon from one could only log a failure.
    if (origin !== window.location.origin) return;
    // A string goes as text/plain, which a browser sends without asking a preflight first.
    navigator.sendBeacon(
      `${origin}/api/v1/usage/events`,
      JSON.stringify({
        ...usagePlace(currentAddress()),
        step,
        lang: usageLanguage(),
        device: deviceClass(),
        session: sessionToken(),
        v: 1,
      }),
    );
  } catch {
    // A step that cannot be told is a step not counted.
  }
}
