/**
 * The league race card (#1135): one timeline with a rank change, the line brought forward
 * by a tap or by the member list with its gained and lost weeks marked, the gameweeks
 * stepped through with whose place changed, fifty members on fixed rows that never meet,
 * and the stylesheet's motion tokens and thumb-sized controls.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { withLeague } from "../../../testSupport/league";
import {
  RACE_SYSTEM,
  raceMember,
  raceScoreboard,
  raceWeek,
} from "../../../testSupport/raceScoreboard";
import type { ScoreboardState } from "../components/karne";
import { writeViewerEntry } from "../identity/useViewerEntry";
import { LeagueMembersView } from "../pages/LeagueMembersPage";
import type { EntryView } from "../types";
import { leagueRace } from "./leagueRace";
import { LeagueRaceCard, RACE_COLUMN, RACE_ROW } from "./LeagueRaceCard";

afterEach(cleanup);
beforeEach(() => writeViewerEntry(null));

const COPY = MESSAGES.tr.leagueMembers;
const MEMBERS = [raceMember(11), raceMember(22), raceMember(33), RACE_SYSTEM];
// Week 2: 22 overtakes 11; week 3: nobody moves.
const RACE = leagueRace(
  raceScoreboard([
    raceWeek(1, { 11: 70, 22: 60, 33: 50 }),
    raceWeek(2, { 11: 120, 22: 125, 33: 90 }),
    raceWeek(3, { 11: 180, 22: 185, 33: 140 }),
  ]),
  MEMBERS,
)!;

function show(initialEntry: number | null = null, language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <LeagueRaceCard race={RACE} members={MEMBERS} initialEntry={initialEntry} />
    </LanguageProvider>,
  );
}

const chart = () => screen.getByRole("img");
const highlightedEntry = (container: HTMLElement) =>
  Number(container.querySelector("[data-highlighted]")!.getAttribute("data-entry"));
const marks = (container: HTMLElement) =>
  [...container.querySelectorAll("circle")].map((mark) => mark.getAttribute("data-move"));
const step = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

describe("one timeline with a rank change", () => {
  it.each(["tr", "en"] as const)(
    "brings the viewer's line forward with the week the place was gained marked (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const { container } = show(22, language);
      expect(highlightedEntry(container)).toBe(22);
      expect(chart()).toHaveAccessibleName(copy.raceChart("M22"));
      // Second in week 1, first from week 2.
      expect(marks(container)).toEqual([null, "gained", null]);
      expect(container.textContent).not.toMatch(AS_A_CHANCE);
      expect(container.textContent).not.toMatch(AS_A_CAVEAT);
    },
  );

  it("lists whose place changed in the week stepped to, and says the first week has none before it", () => {
    const { container } = show(22);
    expect(screen.getByText(COPY.raceWeek(3))).toBeInTheDocument();
    expect(screen.getByText(COPY.raceNoMoves)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: COPY.raceNext })).toBeDisabled();
    step(COPY.racePrevious);
    expect(screen.getByText(COPY.raceWeek(2))).toBeInTheDocument();
    const moved = [...container.querySelectorAll("li[data-move]")].map((row) => [
      row.getAttribute("data-move"),
      row.textContent,
    ]);
    expect(moved).toEqual([
      ["gained", `${COPY.raceMove("M22", 2, 1)}+1`],
      ["lost", `${COPY.raceMove("M11", 1, 2)}−1`],
    ]);
    step(COPY.racePrevious);
    expect(screen.getByText(COPY.raceFirstWeek)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: COPY.racePrevious })).toBeDisabled();
  });

  it("moves the week's band to the gameweek stepped to", () => {
    const { container } = show();
    const band = () => (container.querySelector("rect") as SVGRectElement).style.transform;
    const last = band();
    step(COPY.racePrevious);
    expect(band()).not.toBe(last);
    expect(band()).toBe(`translateX(${32 + RACE_COLUMN}px)`);
  });
});

describe("bringing a line forward", () => {
  it("takes the line tapped, its marks and its row of places", () => {
    const { container } = show(22);
    fireEvent.click(container.querySelector('[data-entry="11"]')!);
    expect(highlightedEntry(container)).toBe(11);
    expect(marks(container)).toEqual([null, "lost", null]);
    const table = screen.getByRole("table", { name: "M11" });
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual([COPY.raceGameweek, COPY.racePlaces, COPY.racePoints]);
    expect(
      within(table)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["1", "2", "2", "70", "120", "180"]);
  });

  it("takes the member chosen from the list, and opens on the first place without one", () => {
    const { container } = show();
    expect(highlightedEntry(container)).toBe(22);
    fireEvent.change(screen.getByLabelText(COPY.raceMember), { target: { value: "33" } });
    expect(highlightedEntry(container)).toBe(33);
    expect(container.querySelector("svg g:last-of-type")).toHaveAttribute("data-entry", "33");
  });
});

describe("a league of fifty over a season", () => {
  const members: EntryView[] = Array.from({ length: 50 }, (_, index) => raceMember(100 + index));
  const weeks = Array.from({ length: 38 }, (_, gameweek) =>
    raceWeek(
      gameweek + 1,
      Object.fromEntries(
        members.map((member, index) => [
          member.entry_id!,
          (gameweek + 1) * 50 + ((index * 7 + gameweek * 3) % 50),
        ]),
      ),
    ),
  );
  const race = leagueRace(raceScoreboard(weeks), members)!;

  it("gives every place its own row and every week its own column, unscaled", () => {
    const { container } = render(
      <LanguageProvider initialLanguage="tr">
        <LeagueRaceCard race={race} members={members} />
      </LanguageProvider>,
    );
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).toBe(
      `0 0 ${svg.getAttribute("width")} ${svg.getAttribute("height")}`,
    );
    const rows = [...container.querySelectorAll("text[data-place]")].map((label) =>
      Number(label.getAttribute("y")),
    );
    expect(rows).toHaveLength(race.places);
    const gaps = rows.slice(1).map((value, index) => value - rows[index]!);
    expect(new Set(gaps)).toEqual(new Set([RACE_ROW]));
    expect(Number(svg.getAttribute("width"))).toBe(32 + 37 * RACE_COLUMN + 18);
  });
});

describe("the card's stylesheet", () => {
  const css = readFileSync(join(__dirname, "LeagueRaceCard.module.css"), "utf-8");
  const rule = (selector: string) =>
    css.match(
      new RegExp(`(?:^|\\n)${selector.replace(/[.[\]]/g, "\\$&")}\\s*\\{([^}]*)\\}`),
    )?.[1] ?? "";

  it("moves the week's band in the data time and a line's state in the card time", () => {
    expect(rule(".guide")).toMatch(
      /transition: transform var\(--motion-data\) var\(--motion-ease\)/,
    );
    expect(rule(".line")).toMatch(/transition: stroke var\(--motion-ui\) var\(--motion-ease\)/);
  });

  it("scrolls the chart inside itself, never the page, with thumb-sized controls", () => {
    expect(rule(".chart")).toMatch(/overflow-x: auto/);
    expect(rule(".step")).toMatch(/height: 44px/);
    expect(rule(".memberPick select")).toMatch(/min-height: 44px/);
  });
});

describe("on the league table page", () => {
  const humans = mockLeagueMembersEnvelope.payload.members.filter(
    (member) => member.member_kind === "human",
  );
  const totals = (base: number) =>
    Object.fromEntries(humans.map((member, index) => [member.entry_id!, base - index * 3]));
  const ready: ScoreboardState = {
    status: "ready",
    envelope: {
      ...mockLeagueMembersEnvelope,
      payload: raceScoreboard([raceWeek(1, totals(60)), raceWeek(2, totals(120))]),
    },
  };

  function page(scoreboard: ScoreboardState) {
    return render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={["/league/352490/members"]}>
          {withLeague(
            <LeagueMembersView envelope={mockLeagueMembersEnvelope} scoreboard={scoreboard} />,
          )}
        </MemoryRouter>
      </LanguageProvider>,
    );
  }

  it("draws the race under the table from the scoreboard the page reads", () => {
    page(ready);
    const race = screen.getByRole("region", { name: COPY.raceTitle });
    expect(within(race).getByRole("img")).toBeInTheDocument();
  });

  it("draws nothing while the scoreboard is missing", () => {
    page({ status: "missing" });
    expect(screen.queryByRole("region", { name: COPY.raceTitle })).toBeNull();
  });
});
