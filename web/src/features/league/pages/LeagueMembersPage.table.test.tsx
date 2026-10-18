/**
 * The league table as direction D draws it (D-Lig): the column order, the gap to the
 * leader, the viewer's lime row, the score bug and the viewer's chips and chaser, which
 * exist only once the visitor has said who they are. No row carries a control to say so.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { writeViewerEntry } from "../identity/useViewerEntry";
import { LeagueMembersView } from "./LeagueMembersPage";
import { withLeague } from "../../../testSupport/league";

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
      <MemoryRouter initialEntries={["/league/352490/members"]}>
        {withLeague(<LeagueMembersView envelope={mockLeagueMembersEnvelope} {...props} />)}
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
    show({}, language);
    expect(document.querySelector('tr[aria-current="true"]')).toBeNull();
    expect(scoreBug()).toBeNull();
    expect(
      screen.queryByRole("heading", { name: MESSAGES[language].memberResources.chipsTitle }),
    ).toBeNull();
    expect(screen.queryByText(copy.followerLabel)).toBeNull();
  });

  it("carries no control on any row to say who the visitor is, and no line asking for it", () => {
    show({}, language);
    expect(screen.queryByRole("button", { name: /Bu benim|This is me/ })).toBeNull();
    expect(document.body).not.toHaveTextContent(/Bu benim|This is me/);
    expect(document.body).not.toHaveTextContent(/Hangisi sensin|Which one is you/);
  });

  it("marks the viewer's own row and fills the score bug from the published row", () => {
    writeViewerEntry({ leagueId: 352490, entryId: leader.entry_id });
    show({}, language);
    const own = rowOf(leader.manager_name!);
    expect(own).toHaveAttribute("aria-current", "true");
    expect(own).toHaveTextContent(`· ${copy.viewerYouBadge}`);
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
    writeViewerEntry({ leagueId: 352490, entryId: leader.entry_id });
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
    writeViewerEntry({ leagueId: 352490, entryId: leader.entry_id });
    const envelope = structuredClone(mockLeagueMembersEnvelope);
    envelope.payload.members.find((member) => member.entry_id === second.entry_id)!.total_points =
      null;
    show({ envelope }, language);
    const chaser = screen.getByText(copy.followerLabel, { exact: false });
    expect(chaser.textContent).toBe(`${copy.followerLabel} ${second.manager_name}.`);
  });

  it("ignores a squad document that belongs to someone else", () => {
    writeViewerEntry({ leagueId: 352490, entryId: leader.entry_id });
    show({ viewerSquad: mockEntrySquadEnvelopes[second.entry_id!]! }, language);
    expect(
      screen.queryByRole("heading", { name: MESSAGES[language].memberResources.chipsTitle }),
    ).toBeNull();
    expect(scoreBug()).not.toHaveTextContent(copy.bankLabel);
  });
});
