/**
 * What another feature may use from the league feature. The moves page checks a pasted
 * league id against the published directory and links to the members page, so it reads
 * those here instead of reaching into the league's modules; the league feature imports
 * nothing from the moves page.
 */
export { membersAddress } from "../../lib/leagueAddresses";
export { lookupPublishedLeague } from "./data";
