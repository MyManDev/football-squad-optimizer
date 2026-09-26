/**
 * What another feature may use from the league feature. The moves page checks a pasted
 * league id against the published members document, so it reads that one loader here
 * instead of reaching into `data.ts`; the league feature imports nothing from the moves page.
 */
export { loadLeagueMembers } from "./data";
