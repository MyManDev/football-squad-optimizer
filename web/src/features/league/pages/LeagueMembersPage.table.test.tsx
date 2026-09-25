/**
 * The league table as direction D draws it (D-Lig): the column order, the gap to the
 * leader, the viewer's lime row, the score bug, the system's record beside the table and
 * the viewer's chips and chaser, which exist only once the visitor has said who they are.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { ScoreboardState } from "../components/karne";
import { writeViewerEntry } from "../identity/useViewerEntry";
import type { LeagueViewEnvelope, Scoreboard, ScoreboardGameweek } from "../types";
import { LeagueMembersView } from "./LeagueMembersPage";

afterEach(cleanup);
beforeEach(() => writeViewerEntry(null));

const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
const leader = humans[0]!;
const second = humans[1]!;

function show(
  props: Partial<Parameters<typeof LeagueMembersView>[0]> = {},
  language: Language = "tr",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/league/members"]}>
        <LeagueMembersView envelope={mockLeagueMembersEnvelope} {...props} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

/** The top bar's score bug, or null when the page shows none. */
function scoreBug() {
  return document.querySelector<HTMLElement>("header dl");
}

function rowOf(managerName: string) {
  return screen.getByRole("link", { name: managerName }).closest("tr")!;
}

function week(
  gameweek: number,
  ours: number | null,
  league: number | null,
  game: number | null,
  checked = true,
): ScoreboardGameweek {
  return {
    gameweek,
    deadline_utc: `2026-08-${10 + gameweek}T17:30:00Z`,
    finished: true,
    data_checked: checked,
    average_entry_score: game,
    highest_score: null,
    ours:
      ours === null
        ? null
        : {
            net: ours,
            xi: ours,
            hits: 0,
            projected: 50,
            mode: "live",
            scoring_basis: "named_eleven_no_autosubs",
            vice_captain_named: false,
          },
    top100: null,
    members: [],
    members_mean_net: league,
    members_counted: 15,
  };
}

function board(weeks: ScoreboardGameweek[], leagueId = 352490): ScoreboardState {
  const envelope: LeagueViewEnvelope<Scoreboard> = {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-09-22T15:12:00Z",
    source_kind: "live",
    payload: {
      season: "2026-27",
      league_id: leagueId,
      source_snapshot_id: "fpl-live-20260922T151216Z-000000000000",
      captured_at_utc: "2026-09-22T15:12:16Z",
      cohort_snapshot_id: null,
      cohort_picks_snapshot_id: null,
      registered_members: 15,
      histories_held: 15,
      gameweeks: weeks,
      cumulative: {
        through_gameweek: weeks.length,
        gameweeks: weeks.map((item) => item.gameweek),
        ours_net: null,
        ours_gameweeks: [],
        ours_basis: null,
        ours_excluded_gameweeks: [],
        members_mean_total_points: null,
        members_gameweeks: [],
        members_counted: 15,
        average_entry_score: null,
      },
    },
  };
  return { status: "ready", envelope };
}

describe.each(["tr", "en"] as const)("the league table in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;

  it("reads rank, movement, team, last week, total and the gap to the leader, in that order", () => {
    show({}, language);
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual([
      copy.rank,
      copy.movement,
      copy.team,
      `${copy.lastWeekLabel}${copy.gameweekNetPointsFor(1)}`,
      copy.total,
      copy.leaderGap,
    ]);
    // The last week's header names the week and its net basis to a screen reader.
    expect(headers[3]).toHaveAccessibleName(copy.gameweekNetPointsFor(1));
    // The team is the first line of its cell and the manager, the link, the second.
    const cells = within(rowOf(second.manager_name!)).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent(`${second.team_name}${second.manager_name}`);
  });

  it("measures each gap from the leader's total, and the leader reads 'leader'", () => {
    show({}, language);
    const gap = (managerName: string) =>
      within(rowOf(managerName)).getAllByRole("cell").at(-1)!.textContent;
    expect(gap(leader.manager_name!)).toBe(copy.leaderMark);
    expect(gap(second.manager_name!)).toBe(String(leader.total_points! - second.total_points!));
    // A member with no published total has no gap: a dash, never the whole lead.
    const unknown = humans.findIndex((member) => member.total_points === null);
    expect(unknown).toBeGreaterThan(0);
    const unknownRow = screen.getAllByRole("row")[unknown + 1]!;
    expect(within(unknownRow).getAllByRole("cell").at(-1)!.textContent).toBe("—");
    expect(document.body.textContent).not.toMatch(AS_A_CHANCE);
  });

  it("has no gaps at all when the leader's own total is unknown", () => {
    const envelope = structuredClone(mockLeagueMembersEnvelope);
    envelope.payload.members[0]!.total_points = null;
    show({ envelope }, language);
    const gaps = screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell").at(-1)!.textContent);
    expect(new Set(gaps)).toEqual(new Set(["—"]));
  });

  it("gives no row a lime fill, a score bug or chips before the visitor says who they are", () => {
    show({ scoreboard: board([week(1, 26, 54.3, 50)]) }, language);
    expect(document.querySelector('tr[aria-current="true"]')).toBeNull();
    expect(scoreBug()).toBeNull();
    expect(
      screen.queryByRole("heading", { name: MESSAGES[language].memberResources.chipsTitle }),
    ).toBeNull();
    expect(screen.queryByText(copy.followerLabel)).toBeNull();
    expect(
      screen.getAllByRole("button", { name: new RegExp(`^${copy.viewerSelect}: `) }),
    ).toHaveLength(humans.length);
    // Every row's button is named for that row, starting with the words it shows, so no
    // two of them share one name (getByRole finds exactly one for each member).
    for (const member of humans) {
      const name = copy.viewerSelectFor(
        member.manager_name ?? copy.unknownMember,
        member.team_name ?? copy.unknownTeam,
      );
      expect(screen.getByRole("button", { name })).toHaveTextContent(copy.viewerSelect);
    }
    expect(screen.getByText(copy.viewerPrompt, { exact: false })).toBeInTheDocument();
  });

  it("marks the viewer's own row and fills the score bug from the published row", () => {
    writeViewerEntry(leader.entry_id);
    show({}, language);
    const own = rowOf(leader.manager_name!);
    expect(own).toHaveAttribute("aria-current", "true");
    expect(own).toHaveTextContent(`· ${copy.viewerYouBadge}`);
    expect(
      within(own).queryByRole("button", { name: new RegExp(`^${copy.viewerSelect}`) }),
    ).toBeNull();
    expect(document.querySelectorAll('tr[aria-current="true"]')).toHaveLength(1);
    // Rank among the members, total and the week net of its hit; without the squad
    // document there is no bank and no free-transfer cell, rather than a 0.
    const bug = scoreBug()!;
    expect(bug).toHaveTextContent(copy.rankLabel);
    expect(within(bug).getByText(`${leader.rank}/${humans.length}`)).toBeInTheDocument();
    expect(within(bug).getByText(String(leader.total_points))).toBeInTheDocument();
    expect(bug).not.toHaveTextContent(copy.bankLabel);
    expect(bug).not.toHaveTextContent(copy.freeTransfersLabel);
  });

  it("adds the viewer's chips, bank and chaser once their squad document is read", () => {
    writeViewerEntry(leader.entry_id);
    const squad = mockEntrySquadEnvelopes[leader.entry_id!]!;
    show({ viewerSquad: squad }, language);
    const resources = MESSAGES[language].memberResources;
    const chips = screen.getByRole("heading", { name: resources.chipsTitle }).closest("section")!;
    expect(chips).toHaveTextContent(resources.halves.first_half);
    expect(chips).toHaveTextContent(copy.chipNames.wildcard);
    expect(chips).toHaveTextContent(copy.chipLine.available);
    expect(scoreBug()).toHaveTextContent(copy.bankLabel);
    // This document does not know the free transfers, so the bug has no cell for them.
    expect(squad.payload.free_transfers_known).toBe(false);
    expect(scoreBug()).not.toHaveTextContent(copy.freeTransfersLabel);
    expect(chips).toHaveTextContent(copy.chipsHalfNote);
    const chaser = screen.getByText(copy.followerLabel, { exact: false });
    expect(chaser).toHaveTextContent(second.manager_name!);
    expect(chaser).toHaveTextContent(
      copy.followerBehind(String(leader.total_points! - second.total_points!)),
    );
  });

  it("names the chaser without a distance, and without a stray comma, when a total is unknown", () => {
    writeViewerEntry(leader.entry_id);
    const envelope = structuredClone(mockLeagueMembersEnvelope);
    envelope.payload.members.find((member) => member.entry_id === second.entry_id)!.total_points =
      null;
    show({ envelope }, language);
    const chaser = screen.getByText(copy.followerLabel, { exact: false });
    expect(chaser.textContent).toBe(`${copy.followerLabel} ${second.manager_name}.`);
  });

  it("ignores a squad document that belongs to someone else", () => {
    writeViewerEntry(leader.entry_id);
    show({ viewerSquad: mockEntrySquadEnvelopes[second.entry_id!]! }, language);
    expect(
      screen.queryByRole("heading", { name: MESSAGES[language].memberResources.chipsTitle }),
    ).toBeNull();
    expect(scoreBug()).not.toHaveTextContent(copy.bankLabel);
  });
});

describe.each(["tr", "en"] as const)("the system's record beside the table in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;
  const scoreboard = MESSAGES[language].leagueScoreboard;

  it("shows every finished week, 'no record' for a missing one, and never a zero bar", () => {
    show(
      {
        scoreboard: board([
          week(1, 26, 54.2667, 50),
          week(2, null, 86.2667, 81),
          week(3, 74, 46.6667, 48, false),
        ]),
      },
      language,
    );
    const karne = screen.getByRole("region", { name: copy.karneTitle });
    expect(karne).toHaveTextContent(copy.karneLede);
    expect(karne).toHaveTextContent(copy.karneCaption);
    const weeks = within(karne).getAllByRole("img");
    expect(weeks).toHaveLength(3);
    expect(weeks[1]).toHaveTextContent(copy.karneNone);
    expect(weeks[1]).toHaveAccessibleName(
      new RegExp(`${copy.karneOurs} ${copy.karneNone}`.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
    expect(weeks[1]!.querySelectorAll("[data-series='ours'] [style]")).toHaveLength(0);
    expect(weeks[0]).toHaveTextContent(language === "tr" ? "54,3" : "54.3");
    // A provisional week says so beside its name.
    expect(karne).toHaveTextContent(scoreboard.provisional);
    expect(karne.textContent).not.toMatch(AS_A_CHANCE);
    // The system's net is on the named-eleven basis, and the record says so.
    expect(karne).toHaveTextContent(copy.karneNamedEleven);
    // No week here was recorded after its deadline, so nothing is marked replay.
    expect(karne).not.toHaveTextContent(copy.karneReplayNote);
  });

  it("marks a week the system recorded after its deadline as replay", () => {
    const replay = week(2, 68, 79.7, 70);
    replay.ours!.mode = "replay";
    show({ scoreboard: board([week(1, 26, 54.3, 50), replay]) }, language);
    const karne = screen.getByRole("region", { name: copy.karneTitle });
    const weeks = within(karne).getAllByRole("img");
    expect(weeks[1]).toHaveAccessibleName(new RegExp(`\\(${copy.karneReplay}\\)`));
    expect(weeks[0]).not.toHaveAccessibleName(new RegExp(copy.karneReplay));
    expect(within(karne).getAllByText(copy.karneReplay)).toHaveLength(1);
    expect(karne).toHaveTextContent(copy.karneReplayNote);
  });

  it("keeps the whole scoreboard, with its basis and modes, one click away and closed", () => {
    show({ scoreboard: board([week(1, 26, 54.3, 50)]) }, language);
    // A wide table: the page lays it out under both columns, not in the record's column.
    const full = screen.getByText(copy.karneFull).closest("details")!;
    expect(screen.getAllByText(copy.karneFull)).toHaveLength(1);
    expect(full.open).toBe(false);
    expect(within(full).getByRole("table", { name: scoreboard.caption })).toBeInTheDocument();
    expect(full).toHaveTextContent(MESSAGES[language].scoreboardComparisons.legacy);
    expect(full).toHaveTextContent(scoreboard.modeNote);
  });

  it.each([
    [{ status: "pending" } as const, "loading"],
    [{ status: "missing" } as const, "notPublished"],
    [{ status: "error" } as const, "notAvailable"],
  ] as const)("says so quietly while the scoreboard is %j", (state, key) => {
    show({ scoreboard: state }, language);
    const karne = screen.getByRole("region", { name: copy.karneTitle });
    expect(karne).toHaveTextContent(scoreboard[key]);
    expect(within(karne).queryAllByRole("img")).toHaveLength(0);
    expect(screen.queryByText(copy.karneFull)).toBeNull();
  });

  it("shows nothing from another league's scoreboard", () => {
    show({ scoreboard: board([week(1, 26, 54.3, 50)], 1) }, language);
    expect(screen.queryByRole("region", { name: copy.karneTitle })).toBeNull();
    expect(screen.queryByText(copy.karneFull)).toBeNull();
  });
});
