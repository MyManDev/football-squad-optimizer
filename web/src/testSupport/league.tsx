/**
 * The example league as a page sees it: the directory entry the gate would provide, the
 * tree that reads it, and a wrapper that puts a component inside that league the way the
 * gate does on the site. `claimIn` and `forgetIdentity` set the visitor's identity the way
 * the two steps in front of the league pages do.
 */

import type { ReactNode } from "react";
import { vi } from "vitest";

import * as dataModule from "../features/league/data";
import { createLeagueTree, type LeagueTree } from "../features/league/data";
import type { PublishedLeague } from "../features/league/directory";
import { writeMemberClaim, type MemberClaim } from "../features/league/identity/memberClaim";
import { writeChosenLeague } from "../features/league/identity/useChosenLeague";
import { LeagueProvider } from "../features/league/LeagueProvider";
import type { HumanEntryView } from "../features/league/types";
import { mockLeagueMembersEnvelope } from "../fixtures/league";

const example = mockLeagueMembersEnvelope.payload;

// The real constructor, held before any test replaces the module's export.
const buildTree = createLeagueTree;

/** The example league, published under the legacy tree path as a site from before the directory. */
export const EXAMPLE_LEAGUE: PublishedLeague = {
  leagueId: example.league_id,
  leagueName: example.league_name,
  season: example.season,
  gameweek: example.gameweek,
  path: "league",
};

export const exampleTree: LeagueTree = createLeagueTree(EXAMPLE_LEAGUE);

export function withLeague(children: ReactNode, league: PublishedLeague = EXAMPLE_LEAGUE) {
  return <LeagueProvider league={league}>{children}</LeagueProvider>;
}

/**
 * The tree the next `LeagueProvider` hands down, with some of its reads replaced. The
 * provider builds its tree from the league it is given, so a test that wants a page to
 * read a document of its own replaces the reads here, before rendering; every read it
 * leaves alone is the real one. `vi.restoreAllMocks()` puts the real constructor back.
 */
export function stubTree(reads: Partial<Omit<LeagueTree, "league">>): LeagueTree {
  const tree: LeagueTree = { ...exampleTree, ...reads };
  vi.spyOn(dataModule, "createLeagueTree").mockImplementation((league) =>
    league.leagueId === EXAMPLE_LEAGUE.leagueId && league.path === EXAMPLE_LEAGUE.path
      ? tree
      : { ...buildTree(league), ...reads },
  );
  return tree;
}

const humans = example.members.filter(
  (member): member is HumanEntryView => member.member_kind === "human",
);

/** The example league's first human member: Deniz Aral, 35249001. */
export const EXAMPLE_MEMBER: HumanEntryView = { ...humans[0]! };

/**
 * The visitor entered `leagueId` and said they are `entryId` in it. The names come from the
 * example league's row for that member, and the league's name from the example league,
 * unless given; the member gate writes the published ones back once it reads the list.
 */
export function claimIn(
  entryId: number = EXAMPLE_MEMBER.entry_id,
  leagueId: number = EXAMPLE_LEAGUE.leagueId,
  names: Partial<Pick<MemberClaim, "managerName" | "teamName" | "leagueName">> = {},
): void {
  const row = humans.find((member) => member.entry_id === entryId);
  writeChosenLeague(leagueId);
  writeMemberClaim({
    leagueId,
    entryId,
    managerName: row?.manager_name ?? null,
    teamName: row?.team_name ?? null,
    leagueName: example.league_name,
    ...names,
  });
}

/** A first visit: no league entered and nobody claimed. */
export function forgetIdentity(): void {
  writeMemberClaim(null);
  writeChosenLeague(null);
}
