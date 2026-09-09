# `rotation_evidence_v1` — the contract

The sibling of `phase_b_evidence_contract.md`, for the rotation lane. One CSV and one
manifest per decision week, written exactly once, read by the member-facing card and by the
owner's lane. This document is the contract; `src/squadopt/features/rotation_evidence.py` is
its implementation and `rotation_evidence_artifact.py` is what refuses a pair that does not
keep it.

**What it is not.** It is not a measurement, so it owes no row in `measurements_index.md`.
It is an evidence handoff, like Phase B's: the table itself stays in the evidence tier
(`artifacts/rotation/`, gitignored) because it is derived from licence-restricted captures,
and the committed half is this document.

## The three rules the table exists to keep

**1. The claim is categorical.** `rotation_disposition` is one of eight declared values or it
is missing. There is no probability, likelihood, chance, score, confidence or `p_start`
column, and there will not be one: a generated number of that kind is forbidden on a
member-facing surface in either language *and* is an unmeasured claim besides. A `confidence`
column is a probability wearing a different hat, which is why it sits in the forbidden set
beside the obvious names — and why that set is checked against the schema at **import time**,
not only against a table at export time.

**2. The citation is a pointer, not a quote.** Columns 18-20 carry the source document's
SHA-256 and a byte span into it. The card resolves them against the locally held snapshot
bytes when it renders. That is how a member reads the manager's own words while this table
carries none of them, and how the words shown are provably the words captured: the digest is
checked before the offsets, so a document that has changed since resolves to nothing rather
than to different words presented as the source's own.

**3. Absent is not zero, and it is not False.** Every column below states what its absence
means. Two flags are never absent at all, because each separates "did not happen" from "was
not observed", and a missing value would collapse the distinction it exists to keep.

## Completeness

**One row per roster player in the decision capture, always**, and `row_count == roster_size`
in the manifest, checked on read. Phase B can check an arithmetic identity — its counts sum to
`11 × 100` — because elite picks have a known total. A model's coverage has no such total, so
this is the honest replacement: every roster player gets a row, and the flags say what was and
was not observed for him. A table with a player quietly missing would look complete otherwise.

## The chain is frozen before the decision

Every club document must have been fetched **strictly before** the decision capture was
taken. A week that breaks that is refused, not published with a caveat.

This is a rule about the *method*, which is why no column records it. `timing_verified`
(column 8) is a fact about a claim — every instant it rests on is earlier than the deadline.
This is a fact about the order things happened in: if the club bytes were fetched after the
capture was taken, then whoever fetched them could have looked at the capture first, noticed
a player who looked wrong, and gone hunting for words about him. That is not partially true
on some rows, so the build refuses.

**What the refusal does not cover.** The model's own call instant. A response carries no
timestamp, and the club-news capture reaches the builder as an identifier rather than as a
snapshot, so there is nothing to compare. That half closes where the response is written
into a capture with its own stamped instant — until then, this document says so rather than
letting a reader assume the check is stronger than it is.

## Columns, in the one order they are ever written or read

| # | column | dtype | absent (`pd.NA`) means |
|---|---|---|---|
| 1 | `contract_version` | string | never absent |
| 2 | `season` | string | never absent — declared by the caller, never inferred from a payload |
| 3 | `target_gameweek` | int64 | never absent |
| 4 | `player_id` | int64 | never absent. The platform's persistent `code`, never the per-season element id: a claim recorded this week is read again next season |
| 5 | `captured_at_utc` | string | never absent — the decision capture's stamped instant |
| 6 | `deadline_timestamp_utc` | string | never absent |
| 7 | `source_snapshot_ids` | string | never absent. Only the captures **this row** was read from; a capture that contributed nothing to it is not one of its sources |
| 8 | `timing_verified` | boolean | **never absent** — every instant this row rests on is strictly before the deadline |
| 9 | `feed_status` | string | field missing from the payload → the build refuses |
| 10 | `feed_chance_of_playing_next_round` | Int64 | **the feed stated no number.** Not 100, not 0 |
| 11 | `feed_news_state` | string, closed | `never_flagged` / `cleared` / `flagged`. Field missing → refuse |
| 12 | `feed_news_added_utc` | string | the player has never been flagged |
| 13 | `feed_scout_risk_count` | Int64 | the field was absent from the payload → refuse. `0` means present and empty |
| 14 | `feed_scout_news_link_present` | boolean | field absent → refuse |
| 15 | `club_source_covered` | boolean | **never absent.** False = no document was read for this player's club this week |
| 16 | `rotation_claim_observed` | boolean | **never absent.** False = the process ran and produced no disposition for him |
| 17 | `rotation_disposition` | string, closed | missing **only** where column 16 is False |
| 18 | `rotation_claim_source_sha256` | string | no claim, or the claim came from the feed alone |
| 19 | `rotation_claim_span_start` | Int64 | no located sentence |
| 20 | `rotation_claim_span_end` | Int64 | no located sentence. 19-20 are byte offsets into the hashed source bytes |
| 21 | `rotation_claim_published_at_utc` | string | **the source carried no dateline.** Never substituted with the fetch instant |
| 22 | `rotation_claim_published_precision` | string, closed | `instant` / `day` / `unknown` |
| 23 | `rotation_claim_speaker` | string, closed | `manager` / `club_official` / `club_statement` / `unattributed`. Never a person's name |
| 24 | `model_identifier` | string | no model was involved in this row |
| 25 | `prompt_sha256` | string | no model was involved |
| 26 | `model_response_sha256` | string | no model was involved, or it said nothing about him |
| 27 | `model_evidence_observed` | boolean | **never absent.** False = the model produced no disposition for him at all |
| 28 | `fixture_context_midweek` | boolean | **never absent** — the calendar could not answer, so the build refused instead |

### `rotation_disposition`, in full

`not_addressed`, `no_statement`, `stated_expected_to_start`, `stated_expected_absent`,
`stated_rotation_risk`, `stated_returning_from_injury`, `stated_minutes_limited`, `ambiguous`.

A closed list, deliberately. It cannot invent a nuance the source did not have, and it cannot
become a number.

### Why 16 and 27 are both here

They are computed independently and they agree on every row today, because the model is
currently the only source of a disposition. They are kept apart because a later feed-derived
disposition would set 16 without 27, and a table that had aliased them could not say so.

### `feed_news_state`, and why three

A player who has never been flagged carries no stamp at all. A player who was flagged and has
since been cleared carries an empty note with the stamp still on it. "Nothing is wrong with
him" and "nobody has said anything about him" are different facts about different players, and
a two-state reading would merge them.

## Manifest

Every field is required on read; a missing one refuses the pair, because the manifest is what
makes the table checkable and one with a hole in it checks less than it claims.

`contract_version`, `artifact_contract_version`, `season`, `target_gameweek`,
`deadline_timestamp_utc`, `generated_at_utc`, `repository_commit`, `table_file`,
`table_sha256`, `row_count`, `roster_size`, `roster_snapshot_id`, `source_snapshot_ids`,
`clubs_declared`, `clubs_covered`, `documents_read`, `document_sha256s`, `model_identifier`,
`model_version`, `prompt_sha256`, `response_sha256s`, `claims_coded`, `claims_ambiguous`,
`players_not_addressed`.

**One check is weaker than Phase B's, and named rather than hidden.** `source_snapshot_ids`
varies by row here: a player nobody wrote about was read from the decision capture alone.
Phase B's provenance is constant per table, so its reader compares the manifest against one
row's value; this one compares the manifest against the **union** over rows.

## Forbidden columns

Everything the Phase B export forbids — `entry`, `entry_id`, `entry_name`, `player_name`,
`manager_name`, `team_name`, `news` — plus `quote`, `text`, `snippet`, `headline`, `title`,
`url`, `source_url`, `manager`, `speaker_name`, `reason`, `notes`, `summary`, `rationale`,
`probability`, `likelihood`, `chance`, `score`, `confidence`, `p_start`.

The last group matters as much as the first.

## Create-once, and what a replay may differ by

The CSV is completed and fsynced in a sibling temporary file, then published with a
no-overwrite hard link; a losing writer compares its own bytes with the winner's and reports a
replay when they agree. The manifest goes through the same writer as every other measurement
document, where a replay may differ by the wall clock and nothing else. An artifact with
different content under the same name is refused, never overwritten. The export refuses a
dirty working tree, so the commit it records actually reproduces the bytes.

The name is `rotation_evidence_v1_<season>_gw<NN>_<capture digest>`, so a rehearsal earlier in
the week is a different artifact from the real run rather than a silent overwrite of it. The
digest is the capture the claims came from; while the synthetic fixture stands in for a live
source the claims are fixed, so the decision capture is what varies and names the file
instead. The manifest records both, so which one named it is never a guess.

## `fixture_context_midweek`, and the refusal behind it

True when the player's club has a kickoff in the four days before the deadline. This is the
first consumer of the captured `kickoff_time_utc`, which the fixture contract makes nullable
precisely because a fixture can be assigned to a gameweek before its time is confirmed.

So coverage is checked before the answer is given: if any fixture in the target gameweek or the
one before it has no kickoff time, the build **refuses**. A `False` that meant "we could not
tell" would be the same failure this table is built to avoid, one column over.

The column is derived here and is **not** added to `FIXTURE_COLUMNS`, which rejects any column
the fixture contract does not define — a derived quantity belongs in the step that aggregates,
not in the stored table.

## Three clocks, and the one that is unbounded

`captured_at_utc` bounds the capture. `generated_at_utc` bounds the artifact. A model has a
third that neither covers: what it knew at call time, from training data of any vintage.
**Nothing can bound that, and this document does not pretend otherwise.**

What the manifest can do, and does, is record the exact prompt digest, the model identifier and
version, and every source document digest, so that *"the claim is traceable to bytes we
captured at time T"* is checkable rather than asserted.

The ordering rule above is what bounds the first two clocks against each other; it does not
touch the third, and nothing can.

A related limit, stated for the same reason: a `day`-precision dateline is **not** compared
against the deadline. It names a calendar day and no time, so testing it against an instant
would require inventing one, and the invented time would decide the answer. Such a row's
`timing_verified` rests on the capture and fetch instants, which are ours and are exact.

## Two unverified field names

`scout_risks` and `scout_news_link` (columns 13-14) are read under those names on the strength
of the lane brief; no capture has been read here to confirm them. The refusal in column 13-14's
"absent means" is what keeps that honest — if the source spells them differently, the first
real capture stops with the names it was looking for rather than quietly reporting that nobody
has any risks.
