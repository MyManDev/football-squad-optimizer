/**
 * What another feature may use from the league feature. The moves page checks a pasted
 * league id against the published directory and opens the members page, where the visitor
 * says who they are, so it reads those here instead of reaching into the league's modules;
 * the league feature imports nothing from the moves page.
 */
export { FIND_YOURSELF, membersAddress } from "../../lib/leagueAddresses";
export { lookupPublishedLeague } from "./data";
