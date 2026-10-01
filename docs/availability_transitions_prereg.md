# How stated playing chances resolve by the next decision: protocol

Status: pre-registered, written before its first pair is read. It declares a count, not a
model. It changes no forecast, planner, default, member page or capture, and it promotes
nothing. Its question is the data side's (`docs/architecture/ownership.md`): what the
source said, and what it said next. The delivered scope is this protocol and its runner;
nothing is run by this document, and who runs the runner, on which capture store, is the
separate answer the C2 question on #632 awaits.

## Why this is written

Since #909 the experimental football planner turns one held player's stated 25, 50 or 75
per cent chance of playing into two information branches for the second decision:
eligible with that probability, unavailable otherwise
(`src/squadopt/live/football_observations.py`, `captured_next_deadline_resolution_v1`).
Its record calls that an assumed information-resolution experiment, not a calibrated
recovery model (`docs/research/football_information_windows.md`), and the owner's fix8
note says information timing remains an assumption (#632). The stored captures can say
how often the assumption held: the decision capture of gameweek g carries the stated
chance, and the decision capture of g+1 carries how the same player stood when the next
decision was made. Nothing else is needed, and nothing else is read.

## Captures and pairs

- A **decision capture** of gameweek g is the latest stored `fpl-live` capture whose own open
  deadline is g (`next_open_deadline` on the capture's own bootstrap at its capture instant),
  the rule `docs/football_prospective_prereg.md` scores from. A capture without a bootstrap
  payload, one whose deadlines cannot be read, or one taken after every published deadline
  is no decision capture; the record lists it as skipped, with the reason.
- A **pair** is the decision captures of g and g+1, and the later one must follow the
  earlier deadline; a deadline that moved between the two is a different week, refused. A
  gameweek with no following decision capture has no pair; it is listed as such, not
  counted as zero of anything.
- A pair is **prospective** when the earlier gameweek's deadline falls after this protocol
  merges, so its later state could not have been seen when the count was declared. The
  runner cannot know that instant: it receives it as `--protocol-merged-at`, the committer
  timestamp of the merge commit on `develop`, and `--protocol-commit` names that commit in
  the record. Earlier pairs are **retrospective**: the 22 September captures already target
  GW6 and show how the GW5 doubtful players stood four days after the GW5 deadline.
  Retrospective pairs are reported, labelled, and never pooled with prospective ones. If
  this merges before the GW6 deadline (2026-10-10T10:00Z), the first prospective pair is
  GW6 to GW7.

## Population and outcome

The population of a pair is every player the earlier capture states at **25, 50 or 75**,
whatever his status. Those are the values the planner's rule branches on; the population
is the whole captured roster, not a member's squad, because the question is what the
source's figure means, not which one held player the planner picks (it keeps one, held,
with a positive forecast, per decision). Stated 0 and 100 are not in it.

The outcome is the later capture's row for the same player code, read by the precedence
and vocabulary of `captured_availability_rule_v1` and classified as this protocol's own
five classes (`availability_transitions_classes_v1`): a stated chance wins over the
status; 100 is `available`, 0 is `out`, and any chance between them, which the rule
applies as a partial multiplier, is `doubtful`; without a chance, status `a` is
`available`, `d` is `doubtful`, `i`, `s`, `u` and `n` are `out`. A player the later
capture no longer lists is `absent`. A status the rule does not know would stop that
rule; here it is `unknown`, and so is a chance outside 0 to 100, which the rule would
clip. Both are their own class. Nothing is read from a match.

## What is recorded

Per pair and per stated chance, and pooled over the three: the number of players stated,
the count in each of the five classes, each class's share with a two-sided 90 percent
Wilson interval, the share `available` among the resolved (`available` against
`available` plus `out`, the two states the planner's binary branch can represent), and
the player codes in each class. A cell with fewer than ten stated players is marked
`small_sample` and its row says thin. The record also carries the same cells **pooled over
the prospective pairs only**, per stated chance and over the three, with the number of
pairs pooled; that block is the reading's figure, and retrospective pairs never enter it.
Player codes let a count be checked against the local capture; no note text and no name
leaves the capture, and the record says so (`news_text_included: false`).

The runner is `scripts/measure_availability_transitions.py`. It reads stored captures
only, fetches nothing, fits nothing, reads no match outcome, and refuses a snapshot root
that is not a directory or holds no `fpl-live` capture. It writes `record.json` and
`summary.md` into a fresh directory the operator names with `--output`, measured before
the directory is created so a refusal leaves nothing behind; it refuses a destination
inside the snapshot root, under `data/` or under `docs/`. `--through-gameweek` fixes a
reading's pair set to the pairs whose later gameweek is at most that week, so the set is
the protocol's and not the run date's. It is to be run only by the operator of the
machine that holds the captures, and only once that operator has said so.

## Readings

Two readings are planned, after the GW20 and after the GW38 decision captures, subject to
the separate answer on #632 about who runs the runner and on which capture store. Each is
a committed record with an index row (`docs/architecture/decisions/0003-measurement-artifacts.md`):
`docs/research/availability_transitions_gw20.{md,json}` and
`docs/research/availability_transitions_gw38.{md,json}`, the runner's `record.json` and
`summary.md` copied into the record by the reading's pull request, run with
`--through-gameweek 20` and `38`. The reading's figure is the pooled prospective block;
per-pair cells and retrospective pairs are shown beside it. Counts are reported at any
size and thin intervals are marked. There is no verdict rule, because nothing switches on
this count.

## What a result licenses

Nothing by itself. The planner's rule reads the stated chance as the probability of being
eligible by the next decision; this protocol measures how often `available` was the next
state, how often the answer was `doubtful` again, which that binary branch cannot
represent, and the share available among the resolved. A mapping from stated chance to
next-deadline state may be proposed only from the pooled prospective block, in its own
declaration, through an explicit evidence contract on the consumer's side (#632).
Unmeasured chances acquire no number, and an interval that includes the stated chance is
not a confirmation of it.

## Deliberate exclusions

No news text, no model confidence, no club-news disposition, no archive season, no
2025-26 holdout, no member document, no outcome store. The stated chance is the source's
quantised field, not a probability this repository fitted. A capture taken long before its
deadline can predate the note that changed a player's chance; that is the lead time
`docs/capture_lead_time.md` measures, and it is why the decision capture, not any capture,
is read. Weeks without a stored capture produce no pair and no number. The captures this
protocol describes are on the owner's machine; this repository's own store holds two GW6
captures and no pair.

## What each pattern would mean

These are readings of the record, not thresholds; none of them switches anything.

- A pooled prospective `available` share for a stated chance whose interval sits clear of
  that chance over many pairs says the planner's branch probabilities are not what the
  source means; the share among the resolved says it without counting the unresolved
  against the chance. Either way the consumer's rule needs its own evidence contract
  before it is called calibrated.
- A large `doubtful` share says a two-branch resolution omits the state that happened
  most, and a later declaration must represent it.
- A common `absent` or `unknown` says the later capture is not reading the same players,
  and the pairing rule, not the planner, is what to look at.
