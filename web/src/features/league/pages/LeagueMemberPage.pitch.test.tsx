/**
 * Direction D's squad section and fixture rail on the member page: the plan's eleven after
 * its transfers on a marked pitch (the Pitch contract: one list, one item per line in the
 * order GK, DEF, MID, FWD, the full name as each plate's title), the bench in the order
 * published, the same week as a list one toggle away, the held squad in a closed section,
 * and the fixtures of the transfers and the eleven read from the published calendar.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { PageShell } from "../../../design/components/PageShell";
import { PHONE_QUERY } from "../../../design/shell/layout";
import { FIXTURE_SHEET_ID } from "../../../design/shell/ShellContext";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import type { FixturesPayload } from "../../fixtures/types";
import type { AdvicePlayer, EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";

afterEach(() => {
  cleanup();
  delete (window as { matchMedia?: unknown }).matchMedia;
  document.documentElement.style.overflow = "";
});

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const GW = SQUAD.payload.gameweek;

function player(
  id: number,
  name: string,
  short: string,
  position: AdvicePlayer["position"],
  team: string,
  expected?: number,
): AdvicePlayer {
  return {
    player_id: id,
    name,
    short_name: short,
    position,
    team,
    ...(expected === undefined ? {} : { expected_points: expected }),
  };
}

// A week shaped like the published GW6 plan: 3-4-3, two moves, captain and vice named.
const MARTIN = player(154561, "David Raya Martín", "Martín", "GK", "Arsenal", 3.94);
const GUEHI = player(209036, "Marc Guéhi", "Guéhi", "DEF", "Man City", 3.6);
const CALAFIORI = player(466075, "Riccardo Calafiori", "Calafiori", "DEF", "Arsenal", 3.55);
const CUYPER = player(465730, "Maxim De Cuyper", "Cuyper", "DEF", "Brighton", 3.3);
const FERNANDES = player(141746, "Bruno Borges Fernandes", "Fernandes", "MID", "Man Utd", 6.35);
const ROGERS = player(244850, "Morgan Rogers", "Rogers", "MID", "Chelsea", 4.55);
const GROSS = player(60307, "Pascal Groß", "Groß", "MID", "Brighton", 4.12);
// No figure published for this one: the plate prints none, never a 0.
const SZOBOSZLAI = player(424876, "Dominik Szoboszlai", "Szoboszlai", "MID", "Liverpool");
const HAALAND = player(223094, "Erling Haaland", "Haaland", "FWD", "Man City", 7.9988702038468515);
const BROBBEY = player(441264, "Brian Brobbey", "Brobbey", "FWD", "Sunderland", 3.58);
const LEWIN = player(177815, "Dominic Calvert-Lewin", "Calvert-Lewin", "FWD", "Leeds", 3.21);
const BENCH = [
  player(112520, "Alex Palmer", "Palmer", "GK", "Ipswich Town", 0.1),
  player(440993, "Iliman Ndiaye", "Ndiaye", "MID", "Man City", 2.93),
  player(199798, "Ezri Konsa Ngoyo", "Ngoyo", "DEF", "Arsenal", 2.63),
  player(219924, "Issa Diop", "Diop", "DEF", "Ipswich Town", 2.46),
];
const PALMER = player(244851, "Cole Palmer", "Palmer", "MID", "Chelsea");
const JESUS = player(475168, "João Pedro Junqueira de Jesus", "Jesus", "FWD", "Chelsea");
const ELEVEN = [
  MARTIN,
  GUEHI,
  CALAFIORI,
  CUYPER,
  FERNANDES,
  ROGERS,
  GROSS,
  SZOBOSZLAI,
  HAALAND,
  BROBBEY,
  LEWIN,
];

function week(patch: Partial<EntryAdvice> = {}): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return {
    ...base,
    payload: {
      ...base.payload,
      moves: [
        {
          move_id: "gw-1",
          player_out: PALMER,
          player_in: FERNANDES,
          expected_points_delta: 2.36,
          reason_code: "points_gain",
        },
        {
          move_id: "gw-2",
          player_out: JESUS,
          player_in: BROBBEY,
          expected_points_delta: 0.65,
          reason_code: "points_gain",
        },
      ],
      expected_gain_vs_hold: 3.01,
      transfer_hit_points: 0,
      solver_status: "OPTIMAL",
      expected_own_points: 56.105,
      captain: HAALAND,
      vice_captain: FERNANDES,
      starting_xi: ELEVEN,
      bench: BENCH,
      chip: null,
      ...patch,
    },
  };
}

function side(name: string, short: string, id: number) {
  return { team_id: id, name, short_name: short };
}

function fixture(id: number, home: ReturnType<typeof side>, away: ReturnType<typeof side>) {
  return {
    fixture_id: id,
    kickoff_utc: null,
    home,
    away,
    finished: false,
    home_score: null,
    away_score: null,
  };
}

const ARS = side("Arsenal", "ARS", 1);
const BHA = side("Brighton", "BHA", 5);
const CHE = side("Chelsea", "CHE", 6);
const LEE = side("Leeds", "LEE", 13);
const LIV = side("Liverpool", "LIV", 14);
const MCI = side("Man City", "MCI", 15);
const MUN = side("Man Utd", "MUN", 16);
const SUN = side("Sunderland", "SUN", 20);
const BOU = side("Bournemouth", "BOU", 3);
const TOT = side("Spurs", "TOT", 19);

const CALENDAR: FixturesPayload = {
  season: SQUAD.payload.season,
  source_snapshot_id: "calendar-test",
  captured_at_utc: "2026-08-20T00:00:00Z",
  current_gameweek: GW,
  unscheduled_count: 0,
  gameweeks: [
    {
      gameweek: GW,
      deadline_utc: "2026-10-10T10:00:00Z",
      fixtures: [
        fixture(1, ARS, LEE),
        fixture(2, CHE, BOU),
        fixture(3, SUN, BHA),
        fixture(4, MUN, TOT),
        fixture(5, LIV, MCI),
      ],
    },
    {
      gameweek: GW + 1,
      // A double week for Sunderland; Man Utd do not play.
      deadline_utc: "2026-10-17T10:00:00Z",
      fixtures: [fixture(6, BOU, SUN), fixture(7, SUN, CHE), fixture(8, MCI, ARS)],
    },
    {
      gameweek: GW + 2,
      deadline_utc: "2026-10-24T10:00:00Z",
      fixtures: [fixture(9, CHE, TOT), fixture(10, SUN, LEE), fixture(11, MUN, BOU)],
    },
  ],
};

function view(props: Partial<LeagueMemberViewProps> = {}): LeagueMemberViewProps {
  return {
    squad: SQUAD,
    advice: week(),
    members: MEMBERS,
    index: mockEntryAdviceIndex(ENTRY).payload,
    fixtures: CALENDAR,
    leagueName: mockLeagueMembersEnvelope.payload.league_name,
    ...props,
  };
}

function show(language: Language = "tr", props: Partial<LeagueMemberViewProps> = {}) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
        <LeagueMemberView {...view(props)} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const pitch = (language: Language = "tr") =>
  screen.getByRole("list", { name: MESSAGES[language].squad.pitchLabel });

describe("the squad after the transfers, on the pitch", () => {
  it.each(["tr", "en"] as const)("draws the plan's eleven, line by line, in %s", (language) => {
    show(language);
    const copy = MESSAGES[language];
    expect(
      screen.getByRole("heading", { level: 2, name: copy.leagueMembers.squadAfterTitle }),
    ).toBeInTheDocument();
    // The formation and the plan's own total, from the published fields.
    expect(
      screen.getByText(
        `3-4-3 · ${copy.leagueMembers.squadOwnPoints(language === "tr" ? "56,11" : "56.11")}`,
      ),
    ).toBeInTheDocument();
    const lines = within(pitch(language)).getAllByRole("listitem");
    // Each line is named by the position word in the page's language, never by the code.
    expect(lines.map((line) => line.getAttribute("aria-label"))).toEqual(
      (["GK", "DEF", "MID", "FWD"] as const).map((code) => copy.positions[code]),
    );
    expect(lines.map((line) => line.dataset.line)).toEqual(["gk", "def", "mid", "fwd"]);
    const byLine = (position: string) =>
      Array.from(
        lines
          .find((line) => line.dataset.line === position.toLowerCase())!
          .querySelectorAll("[title]"),
        (plate) => plate.getAttribute("title"),
      );
    // Every line in the published order.
    expect(byLine("DEF")).toEqual([GUEHI.name, CALAFIORI.name, CUYPER.name]);
    expect(byLine("MID")).toEqual([FERNANDES.name, ROGERS.name, GROSS.name, SZOBOSZLAI.name]);
    for (const player of ELEVEN) {
      expect(within(pitch(language)).getByTitle(player.name)).toHaveTextContent(player.short_name);
    }
  });

  it("marks the armband and the players the moves bring in, and prints only published figures", () => {
    show("tr");
    const copy = MESSAGES.tr;
    const plateOf = (name: string) => within(pitch()).getByTitle(name).parentElement!;
    // One captain and one vice-captain, each on its own plate.
    expect(within(pitch()).getAllByLabelText(copy.squad.captainLabel)).toHaveLength(1);
    expect(
      within(plateOf(HAALAND.name)).getByLabelText(copy.squad.captainLabel),
    ).toBeInTheDocument();
    expect(
      within(plateOf(FERNANDES.name)).getByLabelText(copy.squad.viceCaptainLabel),
    ).toBeInTheDocument();
    // YENİ on the two players this week's moves bring in, and on no one else.
    expect(within(pitch()).getAllByText(copy.leagueMembers.boardNew)).toHaveLength(2);
    expect(within(plateOf(FERNANDES.name)).getByText(copy.leagueMembers.boardNew)).toBeTruthy();
    expect(within(plateOf(BROBBEY.name)).getByText(copy.leagueMembers.boardNew)).toBeTruthy();
    // The club's code from the calendar, the figure as published, trimmed to two places.
    expect(plateOf(HAALAND.name)).toHaveTextContent("MCI");
    // The unit is the Turkish words a screen reader hears, never the English "xP".
    const unit = copy.leagueMembers.pointsUnitSpoken;
    expect(plateOf(HAALAND.name)).toHaveTextContent(`8,0 ${unit}`);
    expect(plateOf(MARTIN.name)).toHaveTextContent(`3,94 ${unit}`);
    expect(pitch()).not.toHaveTextContent("xP");
    // A player whose figure is not published shows none, and never a 0.
    expect(plateOf(SZOBOSZLAI.name)).not.toHaveTextContent(new RegExp(`${unit}|\\d`));
  });

  it("writes the direction of attack under the first defender in the published order", () => {
    const { container } = show("tr");
    const labels = screen.getAllByText(MESSAGES.tr.leagueMembers.attackDirection);
    // Three defenders leave room between their plates: one label, under Guéhi.
    expect(labels).toHaveLength(1);
    expect(labels[0]).toHaveAttribute("aria-hidden", "true");
    expect(within(labels[0]!.parentElement!).getByTitle(GUEHI.name)).toBeInTheDocument();
    // The direction is also in the pitch's description, for both ways it can be drawn.
    expect(pitch()).toHaveAccessibleDescription(
      `${MESSAGES.tr.leagueMembers.pitchHorizontal}${MESSAGES.tr.leagueMembers.pitchVertical}`,
    );
    expect(container.querySelector("[data-def-crowded]")).toBeNull();
  });

  it("adds a place under the whole defence when four or more stand in it", () => {
    const back4 = [
      MARTIN,
      GUEHI,
      CALAFIORI,
      CUYPER,
      { ...BENCH[3]!, position: "DEF" as const },
      FERNANDES,
      ROGERS,
      GROSS,
      HAALAND,
      BROBBEY,
      LEWIN,
    ];
    const { container } = show("en", { advice: week({ starting_xi: back4 }) });
    const labels = screen.getAllByText(MESSAGES.en.leagueMembers.attackDirection);
    // Under the first defender where the pitch is drawn upright, under the last across it
    // (the stylesheet shows the one that fits).
    expect(labels.map((label) => label.getAttribute("data-at"))).toEqual(["first", "last"]);
    expect(within(labels[0]!.parentElement!).getByTitle(GUEHI.name)).toBeInTheDocument();
    expect(within(labels[1]!.parentElement!).getByTitle(BENCH[3]!.name)).toBeInTheDocument();
    expect(container.querySelector("[data-def-crowded]")).not.toBeNull();
  });

  it("lists the bench under the pitch in the published order", () => {
    show("en");
    const bench = screen.getByRole("region", { name: MESSAGES.en.leagueMembers.bench });
    const items = within(bench).getAllByRole("listitem");
    expect(items.map((item) => item.firstElementChild!.textContent)).toEqual(["1", "2", "3", "4"]);
    items.forEach((item, index) => expect(item).toHaveTextContent(BENCH[index]!.name));
    // Club code and position word, never a first name alone.
    expect(items[0]).toHaveTextContent("IPS · goalkeeper");
  });

  it("switches between the pitch and the week's list", () => {
    show("tr");
    const copy = MESSAGES.tr.leagueMembers;
    const toggle = screen.getByRole("group", { name: copy.viewLabel });
    const [onPitch, asList] = within(toggle).getAllByRole("button");
    expect(onPitch).toHaveTextContent(copy.viewPitch);
    expect(onPitch).toHaveAttribute("aria-pressed", "true");
    expect(asList).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("region", { name: copy.lineupTitle })).toBeNull();

    fireEvent.click(asList!);
    expect(asList).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: copy.lineupTitle })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: MESSAGES.tr.squad.pitchLabel })).toBeNull();

    fireEvent.click(onPitch!);
    expect(pitch()).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: copy.lineupTitle })).toBeNull();
  });

  it("keeps the squad held before the transfers in a closed section of its own", () => {
    show("tr");
    const copy = MESSAGES.tr.leagueMembers;
    const held = screen
      .getByText(copy.memberSquad, { selector: "summary span" })
      .closest("details")!;
    expect(held).not.toHaveAttribute("open");
    expect(within(held).getAllByRole("listitem")).toHaveLength(
      SQUAD.payload.starting_xi.length + SQUAD.payload.bench.length,
    );
    // The pitch's list label stays unique on the page.
    expect(
      screen.getAllByRole("list", { name: MESSAGES.tr.squad.pitchLabel, hidden: true }),
    ).toHaveLength(1);
  });

  it("draws a partial squad as far as it goes, with no formation made up", () => {
    const partial = Object.values(mockEntrySquadEnvelopes).find(
      (squad) => squad.payload.data_quality === "partial",
    )!;
    expect(partial.payload.starting_xi).toHaveLength(8);
    render(
      <LanguageProvider initialLanguage="en">
        <MemoryRouter>
          <LeagueMemberView squad={partial} advice={null} members={MEMBERS} />
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(pitch("en").querySelectorAll("[title]")).toHaveLength(8);
    expect(screen.queryByText(/^\d-\d-\d/)).toBeNull();
    const bench = screen.getByRole("region", { name: MESSAGES.en.leagueMembers.bench });
    expect(within(bench).getAllByRole("listitem")).toHaveLength(2);
  });

  it("gives the squad's place an anchor for 'Kadro' even when there is no squad", () => {
    const empty = Object.values(mockEntrySquadEnvelopes).find(
      (squad) => squad.payload.starting_xi.length === 0,
    )!;
    const { container } = render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter>
          <LeagueMemberView squad={empty} advice={null} members={MEMBERS} />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const section = container.querySelector("#kadro")!;
    expect(section).toHaveTextContent(MESSAGES.tr.leagueMembers.emptySquad);
    expect(screen.queryByRole("list", { name: MESSAGES.tr.squad.pitchLabel })).toBeNull();
  });
});

describe("the fixture rail", () => {
  const rail = (language: Language = "tr") =>
    screen.getByRole("complementary", { name: MESSAGES[language].shell.fixtures });

  it.each(["tr", "en"] as const)(
    "shows the transfers' and the eleven's next three gameweeks in %s",
    (language) => {
      show(language);
      const copy = MESSAGES[language].leagueMembers;
      const aside = rail(language);
      expect(aside).toHaveTextContent(copy.railWeeks([GW, GW + 1, GW + 2]));
      // Block A: each move as the player going out, then the one coming in.
      const transfers = within(aside).getByRole("region", { name: copy.railTransfers });
      const rows = within(transfers).getAllByRole("row").slice(1);
      expect(rows.map((row) => row.querySelector("th")!.textContent)).toEqual([
        `${copy.out}${PALMER.short_name}${PALMER.name}CHE`,
        `${copy.in}${FERNANDES.short_name}${FERNANDES.name}MUN`,
        `${copy.out}${JESUS.short_name}${JESUS.name}CHE`,
        `${copy.in}${BROBBEY.short_name}${BROBBEY.name}SUN`,
      ]);
      const home = copy.fixtureHome;
      const away = copy.fixtureAway;
      // Chelsea: at home to Bournemouth, away at Sunderland, at home to Spurs.
      expect(
        within(rows[0]!)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ).toEqual([`BOU ${home}`, `SUN ${away}`, `TOT ${home}`]);
      // Sunderland's double week lists both matches; Man Utd's blank week says so.
      expect(within(rows[3]!).getAllByRole("cell")[1]).toHaveTextContent(`BOU ${away}CHE ${home}`);
      expect(within(rows[1]!).getAllByRole("cell")[1]).toHaveTextContent(copy.fixtureNone);
      // Block B: the eleven, one row each, the captain marked.
      const eleven = within(aside).getByRole("region", { name: copy.railXi });
      expect(within(eleven).getAllByRole("row")).toHaveLength(1 + ELEVEN.length);
      expect(within(eleven).getByRole("rowheader", { name: /Haaland/ })).toHaveTextContent(
        MESSAGES[language].squad.captainLabel,
      );
      // A home match is filled and an away one outlined; nothing else is encoded.
      expect(
        within(rows[0]!).getAllByRole("cell")[0]!.querySelector("[data-venue]"),
      ).toHaveAttribute("data-venue", "home");
      expect(
        within(rows[0]!).getAllByRole("cell")[1]!.querySelector("[data-venue]"),
      ).toHaveAttribute("data-venue", "away");
      // Block C: players of the eleven who face each other that week, home side first.
      const meet = within(aside).getByRole("region", { name: copy.railMeet(GW) });
      expect(
        within(meet)
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual([
        "ARS - LEEMartín, Calafiori / Calvert-Lewin",
        "SUN - BHABrobbey / Cuyper, Groß",
        "LIV - MCISzoboszlai / Guéhi, Haaland",
      ]);
      expect(aside).toHaveTextContent(copy.railLegendVenue);
      expect(aside).toHaveTextContent(copy.railLegendDifficulty);
    },
  );

  it("says so quietly, and shows nothing member-specific, without the calendar", () => {
    show("tr", { fixtures: null });
    const aside = rail();
    expect(aside).toHaveTextContent(MESSAGES.tr.leagueMembers.railNoCalendar);
    expect(within(aside).queryByRole("table")).toBeNull();
  });

  it("says the calendar is being read, not that it failed, while it loads", () => {
    show("tr", { fixtures: null, fixturesPending: true });
    const aside = rail();
    expect(aside).toHaveTextContent(MESSAGES.tr.leagueMembers.railLoading);
    expect(aside).not.toHaveTextContent(MESSAGES.tr.leagueMembers.railNoCalendar);
  });

  it("leaves out the weeks the calendar does not list", () => {
    show("en", {
      fixtures: { ...CALENDAR, gameweeks: CALENDAR.gameweeks.slice(0, 2) },
    });
    const aside = rail("en");
    expect(aside).toHaveTextContent(MESSAGES.en.leagueMembers.railWeeks([GW, GW + 1]));
    const eleven = within(aside).getByRole("region", { name: MESSAGES.en.leagueMembers.railXi });
    expect(within(eleven).getAllByRole("columnheader")).toHaveLength(3);
  });
});

/** The shell's phone layout: the rail becomes the phone bar's fixture sheet. */
function phone() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      media: query,
      matches: query === PHONE_QUERY,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
}

describe("the fixture sheet on a phone", () => {
  it("opens from the phone bar as a modal sheet outside the page, and closes", async () => {
    phone();
    const user = userEvent.setup();
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
          <PageShell>
            <LeagueMemberView {...view()} />
          </PageShell>
        </MemoryRouter>
      </LanguageProvider>,
    );
    const shell = MESSAGES.tr.shell;
    // The phone bar's 'Fikstür', a button now that the page offers its sheet.
    const open = screen.getByRole("button", { name: shell.fixtures });
    expect(open).toHaveAttribute("aria-controls", FIXTURE_SHEET_ID);
    expect(open).toHaveAttribute("aria-expanded", "false");
    const sheet = document.getElementById(FIXTURE_SHEET_ID)!;
    // One rail, rendered outside the page's main so the page can be made inert under it.
    expect(sheet.closest("main")).toBeNull();
    expect(screen.queryByRole("dialog", { name: shell.fixtures })).toBeNull();

    await user.click(open);
    const dialog = screen.getByRole("dialog", { name: shell.fixtures });
    expect(dialog).toBe(sheet);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
    const close = within(dialog).getByRole("button", { name: shell.closeFixtures });
    await waitFor(() => expect(close).toHaveFocus());

    await user.click(close);
    expect(screen.queryByRole("dialog", { name: shell.fixtures })).toBeNull();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    // Focus goes back to the button that opened it.
    expect(open).toHaveFocus();
  });
});

describe("the reading order around the squad", () => {
  // Tab order follows the document, so the document has to say what the screen shows.
  const before = (first: Element, second: Element) =>
    Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  const parts = () => {
    const copy = MESSAGES.tr.leagueMembers;
    return {
      decision: document.querySelector('[data-mark="decision"]')!,
      how: screen.getByText(copy.howComputed).closest("summary")!,
      toggle: screen.getByRole("button", { name: copy.viewPitch }),
    };
  };

  it("reads the decision, then what to make of it, then the squad on a phone", () => {
    phone();
    show("tr");
    const { decision, how, toggle } = parts();
    expect(document.querySelectorAll('[data-mark="honesty"]')).toHaveLength(1);
    expect(before(decision, how)).toBe(true);
    expect(before(how, toggle)).toBe(true);
  });

  it("keeps the squad before the honesty block where the squad is drawn first", () => {
    show("tr");
    const { decision, how, toggle } = parts();
    expect(document.querySelectorAll('[data-mark="honesty"]')).toHaveLength(1);
    expect(before(decision, toggle)).toBe(true);
    expect(before(toggle, how)).toBe(true);
  });
});

describe("a squad without a plan", () => {
  it("draws the squad the member holds, with no vice-captain inferred", () => {
    show("en", { advice: null });
    const copy = MESSAGES.en;
    expect(
      screen.getByRole("heading", { level: 2, name: copy.leagueMembers.memberSquad }),
    ).toBeInTheDocument();
    expect(within(pitch("en")).queryByLabelText(copy.squad.viceCaptainLabel)).toBeNull();
    expect(within(pitch("en")).queryAllByText(copy.leagueMembers.boardNew)).toHaveLength(0);
    // There is no list view to switch to, and no held section repeating the pitch.
    expect(screen.queryByRole("group", { name: copy.leagueMembers.viewLabel })).toBeNull();
    expect(
      screen.queryByText(copy.leagueMembers.memberSquad, { selector: "summary span" }),
    ).toBeNull();
  });
});
