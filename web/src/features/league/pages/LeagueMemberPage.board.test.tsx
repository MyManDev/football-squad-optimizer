/**
 * Direction D's member page: the top bar with the team as the one heading and the score
 * bug, the WHO block, the decision as substitution boards with the gain strip, the captain
 * line and the proof stamp, the two honesty lines with their disclosure, and the tools
 * that wait closed. Every figure is a published one; what is absent is left out.
 */

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { deadlineLong } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { HttpAdviceClient } from "../advice/adviceClient";
import { writeViewerEntry } from "../identity/useViewerEntry";
import type {
  AdviceMove,
  AdvicePlayer,
  EntryAdvice,
  EntrySquad,
  LeagueViewEnvelope,
} from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import { AdviceCard } from "./MemberAdviceCard";
import type { LeagueMemberViewProps } from "./memberPageTypes";

afterEach(cleanup);
beforeEach(() => writeViewerEntry(null));

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const HUMANS = MEMBERS.filter((member) => member.member_kind === "human").length;
const GW = SQUAD.payload.gameweek;
const FORBIDDEN =
  /%|probabilit|olasılık|olasılığ|\bP\(|chance|likelihood|quantile|spread|percentage|ihtimal|şans|yüzde(?!n\b)|kantil|yayılım/i;

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

const PALMER = player(244851, "Cole Palmer", "Palmer", "MID", "Chelsea");
const FERNANDES = player(141746, "Bruno Borges Fernandes", "Fernandes", "MID", "Man Utd", 6.35);
const JESUS = player(475168, "João Pedro Junqueira de Jesus", "Jesus", "FWD", "Chelsea");
const BROBBEY = player(441264, "Brian Brobbey", "Brobbey", "FWD", "Sunderland", 3.58);
const HAALAND = player(223094, "Erling Haaland", "Haaland", "FWD", "Man City", 7.9988702038468515);

function move(id: string, out: AdvicePlayer, into: AdvicePlayer, delta: number | null): AdviceMove {
  return {
    move_id: id,
    player_out: out,
    player_in: into,
    expected_points_delta: delta,
    reason_code: "points_gain",
  };
}

/** The GW6 plan's shape (two moves, both published as shares) on the example member. */
function twoMoves(patch: Partial<EntryAdvice> = {}): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return {
    ...base,
    payload: {
      ...base.payload,
      moves: [
        move("gw-1", PALMER, FERNANDES, 2.3565723928800963),
        move("gw-2", JESUS, BROBBEY, 0.6539544173418577),
      ],
      expected_gain_vs_hold: 3.010526810221954,
      transfer_hit_points: 0,
      solver_status: "OPTIMAL",
      optimality_gap: 0,
      captain: HAALAND,
      vice_captain: FERNANDES,
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

const CHE = side("Chelsea", "CHE", 6);
const MUN = side("Man Utd", "MUN", 14);
const SUN = side("Sunderland", "SUN", 18);
const BOU = side("Bournemouth", "BOU", 3);
const EVE = side("Everton", "EVE", 9);
const TOT = side("Spurs", "TOT", 19);
const LEE = side("Leeds", "LEE", 13);
const BHA = side("Brighton", "BHA", 5);

/** A calendar for the example week and the two after it, in the published shape. */
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
      fixtures: [fixture(1, CHE, BOU), fixture(2, MUN, TOT), fixture(3, SUN, BHA)],
    },
    {
      gameweek: GW + 1,
      // A double week for Sunderland.
      deadline_utc: "2026-10-17T10:00:00Z",
      fixtures: [
        fixture(4, EVE, CHE),
        fixture(5, LEE, MUN),
        fixture(6, BOU, SUN),
        fixture(7, SUN, EVE),
      ],
    },
    {
      gameweek: GW + 2,
      // A blank week for Man Utd.
      deadline_utc: "2026-10-24T10:00:00Z",
      fixtures: [fixture(8, CHE, TOT), fixture(9, SUN, LEE)],
    },
  ],
};

function show(
  language: Language = "tr",
  props: Partial<LeagueMemberViewProps> = {},
  initial = `/league/members/${ENTRY}`,
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <LeagueMemberView
          squad={SQUAD}
          advice={twoMoves()}
          members={MEMBERS}
          index={mockEntryAdviceIndex(ENTRY).payload}
          fixtures={CALENDAR}
          leagueName={mockLeagueMembersEnvelope.payload.league_name}
          {...props}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const decision = (language: Language = "tr") =>
  screen.getByRole("region", { name: MESSAGES[language].leagueMembers.decisionTitle });
const boards = (language: Language = "tr") => within(decision(language)).getAllByRole("article");

describe("the top bar", () => {
  it("names the team as the page's one heading, then the week and its deadline", () => {
    show("tr");
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent(SQUAD.payload.entry.team_name!);
    expect(screen.getByText(`${GW}. hafta`)).toBeInTheDocument();
    // The calendar's deadline in the reader's own time (13:00 on a device set to Istanbul).
    expect(screen.getByText("Son karar")).toBeInTheDocument();
    expect(screen.getByText(deadlineLong("2026-10-10T10:00:00Z", "tr-TR"))).toBeInTheDocument();
  });

  it("shows the published standing in the score bug", () => {
    show("tr");
    const copy = MESSAGES.tr.leagueMembers;
    const bug = screen.getByText(copy.rankLabel).closest("dl")!;
    const cells = Object.fromEntries(
      within(bug)
        .getAllByRole("term")
        .map((term) => [term.textContent, term.nextElementSibling?.textContent]),
    );
    const entry = SQUAD.payload.entry;
    expect(cells).toEqual({
      [copy.rankLabel]: `${entry.rank}/${HUMANS}`,
      [copy.pointsLabel]: String(entry.total_points),
      // Net of the week's hit, as the member list nets it.
      [copy.lastWeekLabel]: String(entry.gameweek_points! - entry.transfer_cost!),
      [copy.bankLabel]: "0,7m",
    });
    // The example squad's free transfers are not known, so there is no cell for them.
    expect(within(bug).queryByText(copy.freeTransfersLabel)).toBeNull();
  });

  it("leaves out a cell whose number is absent instead of printing 0", () => {
    const squad: LeagueViewEnvelope<EntrySquad> = structuredClone(SQUAD);
    squad.payload.entry.transfer_cost = null;
    squad.payload.entry.total_points = null;
    squad.payload.free_transfers_known = true;
    squad.payload.free_transfers = 2;
    show("en", { squad });
    const copy = MESSAGES.en.leagueMembers;
    const bug = screen.getByText(copy.rankLabel).closest("dl")!;
    expect(within(bug).queryByText(copy.lastWeekLabel)).toBeNull();
    expect(within(bug).queryByText(copy.pointsLabel)).toBeNull();
    expect(within(bug).getByText(copy.freeTransfersLabel).nextElementSibling).toHaveTextContent(
      "2",
    );
    expect(within(bug).getByText(copy.bankLabel).nextElementSibling).toHaveTextContent("£0.7m");
  });

  it("says nothing about a deadline the calendar does not state, and names a passed one", () => {
    show("tr", { fixtures: null });
    expect(screen.queryByText("Son karar")).toBeNull();
    cleanup();
    show("tr", { fixtures: CALENDAR, deadlinePassed: "2026-10-10T10:00:00Z" });
    expect(screen.getByText(MESSAGES.tr.leagueMembers.deadlinePassedLabel)).toBeInTheDocument();
    expect(screen.getByTestId("deadline-passed")).toBeVisible();
  });
});

describe("the WHO block", () => {
  it("names the league and links the member back to the list to change member", () => {
    show("tr");
    const who = screen.getByRole("link", { name: /Üye değiştir/ });
    expect(who).toHaveAttribute("href", "/league/members");
    expect(who).toHaveTextContent(SQUAD.payload.entry.team_name!);
    expect(who).toHaveTextContent(`${SQUAD.payload.entry.manager_name} · #${ENTRY}`);
    expect(screen.getByText(mockLeagueMembersEnvelope.payload.league_name)).toBeInTheDocument();
  });
});

describe("the substitution boards", () => {
  it("draws one board per move with the club code and the position word on both sides", () => {
    show("tr");
    const [first, second] = boards();
    expect(within(first!).getByRole("heading", { name: "Değişiklik 1/2" })).toBeInTheDocument();
    expect(within(second!).getByRole("heading", { name: "Değişiklik 2/2" })).toBeInTheDocument();
    // The Palmer rule: the player going out always carries his club and his position.
    expect(first).toHaveTextContent("Çıkan");
    expect(first).toHaveTextContent("Giren");
    expect(within(first!).getAllByText("orta saha")).toHaveLength(2);
    expect(within(first!).getByText("CHE")).toBeInTheDocument();
    expect(within(first!).getByText("MUN")).toBeInTheDocument();
    expect(within(second!).getAllByText("forvet")).toHaveLength(2);
    expect(within(second!).getByText("SUN")).toBeInTheDocument();
    // The screen reader hears the full name; the eye reads the game's short one.
    expect(within(first!).getByText("Cole Palmer")).toHaveClass("visually-hidden");
    expect(within(first!).getByText("Palmer")).toHaveAttribute("aria-hidden", "true");
    // Only the player coming in is new.
    expect(within(first!).getAllByText("Yeni")).toHaveLength(1);
  });

  it("prints each share in LED digits with its sign and the words beside it", () => {
    show("tr");
    const [first, second] = boards();
    expect(within(first!).getByText("+2,36")).toBeInTheDocument();
    expect(within(second!).getByText("+0,65")).toBeInTheDocument();
    expect(within(first!).getByText("beklenen puan")).toBeInTheDocument();
    cleanup();
    show("en", {
      advice: twoMoves({
        moves: [move("gw-1", PALMER, FERNANDES, -0.4), move("gw-2", JESUS, BROBBEY, 1.2)],
        expected_gain_vs_hold: 0.8,
      }),
    });
    expect(within(boards("en")[0]!).getByText("−0.4")).toBeInTheDocument();
  });

  it("gives each side the club's next three gameweeks, a double week and a blank one", () => {
    show("tr");
    const [first, second] = boards();
    expect(within(first!).getByText(/BOU E · EVE D · TOT E/)).toBeInTheDocument();
    expect(within(first!).getByText(/TOT E · LEE D · maç yok/)).toBeInTheDocument();
    expect(within(second!).getByText(/BHA E · BOU D \/ EVE E · LEE E/)).toBeInTheDocument();
    cleanup();
    // No calendar, no strip: never a guessed fixture.
    show("tr", { fixtures: null });
    expect(boards()[0]).not.toHaveTextContent(/BOU E/);
  });

  it("says the move's share was not published instead of a number", () => {
    const advice = twoMoves({ moves: [move("gw-1", PALMER, FERNANDES, null)] });
    show("tr", { advice });
    const [board] = boards();
    expect(
      within(board!).getByText(MESSAGES.tr.leagueMembers.projectedGainUnknown),
    ).toBeInTheDocument();
    expect(within(board!).queryByText("beklenen puan")).toBeNull();
  });

  it("keeps today's sentence in the board area when the plan has no move", () => {
    show("tr", { advice: twoMoves({ moves: [], expected_gain_vs_hold: 0 }) });
    expect(within(decision()).queryAllByRole("article")).toHaveLength(0);
    // The example plan publishes its eleven, bench and armband, so no transfer is a finding.
    expect(within(decision()).getByText(MESSAGES.tr.leagueMembers.noMove)).toBeVisible();
  });
});

describe("the gain strip and the captain line", () => {
  it("states the gain with its basis, the bar, and the transfer facts", () => {
    const squad: LeagueViewEnvelope<EntrySquad> = structuredClone(SQUAD);
    squad.payload.free_transfers_known = true;
    squad.payload.free_transfers = 2;
    show("tr", { squad });
    const copy = MESSAGES.tr.leagueMembers;
    const caption = screen.getByText(copy.gainCaption);
    expect(caption.closest("p")).toHaveTextContent(`+3,01 ${copy.gainCaption}`);
    expect(screen.getByText(copy.freeTransfersUsed(2, 2))).toBeInTheDocument();
    expect(screen.getByText(copy.hitPointsFact("0"))).toBeInTheDocument();
    // Every share is published and none is below zero: one stacked bar at a fixed scale.
    const bar = decision().querySelector('[class*="segments"]')!;
    expect(bar.children).toHaveLength(2);
    expect(bar.parentElement).toHaveAttribute("aria-hidden", "true");
    expect((bar.children[0] as HTMLElement).style.getPropertyValue("--share")).toBe(
      "2.3565723928800963",
    );
  });

  it("lists signed shares instead of a bar when one is below zero", () => {
    show("en", {
      advice: twoMoves({
        moves: [move("gw-1", PALMER, FERNANDES, -0.4), move("gw-2", JESUS, BROBBEY, 1.2)],
        expected_gain_vs_hold: 0.8,
      }),
    });
    expect(decision("en").querySelector('[class*="segments"]')).toBeNull();
    const list = screen.getByText("Fernandes −0.4").closest("p")!;
    expect(list).toHaveTextContent("Fernandes −0.4 · Brobbey +1.2");
    // A share never parts from its player at a line break.
    for (const item of ["Fernandes −0.4", "Brobbey +1.2"]) {
      expect(within(list).getByText(item).className).toMatch(/gainItem/);
    }
  });

  it("colours the gain by its sign, and a loss against holding is never drawn green", () => {
    show("en", {
      advice: twoMoves({
        moves: [move("gw-1", PALMER, FERNANDES, -2.0), move("gw-2", JESUS, BROBBEY, 1.2)],
        expected_gain_vs_hold: -0.8,
      }),
    });
    expect(screen.getByText("−0.8")).toHaveAttribute("data-sign", "down");
    cleanup();
    show("en");
    const figure = screen.getAllByText("+3.01").find((element) => element.tagName === "STRONG");
    expect(figure).toHaveAttribute("data-sign", "up");
  });

  it("counts the free transfers used as at most the ones held", () => {
    const squad: LeagueViewEnvelope<EntrySquad> = structuredClone(SQUAD);
    squad.payload.free_transfers_known = true;
    squad.payload.free_transfers = 1;
    show("tr", { squad, advice: twoMoves({ transfer_hit_points: 4 }) });
    const copy = MESSAGES.tr.leagueMembers;
    // Two moves on one free transfer: one is free and the other is the hit named beside it.
    expect(screen.getByText(copy.freeTransfersUsed(1, 1))).toBeInTheDocument();
    expect(screen.queryByText(copy.freeTransfersUsed(2, 1))).toBeNull();
    expect(screen.getByText(copy.hitPointsFact("4"))).toBeInTheDocument();
  });

  it("says a Wildcard or Free Hit week spends none of the free transfers held", () => {
    const squad: LeagueViewEnvelope<EntrySquad> = structuredClone(SQUAD);
    squad.payload.free_transfers_known = true;
    squad.payload.free_transfers = 5;
    const copy = MESSAGES.tr.leagueMembers;
    for (const chip of ["wildcard", "freehit"] as const) {
      show("tr", { squad, advice: twoMoves({ chip, transfer_hit_points: 0 }) });
      expect(
        screen.getByText(copy.freeTransfersKeptUnderChip(copy.chipNames[chip]!, 5)),
      ).toBeInTheDocument();
      expect(screen.queryByText(copy.freeTransfersUsed(2, 5))).toBeNull();
      expect(screen.getByText(copy.hitPointsFact("0"))).toBeInTheDocument();
      cleanup();
    }
    // A Bench Boost week still counts its moves against the free transfers.
    show("tr", { squad, advice: twoMoves({ chip: "bboost" }) });
    expect(screen.getByText(copy.freeTransfersUsed(2, 5))).toBeInTheDocument();
  });

  it("names no free-transfer fact the squad does not publish", () => {
    show("tr");
    expect(screen.queryByText(/ücretsiz transfer$/)).toBeNull();
  });

  it("puts the captain and the vice-captain on one line with their clubs", () => {
    show("tr");
    // The squad's list view names the armband too; the captain line is the decision's.
    const decision = document.querySelector<HTMLElement>('[data-mark="decision"]')!;
    const line = within(decision).getByText("Haaland").closest("p")!;
    expect(line).toHaveTextContent("Kaptan");
    expect(line).toHaveTextContent("MCI");
    expect(line).toHaveTextContent(`8,0 ${MESSAGES.tr.leagueMembers.pointsUnit}`);
    expect(line).not.toHaveTextContent("xP");
    expect(line).toHaveTextContent("Yedek kaptan");
    expect(within(line).getByText("Fernandes")).toBeInTheDocument();
  });
});

describe("the proof stamp", () => {
  it("says KANITLANDI · OPTİMAL only for a proven plan", () => {
    show("tr");
    // Turkish capitals: the dotted İ, never the English I.
    expect(MESSAGES.tr.leagueMembers.stampOptimal).toBe("KANITLANDI · OPTİMAL");
    expect(screen.getByText(MESSAGES.tr.leagueMembers.stampOptimal)).toBeInTheDocument();
    expect(screen.getByText(MESSAGES.tr.leagueMembers.stampOptimalCaption)).toBeInTheDocument();
  });

  it("keeps the unproven badge and the gap sentence for a plan found without a proof", () => {
    show("tr", { advice: twoMoves({ solver_status: "FEASIBLE", optimality_gap: 1.3 }) });
    const copy = MESSAGES.tr.leagueMembers;
    expect(screen.queryByText(copy.stampOptimal)).toBeNull();
    expect(screen.getAllByText(copy.unprovenPlanBadge)).toHaveLength(1);
    expect(screen.getByText(copy.unprovenPlanBody("1,3"))).toBeInTheDocument();
  });

  it("claims nothing for a status that is neither", () => {
    const advice = twoMoves();
    delete (advice.payload as { solver_status?: string }).solver_status;
    show("en", { advice });
    expect(screen.queryByText(MESSAGES.en.leagueMembers.stampOptimal)).toBeNull();
    expect(screen.queryByText(MESSAGES.en.leagueMembers.unprovenPlanBadge)).toBeNull();
  });
});

describe("the decision heading", () => {
  it("names the selection beside the heading", () => {
    show("tr", {}, `/league/members/${ENTRY}?window=1`);
    expect(screen.getByTestId("member-selection-summary")).toHaveTextContent("Saf puan · 1 hafta");
  });

  it("echoes a computation in the heading, where it stays in view once the drawer closes", async () => {
    // The service queues the request and has not answered since.
    const client = new HttpAdviceClient("https://api.example", async (_url, init) =>
      init?.method === "POST"
        ? new Response(JSON.stringify({ job_id: "job-echo", status: "queued" }), { status: 202 })
        : new Promise<Response>(() => undefined),
    );
    show("tr", { advice: null, client });
    const echo = within(decision())
      .getByTestId("member-selection-summary")
      .parentElement!.querySelector("[aria-live]")!;
    expect(echo).toBeEmptyDOMElement();
    await act(async () => {
      screen.getByRole("button", { name: "Hesapla" }).click();
      await Promise.resolve();
    });
    await waitFor(() => expect(echo).toHaveTextContent("Hesap: kuyrukta"));
    // The panel keeps its own badge; the echo is one line, not a second copy of it.
    expect(screen.getByText("Kuyrukta")).toBeInTheDocument();
  });
});

describe("honesty and the tools", () => {
  it("shows two honesty lines and keeps the rest one click away", () => {
    show("tr");
    const copy = MESSAGES.tr.leagueMembers;
    expect(screen.getByText(copy.honestyModel)).toBeVisible();
    expect(screen.getByText(copy.honestyDecision)).toBeVisible();
    const how = screen.getByText(copy.howComputed).closest("details")!;
    expect(how).not.toHaveAttribute("open");
    for (const sentence of [
      copy.honestyRule,
      copy.independentAdviceRule,
      copy.lineupRule,
      copy.moveRowsBasis,
      copy.diagnosticOnly,
      copy.freshnessNote,
    ]) {
      expect(within(how).getByText(sentence)).not.toBeVisible();
    }
    // The week's hit charge is said once, in the disclosure.
    expect(within(how).getAllByText(/beklenen puan maliyeti/)).toHaveLength(1);
  });

  it("keeps the secondary tools closed, each with its own controls inside", () => {
    const { container } = show("tr");
    const copy = MESSAGES.tr.leagueMembers;
    for (const title of [copy.advancedSettings, copy.decisionTools, copy.chipsAndTransfers]) {
      expect(screen.getByText(title).closest("details")).not.toHaveAttribute("open");
    }
    const advanced = screen.getByText(copy.advancedSettings).closest("details")!;
    for (const name of ["llm", "top100", "chip"]) {
      expect(advanced.querySelectorAll(`input[name="${name}"]`).length).toBeGreaterThan(0);
    }
    expect(within(advanced).getByText(copy.templatesTitle)).toBeInTheDocument();
    // The plan's own inputs are not in the advanced section, and each is on the page once.
    expect(advanced.querySelector('input[name="strategy"], input[name="window"]')).toBeNull();
    expect(container.querySelectorAll('input[name="window"]')).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Hesapla" })).toHaveLength(1);
    const tools = screen.getByText(copy.decisionTools).closest("details")!;
    expect(within(tools).getByText("Karar masam")).toBeInTheDocument();
    const chips = screen.getByText(copy.chipsAndTransfers).closest("details")!;
    expect(within(chips).getByText(MESSAGES.tr.memberResources.transfersTitle)).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)("prints no probability or percent in %s", (language) => {
    const { container } = show(language, {
      advice: twoMoves({
        moves: [move("gw-1", PALMER, FERNANDES, -0.4), move("gw-2", JESUS, BROBBEY, 1.2)],
        expected_gain_vs_hold: 0.8,
        solver_status: "FEASIBLE",
        optimality_gap: 0.5,
      }),
    });
    const match = (container.textContent ?? "").match(FORBIDDEN);
    expect(match, match ? `forbidden fragment: ${match[0]}` : undefined).toBeNull();
  });
});

describe("a chip strategy the service planned", () => {
  it.each(["tr", "en"] as const)(
    "names the Top 100 setting as a weight and its holding values in %s",
    (language) => {
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
      const advice: LeagueViewEnvelope<EntryAdvice> = {
        ...base,
        payload: {
          ...base.payload,
          chip: "wildcard",
          chip_strategy: {
            version: "model_opportunity_reservation_v1",
            mode: "auto",
            requested_chip: "auto",
            selected_chip: "wildcard",
            top100_weight: 20,
            objective_gap: 0.5,
            objective_basis: "selection_utility_with_chip_reserve",
            experimental: true,
            reservations: [
              {
                chip: "3xc",
                first_gameweek: GW,
                last_gameweek: 19,
                remaining_opportunities: 6,
                holding_value: 4.25,
                sample_min: 1,
                sample_max: 9,
              },
            ],
            limits: [],
          },
        },
      };
      const { container } = render(
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter>
            <AdviceCard
              shown={{ envelope: advice, origin: "computed" }}
              squad={SQUAD}
              rivalSquad={null}
            />
          </MemoryRouter>
        </LanguageProvider>,
      );
      const copy = MESSAGES[language].leagueMembers.chipStrategy;
      const section = container.querySelector('[data-testid="chip-strategy"]')!;
      expect(
        within(section as HTMLElement).getByRole("heading", { name: copy.title }),
      ).toBeTruthy();
      expect(section).toHaveTextContent(copy.holdingValue);
      expect(section).toHaveTextContent(MESSAGES[language].leagueMembers.top100Weight(20));
      expect(section.textContent).not.toContain("%");
    },
  );
});
