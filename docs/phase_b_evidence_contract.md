# Phase B — Deadline-safe Evidence Contract

Owner: data / data mining. Status: **complete** — capture (PR B1), evidence table
(PR B2) and export (PR B3) implemented, and the real gameweek 3 handoff produced and
verified (see "The produced GW3 artifact").

What this layer delivers is *evidence*, not a model. Nothing here trains, promotes, or
publishes a probability. Phase C reads the table this contract describes; it does not read
the raw captures.

## 1. Time-of-knowledge

One rule governs everything below:

> **`captured_at_utc < deadline_timestamp_utc`, or the data is not pre-deadline evidence.**

It is enforced where the evidence is assembled, not documented and hoped for:
the capture command refuses a capture instant at or after the deadline before any raw payload
is written, and `RankedCohort.__post_init__` repeats the check when evidence is assembled. The
refusal is deliberate rather than a filter — a cohort built
from a post-deadline read is not a slightly worse cohort, it is a different cohort that
knows the answer.

The second rule is the lag rule, and it is about *picks* rather than about capture time:

> **Gameweek N's picks may never inform a gameweek N feature.** Elite squad evidence for
> gameweek N comes from gameweek N−1 picks at the latest.

A gameweek's picks become public only after its deadline. Using them for that same gameweek
would read the answer. This is stricter than the panel's time-of-knowledge rule in
`data_contract.md` §3 because it concerns a different object: a *squad* rather than a
*column*.

## 2. Cohort selection

The elite cohort is membership, never performance. A cohort says who stood in the official
Overall league's first N ranks at one instant before one deadline.

**Two capture kinds, deliberately not confusable.**

| Kind | Source label | Pages | Selection | Role |
| --- | --- | --- | --- | --- |
| Primary Top-100 | `fpl-top100` | 1–2 | `evaluation.select_as_of_top_100` | The frozen benchmark cohort. Unchanged, and not replaced by anything here. |
| Nested Top-200 | `fpl-top200` | 1–4 | `data.cohorts.nested_cohorts` | Sensitivity and evidence source. |

The labels differ on purpose. A snapshot id reading `top100` while carrying two hundred
ranks is the quiet mislabel this repository refuses elsewhere, and the primary cohort is
frozen — the two kinds must not be confusable at a glance. The first 200-rank capture taken
during this work, `fpl-top100-20260901T163641Z-e2cf9cb0938b`, carried the old label; it is
superseded by the one recorded in §6 and is not the handoff source.

**Nested cohorts are derived, not stored.** `scripts/capture_top100_cohort.py --cohort-size
200` writes the four standings pages and the bootstrap into one atomic snapshot;
`data.cohorts` cuts Top-50, Top-100 and Top-200 out of it on read. So containment is
structural — each cohort is a prefix of one ordering — rather than three separately built
lists that a test has to hope agree. A test asserts it anyway, because a refactor could take
the prefixes from different orderings and nothing else would notice.

`data/cohorts.py` deliberately does not import `squadopt.evaluation`. Duplicating a freeze
rule across two layers is how two answers to one question appear.

**Ordering comes from `rank_sort`, not `rank`.** The platform's tie handling lives in
`rank_sort`; a member without one is refused rather than placed by guess.

**A gap is a refusal, not a smaller cohort.** A missing rank, a repeated `rank_sort`, an
entry at two ranks, or the same page twice all stop the capture. A cohort missing one rank
has a composition that depends on which page failed, and every share computed against it
would be wrong by an amount nobody can state.

## 3. Missingness

Missing is not zero. The evidence table (PR B2) separates:

- a true zero;
- a field the source does not publish;
- a cohort member whose picks could not be read;
- a player absent from the snapshot;
- a capture taken after the deadline;
- a source whose time cannot be verified.

Shares therefore carry an explicit denominator: `elite_squad_share_lag1 =
elite_squad_count_lag1 / elite_members_observed`. When `elite_members_observed == 0` the
share is missing, **not** zero — an unobserved member is not a member who left the player
out.

## 4. Identity

FPL's seasonal `element` id is not the canonical player id. Evidence rows key on the
persistent player `code`, bridged by `player_codes(bootstrap)` from the same capture the
evidence came from. Two elements mapping to one persistent code is fail-closed. An
unrecognised element is never dropped silently: it is counted in diagnostics or the input is
refused.

## 5. Privacy

Entry ids, manager names and squad names never enter a committed artifact.

- The capture stores raw standings pages, which do carry names, in the git-ignored snapshot
  store only.
- `RankedCohort` carries entry ids and counts, and has no name-bearing field at all — a test
  asserts the absence, so nothing downstream can publish one by accident.
- The capture command prints aggregate validation facts and the snapshot id, never a member.
- Committed test fixtures are entirely synthetic: entry ids come from a reserved 900001+
  block that matches no real entry, and the placeholder names are labelled as such.

## 6. The captured evidence source

```text
snapshot        fpl-top200-20260901T163712Z-8711990a9dca
source label    fpl-top200
captured_at     2026-09-01T16:37:12.388574Z
target gameweek 3
deadline        2026-09-04T17:30:00Z   (capture is 72.9 h pre-deadline)
payloads        bootstrap-static.json
                league-314-standings-page-01..04.json
ranks covered   1..200, complete, no duplicates
unique entries  200
nested cohorts  Top-50 (50), Top-100 (100), Top-200 (200); 50 ⊂ 100 ⊂ 200 verified
element→code    629 mappings, from the bootstrap in the same capture
fingerprint     reproduces byte for byte on re-read
```

## 7. Known limitations

- **The primary Top-100 snapshot is not on this machine.** `fpl-top100-20260901T040725Z-5813e06fe096`
  was captured elsewhere, raw snapshots do not enter git (rule 6), and the primary cohort is
  frozen (rule 7). So the new Top-200 has **not** been cross-checked against the primary
  Top-100's membership here. Nested containment is verified within the single Top-200
  capture, which is what the nested reading needs; a primary-vs-sensitivity comparison must
  be run wherever the primary snapshot lives.
- The Top-100 derived from the Top-200 capture is a **sensitivity** cohort. It does not
  replace the frozen primary, and no benchmark claim may be moved onto it.
- Cohort membership is frozen at capture; outcomes for gameweek 3 do not exist yet, so no
  performance statement is available or attempted.
- The capture is a single instant. It does not describe how the first 200 ranks churn.

## 8. The evidence table (PR B2)

One row is one player for one decision week.

```python
from squadopt.features.evidence import build_player_evidence_table

table = build_player_evidence_table(
    season="2026-27",
    target_gameweek=3,
    deadline_timestamp_utc="2026-09-04T17:30:00Z",
    snapshots=[cohort_snapshot, elite_picks_snapshot],  # any pre-deadline captures
    cohort_snapshot=cohort_snapshot,  # where membership is frozen
    cohort_size=100,
)
```

`season` is required and **not** derived. The captured payloads publish no season label, and
inferring one needs a model of the calendar that lives above this layer; guessing it would
mislabel every row.

### Output schema

| Column | Dtype | Source | Missing means |
| --- | --- | --- | --- |
| `contract_version` | string | this module (`player_evidence_v1`) | — |
| `season` | string | caller | — |
| `target_gameweek` | int64 | caller | — |
| `player_id` | int64 | `player_codes(bootstrap)` — persistent code | — |
| `captured_at_utc` | string | the ownership capture | — |
| `deadline_timestamp_utc` | string | caller | — |
| `source_snapshot_ids` | string | the captures actually read — cohort, ownership, and each capture a member's N−1 picks came from — sorted, `;`-joined | — |
| `timing_verified` | boolean | this module | — |
| `elite_cohort_size` | int64 | caller `cohort_size`, cut from the cohort capture | — |
| `elite_members_observed` | int64 | count of members with readable N−1 picks | — |
| `elite_squad_count_lag1` | Int64 | N−1 picks | no member was observed |
| `elite_squad_share_lag1` | Float64 | count ÷ observed | no member was observed |
| `elite_start_count_lag1` | Int64 | N−1 picks, positions 1–11 | as above |
| `elite_start_share_lag1` | Float64 | count ÷ observed | as above |
| `elite_captain_count_lag1` | Int64 | N−1 picks, `is_captain` | as above |
| `elite_captain_share_lag1` | Float64 | count ÷ observed | as above |
| `overall_selected_by_percent` | Float64 | bootstrap | the source value did not parse |
| `transfers_in_event` | Int64 | bootstrap | the field was absent or not an integer |
| `transfers_out_event` | Int64 | bootstrap | as above |
| `net_transfers_event` | Int64 | in − out | either side missing |
| `availability_status` | string | bootstrap `status` | absent or empty |
| `chance_of_playing_next_round` | Int64 | bootstrap | the platform publishes `null` when it has nothing to say |
| `official_news_present` | boolean | `bool(news)` | `news` was not a string |
| `elite_evidence_observed` | boolean | `elite_members_observed > 0` | — |
| `ownership_evidence_observed` | boolean | ownership parsed | — |
| `transfer_evidence_observed` | boolean | both transfer counts present | — |
| `availability_evidence_observed` | boolean | a non-empty status | — |

Rows are sorted by `player_id` with a reset index, so the table is byte-identical across runs
on identical input. Every column is cast to the dtype above rather than left to inference,
so the same contract carries the same dtypes whatever the capture covered; the nullable
families hold `pd.NA`, and a missing count is never a zero nor a missing flag `False`.

Diagnostics that are not per-player ride on `DataFrame.attrs`: `cohort_snapshot_id`,
`ownership_snapshot_id`, `elite_members_missing_picks`, `unmapped_picked_elements`,
`deadline_timestamp_utc`, `hours_pre_deadline`. An unrecognised picked element is counted
there, never dropped in silence.

### Which snapshot each column comes from

- **Elite columns** — the pre-deadline capture(s) carrying each member's N−1 picks (the newest
  legal one per member), cross-referenced with cohort membership from the standings capture.
  Gameweek N picks are not read even when they are present in a supplied capture.
- **Ownership, transfer and availability columns** — the **newest pre-deadline** capture that
  carries a bootstrap. Newest among the *legal* ones: the timing filter runs first, so a later
  capture can never be preferred into the table.
- **Identity** — `player_codes` from that same bootstrap, so codes and ownership always come
  from one reading.
- **Provenance** — `source_snapshot_ids` names exactly the captures that were read: the cohort
  capture, the ownership capture, and every capture a member's N−1 picks were taken from. A
  pre-deadline capture that contributed nothing is not listed.

### Observed coverage, on the real captures

```text
cohort          fpl-top200-20260901T163712Z-8711990a9dca   (Top-100 cut, 72.9 h pre-deadline)
elite picks     fpl-elite-picks-20260901T171603Z-d4b04d078d67   (GW2 picks, 100/100 readable)
rows            629 players
elite           elite_members_observed = 100, elite_evidence_observed = True
                squad counts sum 1500 = 15 x 100
                start counts sum 1100 = 11 x 100
                captain shares sum 1.000  (one captain per member)
                most-held: two players at 100/100; one of them captained by 100/100
ownership       629/629 observed, selected_by_percent 0.0 .. 70.3
transfers       629/629 observed, net -363,855 .. +1,005,866
availability    629/629 observed, 138 players carrying news
diagnostics     0 members missing picks, 0 unmapped picked elements
```

Without the picks capture the same call returns the identical 629 rows with
`elite_members_observed = 0` and **every** elite count and share missing rather than zero.
That is the missingness policy working, not a degraded table.

### Phase C handoff

Phase C reads this table and nothing under `data/snapshots/`. What it may rely on:

- `player_id` is the persistent code, stable across seasons and transfers.
- Every row was assembled from captures that provably preceded the deadline named in the row.
- A missing value is missing. It is never a zero standing in for one.
- The same inputs give the same table; the builder mutates nothing it is given.

What it must **not** do: treat `elite_*_share_lag1` as an ownership probability, or read a
share without also reading `elite_members_observed`. A share of 1.0 over two observed members
and a share of 1.0 over a hundred are the same number and not the same evidence.

### The export artifact (`player_evidence_export_v1`)

What actually crosses to Phase C is a pair of files, written by
`scripts/export_player_evidence.py` from the table above:

```text
<name>.csv             the 27 contract columns, in that order, rows sorted by player_id,
                       LF line endings, no index column; a missing value is an empty cell
<name>.manifest.json   the aggregates and provenance a bare CSV would lose
```

The manifest carries `contract_version`, `artifact_contract_version`, `season`,
`target_gameweek`, `deadline_timestamp_utc`, `generated_at_utc`, `repository_commit`,
`table_file`, `table_sha256`, `row_count`, `cohort_size`, `elite_members_observed`,
`elite_members_missing_picks`, `unmapped_picked_elements`, `cohort_snapshot_id`,
`ownership_snapshot_id` and `source_snapshot_ids`. The last five are the `DataFrame.attrs`
and provenance diagnostics, so the missingness denominator travels with the table.

Three rules hold at export time. The table is validated against its own contract first
(exact columns, one week, unique `player_id`, timing verified, provenance consistent with the
diagnostics), and a missing diagnostic refuses the export rather than becoming a zero. The
same table produces the same CSV bytes and the same `table_sha256`; only `generated_at_utc`
differs between runs. Writing is create-once: the CSV lands through a temporary file, the
digest is taken from the final bytes, and an existing artifact with different content is
never overwritten.

```console
python -m scripts.export_player_evidence --season 2026-27 --target-gameweek 3 \
    --deadline-utc 2026-09-04T17:30:00Z --cohort-snapshot <fpl-top200-...> \
    --snapshot <fpl-elite-picks-...> --cohort-size 100 --output-dir artifacts/phase_b
```

The command prints counts and the digest only. Neither file names an entry or a manager;
raw snapshots stay under `data/snapshots/` and are not part of the handoff.

### The produced GW3 artifact

The pair above, produced from real captures rather than described. Recorded here because the
files themselves are not committed: they derive from licence-restricted third-party captures,
which is why `data/snapshots/` and `data/handoffs/` are git-ignored, and ADR 0003 puts a
per-player expansion in the evidence tier. This section is the record; the artifact is the
evidence.

```text
files           player_evidence_v1_2026-27_gw03_top100.csv          (158,945 bytes)
                player_evidence_v1_2026-27_gw03_top100.manifest.json
contract        player_evidence_v1 / player_evidence_export_v1
week            2026-27 gameweek 3, deadline 2026-09-04T17:30:00Z
commit          330a9b8d8061d56eed070adf70e90497ffda17d3, clean tree
table_sha256    a1ec611ceef5567b43944c0aeba45229ba13cc7efde4deccd79cba3e61a625c0
rows            629 players
cohort          Top-100 cut from fpl-top200-20260901T163712Z-8711990a9dca
ownership       fpl-top200-20260901T163712Z-8711990a9dca   (the same capture's bootstrap)
elite picks     fpl-elite-picks-20260901T171603Z-d4b04d078d67   (gameweek 2, 100 members)
captured_at     2026-09-01T16:37:12.388574Z   (72.88 h pre-deadline)
```

Eleven checks, all passing. The first six are what the command prints; the rest are read back
off the written CSV, because the command deliberately prints counts and a digest rather than
the table:

```text
row_count                        629
elite_members_observed           100   on every row
elite_members_missing_picks      0
unmapped_picked_elements         []
timing_verified                  true on every row
exit code                        0
elite_squad_count_lag1 sum       1500  = 15 x 100
elite_start_count_lag1 sum       1100  = 11 x 100
elite_captain_share_lag1 sum     1.000 = one captain per member
sha256(csv bytes)                equals the manifest's table_sha256
columns                          the 27 player_evidence_v1 columns, in order, no identity column
```

The three sums are the table's internal consistency, not a restatement of the counts: each
observed member contributes exactly fifteen squad places, eleven starting places and one
captaincy, so the totals can only hold if membership, the element-to-code bridge and the
denominator agree. All four evidence families are observed on 629/629 rows —
`selected_by_percent` 0.0 to 70.3, `net_transfers_event` −363,855 to +1,005,866, 138 players
carrying news, two players held by 100/100 members and one of them captained by 100/100.

Re-running the same command reproduces the same digest and writes nothing: create-once saw an
identical artifact and kept it.

**This is the sensitivity Top-100, not the frozen primary.** It is the Top-100 prefix of the
Top-200 capture, so §7 applies unchanged — the frozen primary
`fpl-top100-20260901T040725Z-5813e06fe096` is a different cohort, is not on the machine this
export ran on, and no benchmark claim moves onto this one. What this artifact is for is Phase
C evidence, which is exactly the role §2 gives the nested capture.

Top-50 and Top-200 exports are not part of closing Phase B. They would need picks for members
101–200, which the capture does not carry: at `--cohort-size 200` the denominator stays at the
hundred observed members and `elite_members_missing_picks` records the other hundred.

### Known limitations of the evidence table

- Elite evidence is one week lagged by construction. It describes what the cohort held going
  into gameweek N−1's fixtures, not what they will hold for N.
- Availability uses only the official `status`, `chance_of_playing_next_round` and whether news
  exists. Raw news text is deliberately not a feature: no scraping, no classification, no LLM.
- Ownership and transfer counts are capture-time values, not deadline values. The table records
  `captured_at_utc` and `hours_pre_deadline` so a consumer can price that gap.
- Capturing 100 members' picks costs 100 requests. At Top-200 it is 200, which is where the
  per-request retry ceiling in #235 starts to matter.
- No model is fitted and no probability is produced anywhere in this layer.

### Reading a smaller cohort out of a larger capture

Two different questions live here and they are answered in two places.

`ranked_entries_from_pages` asks whether the **capture is whole**: pages 1..k present, in
order, covering ranks 1..50k with no gap, no repeat and nothing outside. It therefore reads the
full ordering the capture holds and refuses to be asked for fewer ranks than the pages it was
handed — being asked to ignore a page it was given is exactly the shape of a capture defect.

`nested_cohorts` then **cuts**. Top-50, Top-100 and Top-200 out of one 200-rank capture are
prefixes of that single validated ordering.

`scripts/capture_elite_picks.py` follows the same order: it validates every standings page the
cohort capture carries, then cuts `--cohort-size` with `nested_cohorts`, so one Top-200
capture serves all three sizes and a size the capture cannot cover is refused.

Keeping the cut out of the page reader is what lets one capture answer for three sizes. Asking
the reader for `expected_ranks=100` against a four-page capture is refused, and correctly so.

Measured on the real captures, with picks captured for the Top-100 only:

```text
cohort_size=50   elite_members_observed 50    squad counts sum 750  = 15 x 50
cohort_size=100  elite_members_observed 100   squad counts sum 1500 = 15 x 100
cohort_size=200  elite_members_observed 100   squad counts sum 1500  <- 100 of 200 observed
```

The last row is the missingness policy rather than a bug: the denominator is the hundred
members whose picks were read, not the two hundred in the cohort, and
`elite_members_missing_picks` records the other hundred. A share of 0.30 there means "thirty of
the hundred observed", and a consumer that ignores `elite_members_observed` will misread it.
