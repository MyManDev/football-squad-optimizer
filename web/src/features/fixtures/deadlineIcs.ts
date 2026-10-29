import type { FixtureGameweek, FixturesPayload } from "./types";

/** The words a calendar event carries, in the page's language. */
export interface CalendarWords {
  summary: (gameweek: number) => string;
  description: string;
}

/** Every gameweek whose deadline is still ahead of `now`, earliest first. */
export function futureDeadlines(gameweeks: readonly FixtureGameweek[], now = Date.now()) {
  return gameweeks
    .filter((week) => Date.parse(week.deadline_utc) > now)
    .sort((left, right) => left.gameweek - right.gameweek);
}

/** A moment in UTC as iCalendar writes it: 20261031T110000Z. */
function utc(time: number): string {
  return new Date(time).toISOString().replace(/\.\d{3}|[-:]/g, "");
}

/** A TEXT value: a backslash, a semicolon, a comma and a line break are escaped. */
function text(value: string): string {
  return value.replace(/[\\;,]/g, (char) => `\\${char}`).replace(/\r?\n/g, "\\n");
}

const octets = (char: string): number => {
  const point = char.codePointAt(0)!;
  return point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
};

/**
 * A content line folded at 75 octets, never inside a character. Each continuation line
 * begins with one space, which counts towards its 75.
 */
function fold(line: string): string {
  const parts: string[] = [];
  let part = "";
  let size = 0;
  for (const char of line) {
    const width = octets(char);
    if (size + width > (parts.length === 0 ? 75 : 74)) {
      parts.push(part);
      part = "";
      size = 0;
    }
    part += char;
    size += width;
  }
  parts.push(part);
  return parts.join("\r\n ");
}

/**
 * The upcoming deadlines of a published fixture list as an iCalendar file (RFC 5545).
 *
 * One event per gameweek whose deadline is after `now`: an instant at the deadline in UTC,
 * so a DTSTART with no DTEND (§3.6.1), with a display alarm two hours before. The UID is the
 * season and the gameweek, and the SEQUENCE is the build time in whole minutes since the
 * epoch, so it grows with every download: a calendar that honours both updates the event on
 * a second import instead of adding one. A moved deadline reaches the calendar only through
 * a new file; nothing here is a feed.
 */
export function deadlineIcs(
  payload: Pick<FixturesPayload, "season" | "gameweeks">,
  words: CalendarWords,
  now: number,
): string {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SquadOpt//FPL deadlines//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
  ];
  const sequence = Math.floor(now / 60_000);
  for (const week of futureDeadlines(payload.gameweeks, now)) {
    const summary = text(words.summary(week.gameweek));
    lines.push(
      "BEGIN:VEVENT",
      `UID:${text(`${payload.season}-gw${week.gameweek}-deadline@squadopt`)}`,
      `SEQUENCE:${sequence}`,
      `DTSTAMP:${utc(now)}`,
      `DTSTART:${utc(Date.parse(week.deadline_utc))}`,
      `SUMMARY:${summary}`,
      `DESCRIPTION:${text(words.description)}`,
      "BEGIN:VALARM",
      "ACTION:DISPLAY",
      `DESCRIPTION:${summary}`,
      "TRIGGER:-PT2H",
      "END:VALARM",
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}
