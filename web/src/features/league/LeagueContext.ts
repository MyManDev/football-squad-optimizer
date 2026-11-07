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
  /**
   * The tree is built on the device from the FPL forwarder's documents, for a league the
   * site does not publish (or league 0, one team on its own): a compute request for its
   * member goes to the service's public route. Absent for a published league.
   */
  forwarded?: true;
}

export const LeagueContext = createContext<LeagueContextValue | null>(null);
