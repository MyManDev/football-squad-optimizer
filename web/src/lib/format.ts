/** Formatting only: the frontend never computes a number it shows, it formats one. */

export function pounds(tenths: number): string {
  const sign = tenths < 0 ? "-" : "";
  return `${sign}£${(Math.abs(tenths) / 10).toFixed(1)}m`;
}

const isTurkish = (locale: string) => locale.toLowerCase().startsWith("tr");

/**
 * Money the game publishes in tenths of a million, in the reader's own notation: Turkish
 * reads '0,8m' (comma decimal, no currency sign, as the league writes it), English reads
 * '£0.8m'. One decimal always, because a tenth is the unit the number was published in.
 */
export function money(tenths: number, locale = "en-GB"): string {
  const sign = tenths < 0 ? "-" : "";
  const value = (Math.abs(tenths) / 10).toLocaleString(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    useGrouping: false,
  });
  return isTurkish(locale) ? `${sign}${value}m` : `${sign}£${value}m`;
}

export function points(value: number, digits = 1, locale = "en-GB"): string {
  return value.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * A signed figure whose sign belongs to the number actually printed.
 *
 * The sign is taken after rounding to `digits`, not before. A value of -0.04 at one
 * decimal prints as zero, and a minus in front of a zero is a claim the digits do not
 * support: it reads as a loss the reader cannot see. Rounded to zero, it prints unsigned.
 */
export function signedPoints(value: number, digits = 1, locale = "en-GB"): string {
  const scale = 10 ** digits;
  const rounded = Math.round(value * scale) / scale;
  const text = points(Math.abs(rounded), digits, locale);
  return rounded > 0 ? `+${text}` : rounded < 0 ? `−${text}` : text;
}

export function percent(probability: number, digits = 0, locale = "en-GB"): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(probability);
}

export function utcShort(iso: string, locale = "en-GB"): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return (
    date.toLocaleString(locale, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      hour12: false,
    }) + " UTC"
  );
}

export function local(iso: string, locale = "en-GB"): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(locale, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The zone the league keeps its deadlines in, whatever zone the reader's device is set to. */
export const DEADLINE_TIME_ZONE = "Europe/Istanbul";

type DeadlineStyle = "long" | "short";

function deadlineParts(iso: string, locale: string, style: DeadlineStyle) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat(locale, {
    timeZone: DEADLINE_TIME_ZONE,
    weekday: style,
    day: "numeric",
    month: style,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return {
    weekday: part("weekday"),
    day: part("day"),
    month: part("month"),
    time: `${part("hour")}:${part("minute")}`,
  };
}

/**
 * A deadline in Istanbul time, written out: '10 Ekim Cumartesi · 13:00' in Turkish,
 * 'Saturday 10 October · 13:00' in English. An unreadable timestamp is returned as given.
 */
export function deadlineLong(iso: string, locale = "en-GB"): string {
  const parts = deadlineParts(iso, locale, "long");
  if (parts === null) return iso;
  const date = isTurkish(locale)
    ? `${parts.day} ${parts.month} ${parts.weekday}`
    : `${parts.weekday} ${parts.day} ${parts.month}`;
  return `${date} · ${parts.time}`;
}

/**
 * The same deadline for a narrow line: '10 Eki Cmt 13:00' in Turkish, 'Sat 10 Oct 13:00'
 * in English.
 */
export function deadlineShort(iso: string, locale = "en-GB"): string {
  const parts = deadlineParts(iso, locale, "short");
  if (parts === null) return iso;
  return isTurkish(locale)
    ? `${parts.day} ${parts.month} ${parts.weekday} ${parts.time}`
    : `${parts.weekday} ${parts.day} ${parts.month} ${parts.time}`;
}

export interface CountdownLabels {
  closed: string;
  day: string;
}

export interface CountdownResult {
  isClosed: boolean;
  text: string;
}

export function countdown(toIso: string, now: Date, labels: CountdownLabels): CountdownResult {
  const target = new Date(toIso).getTime();
  if (Number.isNaN(target)) return { isClosed: false, text: "" };
  const delta = Math.floor((target - now.getTime()) / 1000);
  if (delta <= 0) return { isClosed: true, text: labels.closed };
  const days = Math.floor(delta / 86_400);
  const hours = Math.floor((delta % 86_400) / 3_600);
  const minutes = Math.floor((delta % 3_600) / 60);
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  const text = days > 0 ? `${days}${labels.day} ${hh}:${mm}` : `${hh}:${mm}`;
  return { isClosed: false, text };
}

export function shortDigest(value: string, length = 12): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}
