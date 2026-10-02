/**
 * Limits the producer publishes with a plan that the member page does not list. They stay
 * in the document; the page leaves them out, and leaves the heading out with them when
 * nothing else is stated. A limit that follows from something the member chose (a chip, a
 * Top 100 weight, an experimental model) is not here and is still shown.
 */
export const HIDDEN_STATED_LIMITS: ReadonlySet<string> = new Set([
  "The first week's projection is repeated over the later weeks, rescaled by each club's fixture count in that week relative to its count in the first week, from the captured calendar; a club with no fixture in the first week stays at zero all the way through, and the later weeks are not projected separately.",
  "Availability is applied once, from the capture: injuries, rotation and suspensions after it are not seen.",
  "Every week inside the window, the first included, is capped at one transfer (a wildcard week excepted); the one-week plan has no such cap.",
  "Prices are held at the captured values; no price change is modelled.",
  "No chip is offered inside the window. A finite window counts nothing for holding a chip back, so a planner that could reach one would spend it; chip timing is a season-long decision this window cannot price.",
]);

/** The published limits the page lists, in the producer's order. */
export function shownLimits(published: readonly string[] | null | undefined): string[] {
  return (published ?? []).filter((sentence) => !HIDDEN_STATED_LIMITS.has(sentence));
}
