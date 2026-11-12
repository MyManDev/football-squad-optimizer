/**
 * The LIVE page's values, in the reader's own time and notation: a kickoff as its weekday
 * and time ('Cmt 15:00', 'Sat 15:00'), a read's time ('15:42'), and whole points with the
 * sign of the number printed ('+8', '−12'). `timeZone` is for tests.
 */

import { signedPoints } from "../../../lib/format";

function parts(iso: string, locale: string, timeZone?: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const found = new Intl.DateTimeFormat(locale, {
    timeZone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    found.find((entry) => entry.type === type)?.value ?? "";
  return { weekday: part("weekday"), time: `${part("hour")}:${part("minute")}` };
}

/** A kickoff: 'Cmt 15:00' in Turkish, 'Sat 15:00' in English; an unreadable one as given. */
export function kickoffShort(iso: string, locale: string, timeZone?: string): string {
  const found = parts(iso, locale, timeZone);
  return found === null ? iso : `${found.weekday} ${found.time}`;
}

/** A read's time of day: '15:42'. */
export function clockTime(iso: string, locale: string, timeZone?: string): string {
  return parts(iso, locale, timeZone)?.time ?? iso;
}

/** Whole points, a negative one with the minus sign the signed figures print: '47', '−1'. */
export function wholePoints(value: number, locale: string): string {
  const text = Math.abs(value).toLocaleString(locale, { maximumFractionDigits: 0 });
  return value < 0 ? `−${text}` : text;
}

/** A figure caught in the middle of its count: rounded first, so passing zero writes '0'. */
export function countedWhole(value: number, locale: string): string {
  return wholePoints(Math.round(value), locale);
}

/** Whole points with their sign: '+8', '−12', '0'. */
export function signedWhole(value: number, locale: string): string {
  return signedPoints(value, 0, locale);
}
