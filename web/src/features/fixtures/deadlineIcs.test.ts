import { describe, expect, it } from "vitest";

import { deadlineIcs, futureDeadlines, type CalendarWords } from "./deadlineIcs";
import type { FixtureGameweek } from "./types";

const NOW = Date.parse("2026-10-28T09:15:42.123Z");

const week = (gameweek: number, deadline_utc: string): FixtureGameweek => ({
  gameweek,
  deadline_utc,
  fixtures: [],
});

/** Gameweek 8 has passed; 10 is listed before 9, as no producer promises an order. */
const payload = {
  season: "2026-27",
  gameweeks: [
    week(8, "2026-10-23T17:30:00Z"),
    week(10, "2026-11-06T18:30:00Z"),
    week(9, "2026-10-31T11:00:00Z"),
  ],
};

const words: CalendarWords = {
  summary: (gameweek) => `FPL GW${gameweek} deadline`,
  description: "Open SquadOpt before the deadline: https://example.org/",
};

const event = (gameweek: number, start: string) => [
  "BEGIN:VEVENT",
  `UID:2026-27-gw${gameweek}-deadline@squadopt`,
  "SEQUENCE:29886315",
  "DTSTAMP:20261028T091542Z",
  `DTSTART:${start}`,
  `SUMMARY:FPL GW${gameweek} deadline`,
  "DESCRIPTION:Open SquadOpt before the deadline: https://example.org/",
  "BEGIN:VALARM",
  "ACTION:DISPLAY",
  `DESCRIPTION:FPL GW${gameweek} deadline`,
  "TRIGGER:-PT2H",
  "END:VALARM",
  "END:VEVENT",
];

describe("the deadline calendar", () => {
  it("writes each deadline ahead, earliest first, with its alarm, in CRLF lines", () => {
    expect(deadlineIcs(payload, words, NOW)).toBe(
      [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SquadOpt//FPL deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        ...event(9, "20261031T110000Z"),
        ...event(10, "20261106T183000Z"),
        "END:VCALENDAR",
        "",
      ].join("\r\n"),
    );
  });

  it("leaves out a deadline that has passed, is now or cannot be read", () => {
    const weeks = [
      week(1, "2026-10-28T09:15:42.123Z"),
      week(2, "?"),
      week(3, "2026-10-28T09:15:43Z"),
    ];
    expect(futureDeadlines(weeks, NOW).map((entry) => entry.gameweek)).toEqual([3]);
    // With none ahead the file is still a whole calendar, holding no event.
    expect(deadlineIcs(payload, words, Date.parse("2026-12-01"))).toBe(
      "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SquadOpt//FPL deadlines//EN\r\n" +
        "CALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\nEND:VCALENDAR\r\n",
    );
  });

  it("writes every time in UTC, from any offset, without milliseconds", () => {
    const file = deadlineIcs(
      { season: "2026-27", gameweeks: [week(9, "2026-10-31T13:00:00.500+02:00")] },
      words,
      Date.parse("2026-10-28T10:00:00+01:00"),
    );
    expect(file).toContain("\r\nDTSTAMP:20261028T090000Z\r\nDTSTART:20261031T110000Z\r\n");
    // A deadline is an instant: DTSTART alone, with neither DTEND nor DURATION (§3.6.1).
    expect(file).not.toMatch(/^(DTEND|DURATION)[:;]/m);
  });

  it("numbers each download in whole minutes, the same for every event of one file", () => {
    const sequences = (now: number) => deadlineIcs(payload, words, now).match(/^SEQUENCE:.*$/gm);
    expect(sequences(NOW)).toEqual(["SEQUENCE:29886315", "SEQUENCE:29886315"]);
    expect(sequences(Date.parse("2026-10-28T09:15:59.999Z"))).toEqual(sequences(NOW));
    expect(sequences(Date.parse("2026-10-28T09:16:00Z"))?.[0]).toBe("SEQUENCE:29886316");
  });

  it("keeps one UID per season and gameweek, whatever the language or the moment", () => {
    const uids = (file: string) => file.match(/^UID:.*$/gm);
    const turkish = { ...words, summary: (gameweek: number) => `FPL ${gameweek}. hafta` };
    expect(uids(deadlineIcs(payload, turkish, NOW + 86_400_000))).toEqual(
      uids(deadlineIcs(payload, words, NOW)),
    );
    expect(uids(deadlineIcs({ ...payload, season: "2027-28" }, words, NOW))?.[0]).toBe(
      "UID:2027-28-gw9-deadline@squadopt",
    );
  });

  it("escapes a backslash, a semicolon, a comma and a line break in text", () => {
    const file = deadlineIcs(payload, { summary: () => "A, B; C\\D", description: "1\n2" }, NOW);
    expect(file).toContain("\r\nSUMMARY:A\\, B\\; C\\\\D\r\nDESCRIPTION:1\\n2\r\n");
    expect(file).toContain("\r\nDESCRIPTION:A\\, B\\; C\\\\D\r\nTRIGGER");
  });

  it("folds a line at 75 octets, never inside a character", () => {
    // "SUMMARY:" is eight octets: 75 stay on one line, the 76th starts the next.
    const at = (summary: string) => deadlineIcs(payload, { ...words, summary: () => summary }, NOW);
    expect(at("x".repeat(67))).toContain(`\r\nSUMMARY:${"x".repeat(67)}\r\nDESCRIPTION`);
    expect(at("x".repeat(68))).toContain(`\r\nSUMMARY:${"x".repeat(67)}\r\n x\r\nDESCRIPTION`);
    // A two-octet letter that would end at octet 76 moves whole to the next line.
    expect(at(`${"x".repeat(66)}ş`)).toContain(`\r\nSUMMARY:${"x".repeat(66)}\r\n ş\r\n`);

    const description = `Deadline'dan önce SquadOpt'u açın: https://example.org/${"ğüşıöç".repeat(12)}`;
    const lines = deadlineIcs(payload, { ...words, description }, NOW).split("\r\n");
    expect(lines.filter((line) => line.startsWith(" ")).length).toBeGreaterThan(2);
    for (const line of lines) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
    expect(lines.join("\r\n").replace(/\r\n /g, "")).toContain(
      `\r\nDESCRIPTION:${description}\r\n`,
    );
  });
});
