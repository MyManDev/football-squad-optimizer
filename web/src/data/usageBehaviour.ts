/**
 * How a visit behaves, told to the usage record as version 2 events (ADR 0015): where on a
 * page a click landed, as a zone and a cell of a 20 by 20 grid over it; how far down a page was
 * read and for how long, as buckets; the browser's speed measurements; which kind of error
 * met the visitor; and where the visit came from, with whether it comes back. Every text is
 * a word of a closed list below and every number an integer in a fixed range, so no address,
 * element text, form content, error message, referrer or position in pixels can leave.
 *
 * Components send nothing themselves: they carry a `data-zone` word, and this module listens
 * at the document. Nothing here can reach a page either: every handler swallows its own
 * failures, and a page that may not send (see `usageOrigin`) installs no listener at all.
 */
import {
  currentUsagePlace,
  deviceClass,
  sendUsage,
  sessionToken,
  usageLanguage,
  usageOrigin,
  type UsagePlace,
} from "./usage";

/** The parts of the site a click is told against, as `workers/usage/src/rules.js` lists them. */
export const USAGE_ZONES = [
  "nav",
  "nav-brand",
  "nav-member",
  "nav-links",
  "nav-settings",
  "phone-bar",
  "topbar",
  "entry-form",
  "league-list",
  "fpl-id-help",
  "member-table",
  "member-picker",
  "decision",
  "pitch",
  "squad",
  "fixtures-rail",
  "tool-tabs",
  "chip-timing",
  "chip-choice",
  "preferences",
  "advice-request",
  "advice-details",
  "what-if",
  "duel",
  "last-week",
  "apply-fpl",
  "resources",
  "coach-news",
  "new-information",
  "history",
  "history-header",
  "history-report",
  "history-picker",
  "history-table",
  "history-week",
  "vs",
  "vs-header",
  "vs-weeks",
  "vs-score",
  "vs-sides",
  "vs-why",
  "vs-squad",
  "live",
  "live-header",
  "live-score",
  "live-refresh",
  "live-rival",
  "live-differentials",
  "live-recap",
  "live-players",
  "llmopt",
  "llmopt-model",
  "llmopt-instructions",
  "llmopt-rule-list",
  "llmopt-rules",
  "llmopt-plan",
  "llmopt-compute",
  "llmopt-results",
  "reminder",
  "reminder-header",
  "reminder-switch",
  "reminder-steps",
  "fixtures",
  "fixtures-header",
  "fixtures-view",
  "fixtures-clubs",
  "fixtures-team",
  "fixtures-matrix",
  "contribute",
  "contribute-header",
  "contribute-team",
  "contribute-position",
  "contribute-player",
  "contribute-form",
  "contribute-comments",
  "page",
] as const;

export type UsageZone = (typeof USAGE_ZONES)[number];

/**
 * Words no component carries any more, kept in the list so an older tab's events are still
 * taken and the record's rows still read. On 2026-11-23 `nav` (the whole sidebar, as tall as
 * the window) gave way to `nav-brand`, `nav-member`, `nav-links` and `nav-settings`, and
 * `llmopt` (the whole page) to the `llmopt-` zones, because a large box's cells did not sit
 * on its controls. Later that day the other whole-page words (`history`, `vs`, `live`,
 * `reminder`, `fixtures`, `contribute`) gave way the same way to zones named after their page.
 * The heatmap mode draws a word only over an element that carries it, so these rows are
 * counted in the admin page and never drawn over the newer, smaller boxes.
 */
export const RETIRED_USAGE_ZONES: readonly UsageZone[] = [
  "nav",
  "llmopt",
  "history",
  "vs",
  "live",
  "reminder",
  "fixtures",
  "contribute",
];

/** The other closed lists of version 2, as the Worker keeps them. */
export const USAGE_KINDS = ["click", "scroll", "vital", "error", "arrival"] as const;
export const USAGE_TARGETS = ["control", "plain"] as const;
export const USAGE_MARKS = ["none", "rage", "dead"] as const;
export const USAGE_DWELLS = ["s5", "s15", "s30", "s60", "s180", "s600", "long"] as const;
export const USAGE_METRICS = ["lcp", "inp", "cls", "fcp", "ttfb"] as const;
export const USAGE_RATINGS = ["good", "needs", "poor"] as const;
export const USAGE_ERRORS = ["script", "promise", "chunk"] as const;
export const USAGE_SOURCES = [
  "direct",
  "internal",
  "whatsapp",
  "telegram",
  "google",
  "bing",
  "x",
  "instagram",
  "facebook",
  "reddit",
  "fpl",
  "other",
] as const;
export const USAGE_VISITS = [
  "new",
  "same_week",
  "last_week",
  "weeks_2_4",
  "older",
  "unknown",
] as const;

type UsageKind = (typeof USAGE_KINDS)[number];
type UsageError = (typeof USAGE_ERRORS)[number];
export type UsageSource = (typeof USAGE_SOURCES)[number];
export type UsageVisit = (typeof USAGE_VISITS)[number];

/** The cells a zone's box is cut into, along each side. */
const GRID = 20;
/** How long after a click the document is watched before the click is told. */
const CLICK_SETTLE_MS = 500;
/** A third click this soon after the first and this close to it makes a rage burst. */
const RAGE_WINDOW_MS = 800;
const RAGE_RADIUS_PX = 30;
const RAGE_CLICKS = 3;
/** A label passes its click on to its field at once; a click on that field this soon after is
 * the same click. */
const FORWARDED_MS = 100;
/** At most one click event this often, and this many a page view. */
const CLICK_GAP_MS = 250;
const CLICKS_PER_VIEW = 150;
/** At most this many error events a page view, and one of each kind this often. */
const ERRORS_PER_VIEW = 5;
const ERROR_GAP_MS = 1000;
/** A speed measurement above this is told as this. */
const MAX_VITAL = 60000;
/** The upper ends of the dwell buckets, in seconds; a longer stay is `long`. */
const DWELL_BUCKETS: [number, (typeof USAGE_DWELLS)[number]][] = [
  [5, "s5"],
  [15, "s15"],
  [30, "s30"],
  [60, "s60"],
  [180, "s180"],
  [600, "s600"],
];

const ARRIVED_KEY = "squadopt.usage.arrived";
export const VISIT_WEEK_KEY = "squadopt.usage.week";

const ZONES: ReadonlySet<string> = new Set(USAGE_ZONES);

/** A link, a button, a form field, a summary, a label or an element with one of those roles. */
const CONTROL = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  "label",
  ...["button", "link", "tab", "switch", "checkbox", "radio", "menuitem", "option"].map(
    (role) => `[role="${role}"]`,
  ),
].join(",");

/** A script or module that failed to load: the words browsers and Vite use for it. */
const CHUNK_MESSAGE =
  /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|loading (?:css )?chunk|unable to preload css/i;

/** One event of version 2: the common fields, then the kind's own. */
function sendBehaviour(
  kind: UsageKind,
  place: UsagePlace,
  fields: Record<string, string | number>,
): void {
  sendUsage(() => ({
    v: 2,
    kind,
    page: place.page,
    tool: place.tool,
    lang: usageLanguage(),
    device: deviceClass(),
    session: sessionToken(),
    ...fields,
  }));
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/** The zone a click names: the nearest ancestor with a known word, else the page. */
export function zoneOf(target: Element): { zone: UsageZone; element: Element | null } {
  let element = target.closest("[data-zone]");
  while (element !== null) {
    const word = element.getAttribute("data-zone") ?? "";
    if (ZONES.has(word)) {
      // `page` is always the whole document's grid, whichever element names it.
      return word === "page"
        ? { zone: "page", element: null }
        : { zone: word as UsageZone, element };
    }
    element = element.parentElement?.closest("[data-zone]") ?? null;
  }
  return { zone: "page", element: null };
}

/** The cell, row times 20 plus column, a point falls in over a box; outside points clamp. */
export function cellOf(
  x: number,
  y: number,
  box: { left: number; top: number; width: number; height: number },
): number {
  const along = (offset: number, size: number) =>
    size > 0 ? clamp(Math.floor((offset / size) * GRID), 0, GRID - 1) : 0;
  return along(y - box.top, box.height) * GRID + along(x - box.left, box.width);
}

/** Where a click landed in the viewport. A click from the keyboard lands nowhere; its target's
 * middle stands for it. */
function clickPoint(event: MouseEvent, target: Element): { x: number; y: number } {
  if (event.detail !== 0 || event.clientX !== 0 || event.clientY !== 0) {
    return { x: event.clientX, y: event.clientY };
  }
  const box = target.getBoundingClientRect();
  return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
}

/** The click's cell over its zone, or over the whole document for `page`. */
function clickCell(x: number, y: number, zone: Element | null): number {
  if (zone !== null) return cellOf(x, y, zone.getBoundingClientRect());
  const root = document.documentElement;
  return cellOf(x + window.scrollX, y + window.scrollY, {
    left: 0,
    top: 0,
    width: root.scrollWidth,
    height: root.scrollHeight,
  });
}

export function dwellBucket(milliseconds: number): (typeof USAGE_DWELLS)[number] {
  const seconds = milliseconds / 1000;
  for (const [limit, bucket] of DWELL_BUCKETS) if (seconds < limit) return bucket;
  return "long";
}

/** The deepest share of the page in view now, in steps of 10. */
function depthNow(): number {
  const height = document.documentElement.scrollHeight;
  if (height <= 0) return 0;
  const seen = ((window.scrollY + window.innerHeight) / height) * 100;
  return clamp(Math.floor(seen / 10) * 10, 0, 100);
}

const isHost = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`);

/** The source a referrer's host names. */
function hostSource(host: string): UsageSource {
  const labels = host.split(".");
  if (labels.includes("whatsapp") || isHost(host, "wa.me")) return "whatsapp";
  if (labels.includes("telegram") || isHost(host, "t.me")) return "telegram";
  if (/(?:^|\.)google(?:\.[a-z]{2,3}){1,2}$/.test(host)) return "google";
  if (isHost(host, "bing.com")) return "bing";
  if (["x.com", "t.co", "twitter.com"].some((domain) => isHost(host, domain))) return "x";
  if (labels.includes("instagram")) return "instagram";
  if (labels.includes("facebook") || labels.includes("fb")) return "facebook";
  if (labels.includes("reddit")) return "reddit";
  if (isHost(host, "premierleague.com")) return "fpl";
  return "other";
}

/** The source a `utm_source` names; one outside the list is `other`, and never sent itself. */
const UTM_SOURCES: Record<string, UsageSource> = {
  whatsapp: "whatsapp",
  wa: "whatsapp",
  telegram: "telegram",
  tg: "telegram",
  google: "google",
  bing: "bing",
  x: "x",
  twitter: "x",
  instagram: "instagram",
  ig: "instagram",
  facebook: "facebook",
  fb: "facebook",
  reddit: "reddit",
  fpl: "fpl",
};

/**
 * Where a visit came from, as a word: a `utm_source` first, since a shared link opened from an
 * app often carries no referrer, then the referrer's host. Neither is sent.
 */
export function arrivalSource(referrer: string, search: string, origin: string): UsageSource {
  const utm = new URLSearchParams(search).get("utm_source")?.trim().toLowerCase() ?? "";
  if (utm !== "") return Object.hasOwn(UTM_SOURCES, utm) ? UTM_SOURCES[utm]! : "other";
  if (referrer === "") return "direct";
  let from: URL;
  try {
    from = new URL(referrer);
  } catch {
    return "other";
  }
  if (from.origin === origin) return "internal";
  return hostSource(from.hostname.toLowerCase());
}

/** A day's ISO week as `2026-W47`, read from its local date. */
export function isoWeek(date: Date): string {
  const day = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  // The Thursday of the same week names the week's year.
  day.setUTCDate(day.getUTCDate() + 3 - ((day.getUTCDay() + 6) % 7));
  const year = day.getUTCFullYear();
  const week = Math.ceil(((day.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 + 1) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

/** The Monday of an ISO week, in days since 1970, or null for a value of another shape. */
function weekMonday(week: string): number | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(week);
  if (match === null) return null;
  const year = Number(match[1]);
  const number = Number(match[2]);
  if (number < 1 || number > 53) return null;
  const january4 = Date.UTC(year, 0, 4) / 86_400_000;
  const weekday = (new Date(Date.UTC(year, 0, 4)).getUTCDay() + 6) % 7;
  return january4 - weekday + (number - 1) * 7;
}

/** Which bucket this visit is in, by the weeks since the last one's; a stored value is replaced. */
export function visitBucket(stored: string | null, now: string): UsageVisit {
  if (stored === null) return "new";
  const then = weekMonday(stored);
  const current = weekMonday(now);
  if (then === null || current === null) return "unknown";
  const weeks = Math.round((current - then) / 7);
  if (weeks < 0) return "unknown";
  if (weeks === 0) return "same_week";
  if (weeks === 1) return "last_week";
  if (weeks <= 4) return "weeks_2_4";
  return "older";
}

/** The visit's bucket from the week kept on the device, keeping this week in its place. */
function visitNow(): UsageVisit {
  const week = isoWeek(new Date());
  try {
    const bucket = visitBucket(window.localStorage.getItem(VISIT_WEEK_KEY), week);
    window.localStorage.setItem(VISIT_WEEK_KEY, week);
    return bucket;
  } catch {
    return "unknown";
  }
}

/** The arrival, once a tab: true the first time this tab asks. */
let arrivedUnstored = false;
function firstPageOfTab(): boolean {
  try {
    if (window.sessionStorage.getItem(ARRIVED_KEY) !== null) return false;
    window.sessionStorage.setItem(ARRIVED_KEY, "1");
    return true;
  } catch {
    // Storage refuses: the session token lasts as long as the page, and so does this.
    if (arrivedUnstored) return false;
    arrivedUnstored = true;
    return true;
  }
}

/** Whether an error's text says a script or module failed to load. */
function isChunkMessage(reason: unknown): boolean {
  const text =
    reason instanceof Error
      ? `${reason.name} ${reason.message}`
      : typeof reason === "string"
        ? reason
        : "";
  return CHUNK_MESSAGE.test(text);
}

interface PendingClick {
  at: number;
  path: string;
  place: UsagePlace;
  zone: UsageZone;
  cell: number;
  target: "control" | "plain";
  /** Still inside its half second, watching the document. */
  open: boolean;
  /** The document changed, the address moved or the page went away while it was open. */
  changed: boolean;
  burst: Burst;
}

interface Burst {
  at: number;
  x: number;
  y: number;
  clicks: PendingClick[];
  rage: boolean;
}

/** One page view: what is counted and capped until the address moves. */
interface PageView {
  path: string;
  place: UsagePlace;
  start: number;
  depth: number;
  scrollSent: boolean;
  clicks: number;
  errors: number;
}

let uninstall: (() => void) | null = null;

/**
 * Starts listening, once per page; a later call names the address the router reached, and a
 * new address is a new page view. Does nothing where the page may not send.
 */
export function watchUsageBehaviour(): void {
  try {
    if (uninstall !== null) {
      notePath();
      return;
    }
    if (usageOrigin() === null) return;
    uninstall = install();
  } catch {
    // Behaviour that cannot be watched is behaviour not counted.
  }
}

/** Stops listening and forgets the page view; for tests. */
export function stopUsageBehaviour(): void {
  try {
    uninstall?.();
  } finally {
    uninstall = null;
  }
}

let notePath: () => void = () => {};

function install(): () => void {
  const listeners: [EventTarget, string, EventListener, AddEventListenerOptions][] = [];
  const timers = new Set<ReturnType<typeof setTimeout>>();
  let active = true;

  /** Adds a listener whose failures stay here. */
  const listen = <E extends Event>(
    target: EventTarget,
    type: string,
    handler: (event: E) => void,
    options: AddEventListenerOptions = {},
  ) => {
    const safe = (event: Event) => {
      try {
        if (active) handler(event as E);
      } catch {
        // Nothing here may reach the page.
      }
    };
    target.addEventListener(type, safe, options);
    listeners.push([target, type, safe, options]);
  };
  const later = (delay: number, run: () => void) => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      try {
        if (active) run();
      } catch {
        // As above.
      }
    }, delay);
    timers.add(timer);
  };

  const newView = (): PageView => ({
    path: window.location.pathname,
    place: currentUsagePlace(),
    start: Date.now(),
    depth: 0,
    scrollSent: false,
    clicks: 0,
    errors: 0,
  });
  let view = newView();

  // Scroll: the deepest share seen, told once a page view.
  const sampleDepth = () => {
    if (window.location.pathname === view.path) view.depth = Math.max(view.depth, depthNow());
  };
  const sendScroll = (sample: boolean) => {
    if (view.scrollSent) return;
    view.scrollSent = true;
    if (sample) sampleDepth();
    sendBehaviour("scroll", view.place, {
      depth: view.depth,
      dwell: dwellBucket(Date.now() - view.start),
    });
  };

  // Clicks: decided half a second after each, one rage event for a burst.
  const pending = new Set<PendingClick>();
  let burst: Burst | null = null;
  let lastClickSent = Number.NEGATIVE_INFINITY;
  let forwardedTo: Element | null = null;
  let forwardedAt = Number.NEGATIVE_INFINITY;
  const observer =
    typeof MutationObserver === "function"
      ? new MutationObserver(() => {
          for (const click of pending) if (click.open) click.changed = true;
        })
      : null;
  let observing = false;
  const watchDocument = (on: boolean) => {
    if (observer === null || observing === on) return;
    observing = on;
    if (on) {
      observer.observe(document, {
        subtree: true,
        childList: true,
        attributes: true,
        characterData: true,
      });
    } else {
      observer.disconnect();
    }
  };
  const sendClick = (click: PendingClick, mark: (typeof USAGE_MARKS)[number]) => {
    const now = Date.now();
    if (now - lastClickSent < CLICK_GAP_MS) return;
    // A click that moved the address counts against the page it was made on.
    const counted = click.path === view.path ? view : null;
    if (counted !== null && counted.clicks >= CLICKS_PER_VIEW) return;
    lastClickSent = now;
    if (counted !== null) counted.clicks += 1;
    sendBehaviour("click", click.place, {
      zone: click.zone,
      cell: click.cell,
      target: click.target,
      mark,
    });
  };
  const decide = (click: PendingClick) => {
    if (!pending.delete(click)) return;
    const { burst } = click;
    if (burst.rage) {
      // The burst's third click tells the rage, for the burst's first click's place.
      const first = burst.clicks[0]!;
      if (click === burst.clicks[RAGE_CLICKS - 1]) sendClick(first, "rage");
      return;
    }
    sendClick(click, click.changed ? "none" : "dead");
  };
  const settle = (click: PendingClick) => {
    if (!pending.has(click)) return;
    if (observer !== null && observer.takeRecords().length > 0) {
      for (const open of pending) if (open.open) open.changed = true;
    }
    click.open = false;
    if (window.location.pathname !== click.path) click.changed = true;
    if (![...pending].some((other) => other.open)) watchDocument(false);
    // A burst still open may yet turn to rage; its clicks wait for it to close.
    const closes = click.burst.at + RAGE_WINDOW_MS;
    const now = Date.now();
    if (!click.burst.rage && click.burst.clicks.length < RAGE_CLICKS && now < closes) {
      later(closes - now, () => decide(click));
    } else {
      decide(click);
    }
  };
  const onClick = (event: MouseEvent) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const now = Date.now();
    if (target === forwardedTo && now - forwardedAt < FORWARDED_MS) {
      forwardedTo = null;
      return;
    }
    const label = target.closest("label");
    const field = label?.control ?? null;
    forwardedTo = field !== null && !field.contains(target) ? field : null;
    forwardedAt = now;
    sampleDepth();
    const { x, y } = clickPoint(event, target);
    const joins =
      burst !== null &&
      !burst.rage &&
      now - burst.at <= RAGE_WINDOW_MS &&
      Math.hypot(x - burst.x, y - burst.y) <= RAGE_RADIUS_PX;
    if (burst !== null && burst.rage && now - burst.at <= RAGE_WINDOW_MS) {
      // A click after the rage, inside its window and radius, belongs to the same burst.
      if (Math.hypot(x - burst.x, y - burst.y) <= RAGE_RADIUS_PX) return;
    }
    if (!joins) burst = { at: now, x, y, clicks: [], rage: false };
    const { zone, element } = zoneOf(target);
    const click: PendingClick = {
      at: now,
      path: window.location.pathname,
      place: currentUsagePlace(),
      zone,
      cell: clickCell(x, y, element),
      target: target.closest(CONTROL) !== null ? "control" : "plain",
      open: true,
      changed: false,
      burst: burst!,
    };
    burst!.clicks.push(click);
    if (burst!.clicks.length === RAGE_CLICKS) burst!.rage = true;
    pending.add(click);
    watchDocument(true);
    later(CLICK_SETTLE_MS, () => settle(click));
  };

  // Errors: the kind only, capped.
  const lastErrorSent: Record<UsageError, number> = {
    script: Number.NEGATIVE_INFINITY,
    promise: Number.NEGATIVE_INFINITY,
    chunk: Number.NEGATIVE_INFINITY,
  };
  const sendError = (error: UsageError) => {
    const now = Date.now();
    if (view.errors >= ERRORS_PER_VIEW || now - lastErrorSent[error] < ERROR_GAP_MS) return;
    view.errors += 1;
    lastErrorSent[error] = now;
    sendBehaviour("error", view.place, { error });
  };
  const onError = (event: Event) => {
    const target = event.target;
    if (target instanceof Element) {
      // A resource that failed: a script or a stylesheet or module preload is a chunk.
      if (target.tagName === "SCRIPT" || target.tagName === "LINK") sendError("chunk");
      return;
    }
    const error = event as ErrorEvent;
    sendError(isChunkMessage(error.error) || isChunkMessage(error.message) ? "chunk" : "script");
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    sendError(isChunkMessage(event.reason) ? "chunk" : "promise");
  };

  // Leaving: the scroll, and the clicks still waiting, which plainly were not dead. A hidden
  // tab's timers still run; a page being unloaded tells its clicks at once.
  const onLeave = (unloading: boolean) => {
    for (const click of pending) click.changed = true;
    if (unloading) {
      for (const click of [...pending]) {
        click.open = false;
        decide(click);
      }
      watchDocument(false);
    }
    sendScroll(true);
  };

  listen(document, "click", onClick, { capture: true });
  listen(window, "scroll", sampleDepth, { passive: true });
  listen(window, "pagehide", () => onLeave(true));
  listen(document, "visibilitychange", () => {
    if (document.visibilityState === "hidden") onLeave(false);
  });
  listen(window, "pageshow", (event: PageTransitionEvent) => {
    // A page brought back from the back-forward cache is a page view of its own.
    if (event.persisted) view = newView();
  });
  listen(window, "error", onError, { capture: true });
  listen(window, "unhandledrejection", onRejection);

  notePath = () => {
    if (!active || window.location.pathname === view.path) return;
    // The page view that ends is told for its own place, with the depth it reached.
    sendScroll(false);
    view = newView();
  };

  // Speed: the browser's measurements, once each a page load, for the place they come at.
  const reported = new Set<string>();
  void import("web-vitals")
    .then(({ onCLS, onFCP, onINP, onLCP, onTTFB }) => {
      const report = (metric: {
        name: string;
        value: number;
        rating: "good" | "needs-improvement" | "poor";
      }) => {
        try {
          if (!active || reported.has(metric.name)) return;
          reported.add(metric.name);
          const value = metric.name === "CLS" ? metric.value * 1000 : metric.value;
          sendBehaviour("vital", currentUsagePlace(), {
            metric: metric.name.toLowerCase(),
            rating: metric.rating === "needs-improvement" ? "needs" : metric.rating,
            value: clamp(Math.round(value), 0, MAX_VITAL),
          });
        } catch {
          // As above.
        }
      };
      for (const watch of [onLCP, onINP, onCLS, onFCP, onTTFB]) watch(report);
    })
    .catch(() => {
      // A measurement library that does not load measures nothing.
    });

  // Arrival: once a tab, with its first page.
  if (firstPageOfTab()) {
    sendBehaviour("arrival", view.place, {
      source: arrivalSource(document.referrer, window.location.search, window.location.origin),
      visit: visitNow(),
    });
  }

  return () => {
    active = false;
    for (const [target, type, handler, options] of listeners) {
      target.removeEventListener(type, handler, options);
    }
    for (const timer of timers) clearTimeout(timer);
    observer?.disconnect();
    notePath = () => {};
  };
}
