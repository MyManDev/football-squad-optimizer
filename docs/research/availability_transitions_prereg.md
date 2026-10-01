# How stated playing chances resolve by the next decision: protocol

Status: pre-registered, written before its first pair is read. It declares a count, not a
model. It changes no forecast, planner, default, member page or capture, and it promotes
nothing. Its question is the data side's (`docs/architecture/ownership.md`): what the
source said, and what it said next.

## Why this is written

Since fix7 the experimental football planner turns one held player's stated 25, 50 or 75
per cent chance of playing into two information branches for the second decision: eligible
with that probability, unavailable otherwise (`src/squadopt/live/football_observations.py`,
`captured_next_deadline_resolution_v1`). Its record says plainly that information timing is
an assumption (`docs/research/football_information_windows.md`). The stored captures can
say how often the assumption held: the decision capture of gameweek g carries the stated
chance, and the decision capture of g+1 carries how the same player stood when the next
decision was made. Nothing else is needed, and nothing else is read.

## Captures and pairs

- A **decision capture** of gameweek g is the latest stored `fpl-live` capture whose own open
  deadline is g (`next_open_deadline` on the capture's own bootstrap at its capture instant),
  the rule `docs/football_prospective_prereg.md` scores from. A capture without a bootstrap
  payload, or taken after every published deadline, is no decision capture.
- A **pair** is the decision captures of g and g+1. A gameweek with no following decision
  capture has no pair; it is listed as such, not counted as zero of anything.
- A pair is **prospective** when the earlier gameweek's deadline falls after this protocol
  merges, so its later state could not have been seen when the count was declared. Earlier
  pairs are **retrospective**: the 22 September captures already target GW6 and show how the
  GW5 doubtful players stood four days after the GW5 deadline. Retrospective pairs are
  reported, labelled, and never pooled with prospective ones. If this merges before the GW6
  decision capture (deadline 2026-10-10T10:00Z), the first prospective pair is GW6 to GW7.

## Population and outcome

The population of a pair is every player the earlier capture states at **25, 50 or 75**,
whatever his status, which is the set the planner's rule reads. Stated 0 and 100 are not
in it. The outcome is the later capture's row for the same player code, read by the
availability rule's own precedence (`captured_availability_rule_v1`): a stated chance wins
over the status, 100 is `available`, 0 is `out`, 25, 50 or 75 is `doubtful`; without a
chance, status `a` is `available`, `d` is `doubtful`, `i`, `s`, `u` and `n` are `out`. A
player the later capture no longer lists is `absent`; a status or chance the rule does not
know is `unknown`. Both are their own class. Nothing is read from a match.

## What is recorded

Per pair and per stated chance, and pooled over the three: the number of players stated,
the count in each of the five classes, each class's share with a two-sided 90 percent Wilson
interval, and the player codes in each class. Player codes let a count be checked against
the local capture; no note text and no name leaves the capture, and the record says so
(`news_text_included: false`). The runner is `scripts/measure_availability_transitions.py`.
It reads stored captures only, fetches nothing, fits nothing, and writes `record.json` and
`summary.md` into a fresh directory the operator names, under `artifacts/` by convention.
It never writes under `data/`, never touches a live store or the backend, and runs on no
machine without that machine's operator saying so.

## Readings

The runner may run after any decision capture; a decision capture of g+1 is the only
outcome a pair needs, and no match result is involved. Two readings are written up: after
the GW20 decision capture and after the GW38 decision capture, each as a committed record
with an index row (`docs/architecture/decisions/0003-measurement-artifacts.md`), pooling
prospective pairs only. Counts are reported at any size; an interval on fewer than ten
stated players is printed and called what it is. There is no verdict rule, because nothing
switches on this count.

## What a result licenses

Nothing by itself. The planner's rule reads the stated chance as the probability of being
eligible by the next decision; this protocol measures how often `available` was the next
state, and how often the answer was `doubtful` again, which that binary branch cannot
represent. A mapping from stated chance to next-deadline state may be proposed only from
the pooled prospective pairs, in its own declaration, through an explicit evidence contract
on the consumer's side (#632). Unmeasured chances acquire no number, and an interval that
includes the stated chance is not a confirmation of it.

## Deliberate exclusions

No news text, no model confidence, no club-news disposition, no archive season, no
2025-26 holdout, no member document, no outcome store. The stated chance is the source's
quantised field, not a probability this repository fitted. A capture taken long before its
deadline can predate the note that changed a player's chance; that is the lead time
`docs/capture_lead_time.md` measures, and it is why the decision capture, not any capture,
is read. Weeks without a stored capture produce no pair and no number.

## Falsifiers, written first

- If the pooled prospective `available` share for a stated chance sits far from that chance
  over many pairs, the planner's branch probabilities are not what the source means, and
  the consumer's rule needs its own evidence contract before it is called calibrated.
- If `doubtful` is a large share of next states, a two-branch resolution omits the state
  that happened most, and a later declaration must represent it.
- If `absent` or `unknown` is common, the later capture is not reading the same players,
  and the pairing rule, not the planner, is what to look at.
