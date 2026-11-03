/** A kickoff's local day, as a fixture list prints it; an unreadable instant is printed as it is. */
export function fixtureDay(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

/** A kickoff's local time, as a fixture list prints it; an unreadable instant prints nothing. */
export function fixtureTime(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
}
