// Only for product copy owned by the repository, never member-supplied names.
//
// The standing rule: no member-facing page or payload, in either language, publishes a
// probability, a percentage of a probability, a quantile, a spread, a likelihood, a chance
// or odds. Expected points, an expected gap against a named rival, overlap counts and a
// price in points are the whole of what may be published.
//
// Two alternations carry an exception, and both are written into the pattern rather than
// kept as a list of blessed strings:
//
//   yuzde   The Turkish "yüzde" is the numerical term "per cent", but "yüzden" (as in "bu
//           yüzden", meaning therefore) begins with the same six letters. The negative
//           lookahead excludes only that causal word, so "yüzdesi" and "yüzdelik" are still
//           caught.
//   percent A per cent sign is a violation unless it belongs to an ownership share. The game
//           itself publishes ownership, so quoting it is a fact rather than a claim of ours.
//           The exception is spelled as ownership wording within forty characters on either
//           side of the sign; a per cent sign in any other company still matches.
const OWNERSHIP = "owned|ownership|sahipli";
const PERCENT_NOT_OWNERSHIP = `(?<!(?:${OWNERSHIP})[\\s\\S]{0,40})%(?![\\s\\S]{0,40}(?:${OWNERSHIP}))`;

export const AS_A_CHANCE = new RegExp(
  [
    PERCENT_NOT_OWNERSHIP,
    "probabilit",
    "olasıl",
    "\\bP\\(",
    "chance",
    "likelihood",
    "odds",
    "quantile",
    "spread",
    "percentage",
    "\\btail\\b",
    "ihtimal",
    "şans",
    "yüzde(?!n\\b)",
    "kantil",
    "yayılım",
    "\\bkuyruk\\b",
  ].join("|"),
  "i",
);
