# FPL facts, coach news and football decisions

The official FPL bootstrap capture supplies player status, the source's playing
percentage, editorial text and its reported date for every represented club.
`fpl_information_v1` publishes selected player facts and capture coverage. It does
not publish the editorial text, and it does not turn the percentage into a
calibrated probability of starting. Zero and an unknown value remain different.
An empty news field with a retained date is reported as cleared text; this is not
proof that the player has recovered.

The page shows the capture time separately from the news date. It only reflects
the capture used by that decision. Server readiness does not establish freshness,
and this feature adds neither a polling service nor a new data scheduler.

## Coach evidence

The acquisition command's coding V3 request supplies the target season, gameweek,
deadline and observation time. Responses classify the fixture scope as upcoming
league, other competition, past, ambiguous or unspecified. The supplied classification is not sufficient for
a numerical change. The held source must independently establish its publication
time, quote span and applicable upcoming league wording. The target fixture must
also be the first league fixture after publication for that club. An intervening
match or an ambiguous double gameweek prevents the update.

The finite English scope rules deliberately leave unrecognised wording unapplied.
V1 and V2 coding responses and V2/V3 rotation tables remain readable; they do not
gain missing V4 source attestations by being read with newer code.

Both football forecast routes keep vague minute management separate from an
explicit full-match restriction. The latter can affect only the matched first
week and needs the corresponding component basis. Explicit absence uses the
eligibility path. Existing source availability is not multiplied twice. Neither
path derives a new numerical starter probability from model confidence or from a
categorical quote. Per-player outcomes explain accepted and withheld statements.

## Bounded collection

The existing registry, robots checks, origin restrictions and document bounds
still apply. Relevant first-team injury and upcoming-match article links have
priority; youth, women's and commercial links have lower priority. FPL player
coverage and the much smaller registered coach-news coverage are separate facts.

`capture_club_news` accepts `--max-model-calls` (default 3, range 0 to 20).
Configured providers make no automatic transport retries. A failed provider call
uses its allowance. `--previous-news-capture` may name an exact previous capture;
unchanged valid coding inputs reuse its response without a paid request. Reuse
requires matching target, roster, source bytes, media type, model, prompt and
request configuration. It preserves the original response and publication time.
A successful empty reply is not a transport failure or evidence of player absence.

Example, using operator-chosen private paths and a held roster capture:

```text
python -m scripts.capture_club_news --roster-snapshot <held-id> --snapshot-root <captures> --capture-root <new-captures> --settings-file <private-config> --club Liverpool --max-model-calls 1
```

## Forecast and component production

`build_football_forecast --with-components` produces the v1 forecast and its fixture
companion from one fit. Repeating `--training-season` creates an explicit allowed
population before archive reads. An excluded archive is not read or hashed. The
current season must also be listed to include its captured history. Its capture
must contain every required settled event from gameweek 1 through the previous week.
Bootstrap and fixtures alone are insufficient. Omitting the option retains the
existing training population, including 2025-26; it is not an exclusion policy.

The forecast and companion both record the selection and the fitted population.
The reader requires matching capture, calendar, model and forecast identity.
A malformed or mismatched companion is not reported as bound just because its
file digest exists. The generic snapshot reader still verifies every payload in
the explicitly selected capture; the season option is not a payload filter.

## Decision and planning behavior

`football_decision_information_v1` identifies the bound forecast, participation
policy and evidence. A changed revision can prompt the user to calculate again;
it does not rewrite the displayed answer or submit a computation automatically.
Different captures continue through the existing publication transition. This is
not a live news feed detached from the published squad.

The guarded football planner keeps three- and five-week windows and the user's
Top100 selection. Normal weeks can propose two transfers when both are covered by
banked free transfers. Purchase lots, bank and actual transfer hits still bind.
The first action cannot depend on which future news branch occurs. The baseline
candidate is retained; favorable and unfavorable news each receive a bounded
proposal budget and every candidate is evaluated against both branches.

Chip comparisons use the same expected lineup calculation, including automatic
substitutions and vice-captain recovery. Bench Boost does not add normal autosub
value a second time. The existing automatic chip-menu gate remains in place;
automatic chip plans do not branch on future news. No Top100 setting is silently
selected for the user.

## Acceptance boundaries

Acceptance checks must exercise successful, empty, failed, ambiguous and stale
evidence with deterministic source and provider fixtures. Worker/API checks must
validate the published facts and outcomes; browser checks must cover mobile
presentation and explicit recalculation.
These functional checks do not establish realized FPL points, predictive
superiority, calibrated news-arrival probabilities or a live coach-news effect.
Real provider and live release receipts must report those outcomes separately.
