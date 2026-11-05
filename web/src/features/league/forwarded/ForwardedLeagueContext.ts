/**
 * The forwarded league a page is under (#983 step 4): a classic league the site does not
 * publish, opened from the FPL forwarder's standings. The league gate provides it for an
 * unlisted league that page 1 answered; an entry opened on its own has none.
 */

import { createContext, useContext } from "react";

export interface ForwardedLeague {
  leagueId: number;
  /** The league's name as FPL states it, or null when it states none. */
  leagueName: string | null;
}

export const ForwardedLeagueContext = createContext<ForwardedLeague | null>(null);

/** The forwarded league in context, or null outside one. */
export function useForwardedLeague(): ForwardedLeague | null {
  return useContext(ForwardedLeagueContext);
}
