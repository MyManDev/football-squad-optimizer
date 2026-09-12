# `rotation_evidence_v2` — the contract

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
| 17 | `rotation_claim_unresolved` | boolean | **never absent.** True = a claim was made about him and its citation could not be verified |
| 18 | `rotation_disposition` | string, closed | missing **only** where column 16 is False |
| 19 | `rotation_claim_source_sha256` | string | no claim, or the claim came from the feed alone |
| 20 | `rotation_claim_span_start` | Int64 | no located sentence |
| 21 | `rotation_claim_span_end` | Int64 | no located sentence. 20-21 are byte offsets into the hashed source bytes |
| 22 | `rotation_claim_published_at_utc` | string | **the source carried no dateline.** Never substituted with the fetch instant |
| 23 | `rotation_claim_published_precision` | string, closed | `instant` / `day` / `unknown` |
| 24 | `rotation_claim_speaker` | string, closed | `manager` / `club_official` / `club_statement` / `unattributed`. Never a person's name |
| 25 | `model_identifier` | string | no model was involved in this row |
| 26 | `prompt_sha256` | string | no model was involved |
| 27 | `model_response_sha256` | string | no model was involved, or it said nothing about him. **This player's club's** response — see below |
| 28 | `model_evidence_observed` | boolean | **never absent.** False = the model produced no disposition for him at all |
| 29 | `fixture_context_midweek` | boolean | **never absent** — the calendar could not answer, so the build refused instead |

## Four states, not three

Columns 15, 16 and 17 are read together, and the reason column 17 exists is that without it
the fourth state was indistinguishable from the second:

| | `club_source_covered` | `rotation_claim_observed` | `rotation_claim_unresolved` |
| --- | --- | --- | --- |
| his club was never read | False | False | False |
| read, and nothing was said about him | True | False | False |
| something was said, the citation could not be verified | True | False | **True** |
| something was said and it was located | True | True | False |

The third row is a **source error**: the model wrote about him and the quote it gave could not
be found in the bytes it cites, so no disposition is carried. Before column 17 he appeared as
the second row, which asserts a silence that never happened.

One unverifiable citation costs one claim. A club whose *every* claim lost its citation is
dropped from `clubs_covered` — nothing it said survives into evidence, so calling it covered
would assert that its page was read into the table when none of it was. A club that was read
and genuinely said nothing has no claims either way and stays covered.

### `rotation_disposition`, in full

`not_addressed`, `no_statement`, `stated_expected_to_start`, `stated_expected_absent`,
`stated_rotation_risk`, `stated_returning_from_injury`, `stated_minutes_limited`, `ambiguous`.

A closed list, deliberately. It cannot invent a nuance the source did not have, and it cannot
become a number.

### Why 16 and 27 are both here

They are computed independently and they agree on every row today, because the model is
currently the only source of a disposition. They are kept apart because a later feed-derived
disposition would set 16 without 27, and a table that had aliased them could not say so.

### Provenance is per club, and the instrument is not

A model is called once per club, so a week holds as many responses as clubs it read. Column 26
is the digest of **that player's club's** response. A single digest written across every row
would give an Arsenal player a citation into bytes that never mentioned him — and the digest
would verify, which is the worst kind of wrong.

Columns 24 and 25 stay single-valued. Which model answered and which question it was asked are
facts about the instrument, not about a club, and the manifest states one of each. A week
answered by two models, served by two model versions, or asked under two prompts is therefore
**refused** rather than recorded: it is a mixture the manifest cannot express, and a week whose
claims came from somewhere other than the model the manifest names is not a week anyone can
check. Same reasoning as the coding call's refusal to declare a fallback model.

The manifest's `response_sha256s` lists every response the week holds, sorted and without
repeats. Deduplicated because one response can legitimately cover several clubs — the fixture
provider answers once for all of them — and listing the same digest twice would imply a second
call there never was.

A claim placed on a player whose club has no recorded response refuses the whole week, naming
every such club at once. A disposition whose response cannot be named is traceable to no bytes
at all.

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

The name is `rotation_evidence_v2_<season>_gw<NN>_<capture digest>`, so a rehearsal earlier in
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

## The model call

How the coding response is produced, what the prompt asks for, and why the model is never
asked for a byte offset: `docs/rotation_claim_coding.md`.
