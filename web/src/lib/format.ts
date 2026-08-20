/** Formatting only — the frontend never computes a number it shows, it formats one. */

export function pounds(tenths: number): string {
  const sign = tenths < 0 ? "-" : "";
  return `${sign}£${(Math.abs(tenths) / 10).toFixed(1)}m`;
}

export function points(value: number, digits = 1, locale = "en-GB"): string {
  return value.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function signedPoints(value: number, digits = 1, locale = "en-GB"): string {
  const text = points(Math.abs(value), digits, locale);
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

export function percent(probability: number, digits = 0, locale = "en-GB"): string {
  return `${points(probability * 100, digits, locale)}%`;
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

export function countdown(
  toIso: string,
  now: Date = new Date(),
  language: "tr" | "en" = "en",
): string {
  const target = new Date(toIso).getTime();
  if (Number.isNaN(target)) return "";
  const delta = Math.floor((target - now.getTime()) / 1000);
  if (delta <= 0) return language === "tr" ? "kapandı" : "closed";
  const days = Math.floor(delta / 86_400);
  const hours = Math.floor((delta % 86_400) / 3_600);
  const minutes = Math.floor((delta % 3_600) / 60);
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  return days > 0 ? `${days}${language === "tr" ? "g" : "d"} ${hh}:${mm}` : `${hh}:${mm}`;
}

export function shortDigest(value: string, length = 12): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}
