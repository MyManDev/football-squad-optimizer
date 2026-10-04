/**
 * The league a page is about, and the tree it reads. `LeagueProvider` fills it from the
 * address and the directory; `useLeague` reads it.
 */

import { createContext } from "react";

import type { LeagueTree } from "./data";
import type { PublishedLeague } from "./directory";

export interface LeagueContextValue {
  league: PublishedLeague;
  tree: LeagueTree;
}

export const LeagueContext = createContext<LeagueContextValue | null>(null);
