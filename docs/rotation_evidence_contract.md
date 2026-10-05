# `rotation_evidence_v4` — the contract

The sibling of `phase_b_evidence_contract.md`, for the rotation lane. One CSV and one
manifest per decision capture and news source, written exactly once, read by the
member-facing card and by the owner's lane. This document is the contract;
`src/squadopt/features/rotation_evidence.py` is
its implementation and `rotation_evidence_artifact.py` is what refuses a pair that does not
keep it.

**What it is not.** It is not a measurement, so it owes no row in `measurements_index.md`.
It is an evidence handoff, like Phase B's: the table itself stays in the evidence tier
(`artifacts/rotation/`, gitignored) because it is derived from licence-restricted captures,
and the committed half is this document.

## The three rules the table exists to keep

**1. The model claim is categorical.** `rotation_disposition` is one of nine declared values
or is missing. This table adds no generated probability, confidence or score. The separately
named `feed_chance_of_playing_next_round` preserves the official feed's stated value; it is
not a model estimate or a calibration result. Forbidden generated field names are checked
against the schema at import time and on artifact read.

**2. The citation is a pointer, not a quote.** Columns 19-21 carry the source document's
SHA-256 and a byte span into it. The card resolves them against the locally held snapshot
bytes when it renders. That is how a member reads the manager's own words while this table
carries none of them, and how the words shown are provably the words captured: the digest is
checked before the offsets, so a document that has changed since resolves to nothing rather
than to different words presented as the source's own.

**3. Absent is not zero, and it is not False.** Every column below states what its absence
means. Observation and attestation flags are never absent, because a missing value would
collapse "did not happen" and "was not verified".

## Completeness

**One row per roster player in the decision capture, always**, and `row_count == roster_size`
in the manifest, checked on read. Phase B can check an arithmetic identity — its counts sum to
`11 × 100` — because elite picks have a known total. A model's coverage has no such total, so
this is the honest replacement: every roster player gets a row, and the flags say what was and
was not observed for him. A table with a player quietly missing would look complete otherwise.

## The chain is frozen before the decision

Every club document must have been fetched **strictly before** the decision capture. For a
captured source, the completed news capture must also precede that decision: the acquisition
writer stamps it after coding, and the exporter compares its timestamp before building the
table. The manifest records `club_news_snapshot_id` and `club_news_captured_at_utc`; the
artifact reader checks the completed-capture ordering again, including when there are zero
claims. A synthetic fixture has no provider call and does not acquire that provenance.

`timing_verified` separately says the decision capture, fetch instants and any exact claim
publication instant are strictly before the decision deadline. It does not make a day-only
dateline exact or establish that a statement applies to this fixture.

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
| 15 | `club_source_covered` | boolean | **never absent.** False = the club did not retain read-and-coded coverage; see the coverage rules below |
| 16 | `rotation_claim_observed` | boolean | **never absent.** False = no resolved disposition is carried for him; read with columns 15 and 17 |
| 17 | `rotation_claim_unresolved` | boolean | **never absent.** True = an unverified citation or conflicting claims resolved to this player |
| 18 | `rotation_disposition` | string, closed | missing **only** where column 16 is False |
| 19 | `rotation_claim_source_sha256` | string | no observed claim |
| 20 | `rotation_claim_span_start` | Int64 | no located sentence |
| 21 | `rotation_claim_span_end` | Int64 | no located sentence. 20-21 are byte offsets into the hashed source bytes |
| 22 | `rotation_claim_published_at_utc` | string | no claim or no admitted publication date. Never substituted with the fetch instant |
| 23 | `rotation_claim_published_precision` | string, closed | no claim; otherwise `instant` / `day` / `unknown` |
| 24 | `rotation_claim_speaker` | string, closed | no claim; otherwise `manager` / `club_official` / `club_statement` / `unattributed`. Never a person's name |
| 25 | `model_identifier` | string | no model instrument recorded; otherwise repeated across the roster, not evidence that this player was mentioned |
| 26 | `prompt_sha256` | string | no model instrument recorded |
| 27 | `model_response_sha256` | string | no model was involved, or it said nothing about him. **This player's club's** response — see below |
| 28 | `model_evidence_observed` | boolean | **never absent.** False = no resolved model disposition is carried for him |
| 29 | `fixture_context_midweek` | boolean | **never absent** — the calendar could not answer, so the build refused instead |
| 30 | `rotation_claim_fixture_scope` | string, closed | no observed claim |
| 31 | `rotation_claim_scope_verified` | boolean | **never absent.** False = no verified binding to the target decision's next league fixture |
| 32 | `rotation_claim_publication_verified` | boolean | **never absent.** False = the stated date was not verified against held source metadata |
| 33 | `rotation_claim_publication_source` | string, closed | no verified metadata source recorded |
| 34 | `rotation_claim_publication_source_sha256` | string | no recorded publication metadata source; present together with column 33 |

V4 has exactly these 34 columns. The reader also accepts the 29-column V2 and V3 table
contracts with the supported export manifest contract. V2 retains its eight-value
disposition vocabulary; V3 adds `stated_full_match_unavailable`. Legacy rows do not acquire
V4 attestations merely by being read.

### Source attestation is separate from a located citation

`rotation_claim_fixture_scope` is `upcoming_premier_league`, `other_competition`, `past`,
`ambiguous` or `unspecified`. Only the first can have `scope_verified=True`. The current
finite English source check requires explicit unconditional wording. Absence, full-match
inability and rotation-risk restrictions must name the player and the relevant predicate
in the same complete cited clause. Unsupported aliases, pronouns, training-only wording,
other competitions, past matches and uncertain statements do not authorize those changes.
The cited span must also be a whole sentence of the held source, by the same rule the
manager-word reader applies: a quote cut from inside a longer sentence keeps its scope
label but not `scope_verified`. A colon may introduce the sentence; a question mark or an
ellipsis does not end one.

The builder also checks the captured club calendar: the target week must have one dated
fixture still ahead of the decision, and it must be the first club fixture after the exact
publication instant. An intervening fixture, an ambiguous double gameweek or a relevant
undated fixture leaves the statement unbound. Unassigned fixtures (`event=null`) participate
in this attestation check even though they are not projection rows.

Publication attestation comes from explicit held publication metadata, never fetch time,
HTTP `Last-Modified` or an invented time. Its closed sources are `html_publication_meta`,
`html_publication_time`, `jsonld_datePublished`, `text_published`, `feed_published` and
`consistent_publication_fields`. The date, precision, source and digest are retained. A
verified day-only date remains day-only and cannot authorize an exact-time intervention.

The artifact reader validates these fields' shape. The manager-word consumer independently
resolves the citation, recomputes source publication and scope, and checks the decision
calendar before granting a role constraint. Numeric participation/minute consumers apply
their own explicit-label, timing and forecast-basis checks. Neither a located quote nor an
LLM disposition alone establishes absence, a start forecast or a minute allocation.

## Read the coverage and claim flags together

Columns 15, 16 and 17 distinguish these common cases:

| | `club_source_covered` | `rotation_claim_observed` | `rotation_claim_unresolved` |
| --- | --- | --- | --- |
| his club was not read and coded | False | False | False |
| read and coded, with no resolved or unresolved claim about him | True | False | False |
| an unresolved claim about him, with other coverage retained | True | False | **True** |
| something was said and it was located | True | True | False |

The third row records an unresolved claim: its citation could not be verified, or conflicting
claims resolved to the same player. No disposition is carried. Conflicting player IDs are
also recorded in `players_with_conflicting_claims`; they are not a quiet-source result.
The flags are independent: when all a club's citations fail, coverage is False while the
affected players can still have unresolved=True. A retained claim can also coexist with a
separate unverified citation, so observed and unresolved need not be mutually exclusive.

One unverifiable citation costs one claim. A club whose *every* claim lost its citation is
dropped from `clubs_covered` — nothing it said survives into evidence, so calling it covered
would assert that its page was read into the table when none of it was. A club that was read
and genuinely said nothing has no claims either way and stays covered.

### Covered is not the same as covered in full

A club may register more than one page — team news and an injury table are often separate —
so "his club was read" and "all of his club's pages were read" stopped being one statement.
The answer this contract gives:

**Covered means at least one registered page was read and the club was coded**, subject to
the all-citations-refused rule above. It does not mean every registered page was read or that
the source said something actionable about every player. A successful zero-claim response
remains distinct from an uncoded club or a response whose claims were all refused.

**Fully covered is a different question, and the manifest answers it.**
`clubs_partially_covered` names the covered clubs at least one of whose registered pages was
not read. It is a narrowing of `clubs_covered`, never a substitute: every name in it also
appears there, and a club none of whose pages were read is *unread*, not partly read. Those
are different facts about different weeks, and an export that confuses them is refused.

Fully covered is therefore `clubs_covered` minus `clubs_partially_covered`, and a reader who
wants to know which page went missing has the capture: its index records every document's
club and both URLs.

**A followed article is not a registered page.** The reader follows article links from a
registered page to pages under it on the same host (`docs/club_news_sources.md` states the
rule), and stores each article as a document of the registered page's club. Both lists above
stay about registered pages: an article that could not be read is named among the run's
refusals and narrows nothing, since the articles a page links to are a capped sample and
never a list the week declared. The capture's index names every article that was read.

The field is recorded rather than derived, for the same reason `clubs_covered` is. From the
payloads alone, a club whose second page was refused is indistinguishable from a club that
only ever registered one — both arrive with one document. Only the run that read the registry
knows which it was, so it writes it down while it still knows.

The current pair contract is `rotation_evidence_export_v3`, independently of the table's V4
schema. Its manifest requires `clubs_partially_covered`; older *news captures* can omit the
capture field and the capture reader supplies an empty list. Optional provider provenance
remains unknown for captures or manifests that did not record it.

### `rotation_disposition`, in full

`not_addressed`, `no_statement`, `stated_expected_to_start`, `stated_expected_absent`,
`stated_rotation_risk`, `stated_returning_from_injury`, `stated_minutes_limited`, `ambiguous`,
`stated_full_match_unavailable`.

A closed list, deliberately. It cannot invent a nuance the source did not have, and it cannot
become a number.

### Why 16 and 28 are both here

They are computed independently and they agree on every row today, because the model is
currently the only source of a disposition. They are kept apart because a later feed-derived
disposition would set 16 without 28, and a table that had aliased them could not say so.

### Provenance is per club, and the instrument is not

A response is associated with each coded club; this is not a count of paid calls. An unchanged
request can reuse a captured response, and a synthetic response can cover several clubs.
Column 27 is the digest of **that player's club's** response. A single digest written across
every row would give an Arsenal player a citation into bytes that never mentioned him — and the digest
would verify, which is the worst kind of wrong.

Columns 25 and 26 stay single-valued. Which model answered and which question it was asked are
facts about the instrument, not about a club, and the manifest states one of each. A week
answered by two models, served by two model versions, or asked under two prompts is therefore
**refused** rather than recorded: it is a mixture the manifest cannot express, and a week whose
claims came from somewhere other than the model the manifest names is not a week anyone can
check. Same reasoning as the coding call's refusal to declare a fallback model.

The manifest's `response_sha256s` lists every response the week holds, sorted and without
repeats. One response can legitimately cover several clubs, and separate calls can return
identical bytes; this list identifies response content, not call count.

A claim placed on a player whose club has no recorded response refuses the whole week, naming
every such club at once. A disposition whose response cannot be named is traceable to no bytes
at all.

### `feed_news_state`, and why three

A player who has never been flagged carries no stamp at all. A player who was flagged and has
since been cleared carries an empty note with the stamp still on it. "Nothing is wrong with
him" and "nobody has said anything about him" are different facts about different players, and
a two-state reading would merge them.

## Manifest

These fields are required on read; a missing one refuses the pair:

`contract_version`, `artifact_contract_version`, `season`, `target_gameweek`,
`deadline_timestamp_utc`, `generated_at_utc`, `repository_commit`, `table_file`,
`table_sha256`, `row_count`, `roster_size`, `roster_snapshot_id`, `source_snapshot_ids`,
`clubs_declared`, `clubs_covered`, `clubs_partially_covered`, `documents_read`,
`document_sha256s`, `model_identifier`,
`model_version`, `prompt_sha256`, `response_sha256s`, `claims_coded`, `claims_ambiguous`,
`players_not_addressed`.

`provider` is optional on read and remains `null` if unrecorded; it identifies the adapter,
not the model or endpoint by inference. Clubs must agree on the recorded provider, model,
model version and prompt. The capture retains any request/reuse provenance; the rotation
manifest's response digests alone do not establish how many provider calls were made.

Current exports also write `club_news_source_kind` (`capture` or `fixture`) and
`players_with_conflicting_claims`. Captured sources write the paired
`club_news_snapshot_id` and `club_news_captured_at_utc` fields. A partial binding is refused.
V4 capture evidence must carry the binding, including a genuinely quiet response. Legacy
manifests retain their existing read checks without gaining this completed-call guarantee.

For a bound capture, `claims_coded` must equal the table's observed-claim count. Every observed
row must name the news capture; a zero-claim table names only the decision capture in its row
sources while still naming the completed news capture in the manifest. This permits quiet
coverage to be checked without pretending those claims exist.

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
document, where a replay may differ by `generated_at_utc` and nothing else. An artifact with
different content under the same name is refused, never overwritten. The export CLI refuses
a dirty working tree; the application function receives its repository commit from its caller.
The two files are individually immutable, not a transactional pair; consumers require both.

For captured news the default stem is
`rotation_evidence_v4_<season>_gw<NN>_<news suffix>_decision_<decision suffix>`.
Each suffix is the final 12 characters of its capture ID. Synthetic fixtures instead use
`rotation_evidence_v4_<season>_gw<NN>_<decision suffix>`. Explicit `table_name` overrides the
stem but not content checks. The decision suffix prevents two decisions using the same news
capture from colliding; full identities remain in the manifest and row provenance.

## `fixture_context_midweek`, and the refusal behind it

True when the player's club has a kickoff in the four days before the deadline. It uses
captured `kickoff_time_utc`, which the fixture contract makes nullable
precisely because a fixture can be assigned to a gameweek before its time is confirmed.

So coverage is checked before the answer is given: if any fixture in the target gameweek or the
one before it has no kickoff time, the build **refuses**. A `False` that meant "we could not
tell" would be the same failure this table is built to avoid, one column over.

The column is derived here and is **not** added to `FIXTURE_COLUMNS`, which rejects any column
the fixture contract does not define — a derived quantity belongs in the step that aggregates,
not in the stored table.

## Source, provider and artifact clocks

Source publication, document fetch, completed news capture, decision capture and artifact
generation are distinct timestamps. `generated_at_utc` is the export wall clock, not the
publication or decision time. The completed news capture bounds the finished acquisition and
coding process; it is not a provider-signed per-call timestamp. Reused responses retain their
capture provenance and must still pass the decision binding.

None of these checks verifies the model's training-data cutoff or prevents a model from
having unrelated prior knowledge. Traceable held bytes, exact quote offsets, instrument
identity and conservative source checks limit what this lane can act on; they do not prove
forecast calibration. A `day`-precision dateline is never converted to an instant: its row's
`timing_verified` can rest on exact capture/fetch times while the intervention remains gated.

## The model call

How the coding response is produced, what the prompt asks for, and why the model is never
asked for a byte offset: `docs/rotation_claim_coding.md`.
