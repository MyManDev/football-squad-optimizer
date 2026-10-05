/**
 * The example league as a page sees it: the directory entry the gate would provide, the
 * tree that reads it, and a wrapper that puts a component inside that league the way the
 * gate does on the site.
 */

import type { ReactNode } from "react";
import { vi } from "vitest";

import * as dataModule from "../features/league/data";
import { createLeagueTree, type LeagueTree } from "../features/league/data";
import type { PublishedLeague } from "../features/league/directory";
import { LeagueProvider } from "../features/league/LeagueProvider";
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
