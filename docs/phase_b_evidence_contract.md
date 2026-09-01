# Phase B — Deadline-safe Evidence Contract

Owner: data / data mining. Status: **engineering complete in stacked PRs B1 and B2;
operational elite-picks coverage is reported explicitly below.**

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

## 3. Evidence assembly and missingness

The Phase C boundary is deliberately one narrow function:

```python
build_player_evidence_table(
    *,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    snapshots: Sequence[CapturedSnapshot],
    cohort_snapshot: CapturedSnapshot,
) -> pandas.DataFrame
```

`cohort_snapshot` alone freezes membership. Standings pages found in later snapshots are
never consulted for membership. Among verified snapshots strictly before the target
deadline, the latest bootstrap supplies ownership, transfers and availability. For each
cohort member, the latest eligible snapshot carrying bootstrap, history and GW N-1 picks
supplies squad/start/captain evidence. A picks snapshot taken before the N-1 deadline is
not public evidence yet and is skipped. Payload checksums, the full snapshot fingerprint
and the snapshot id are recomputed before any payload is parsed.

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

The separate local verification capture used while developing B2 was
`fpl-top200-20260901T165747Z-fcf21642ff8c`. It yielded 629 unique persistent player rows:
629 ownership observations, 629 transfer observations and 629 availability observations.
It carries no entry-picks payloads, so `elite_members_observed` is honestly 0/200 and all
three elite shares are missing. Raw snapshots and entry identities remain git-ignored.

## 7. Output schema and dtypes

Every row has contract version `player_evidence_v1`. `source_snapshot_ids` is a sorted,
comma-separated set of the snapshot ids actually used for cohort, market and elite-picks
evidence; `captured_at_utc` is the latest capture time in that set.

| Columns | Pandas dtype | Meaning/source |
| --- | --- | --- |
| `contract_version`, `season`, `captured_at_utc`, `deadline_timestamp_utc`, `source_snapshot_ids` | `string` | Contract and verified provenance |
| `target_gameweek`, `player_id`, `elite_cohort_size`, `elite_members_observed` | `int64` | Decision key, persistent FPL code and explicit denominator |
| `timing_verified` | `boolean` | All used captures passed the strict pre-deadline rule |
| `elite_squad_count_lag1`, `elite_start_count_lag1`, `elite_captain_count_lag1` | `int64` | Counts from observed GW N-1 picks only |
| `elite_squad_share_lag1`, `elite_start_share_lag1`, `elite_captain_share_lag1` | `Float64` | Count divided by `elite_members_observed`; missing at denominator zero |
| `overall_selected_by_percent` | `Float64` | Latest eligible bootstrap value at capture time |
| `transfers_in_event`, `transfers_out_event`, `net_transfers_event` | `Int64` | Latest eligible bootstrap values; net exists only when both operands exist |
| `availability_status` | `string` | Official FPL status at capture time |
| `chance_of_playing_next_round` | `Int64` | Official FPL chance at capture time |
| `official_news_present` | `boolean` | Whether official news was non-empty; raw text is discarded |
| four `*_evidence_observed` columns | `boolean` | Whether each evidence family is observed, independently of its value |

Counts are real zero when at least one cohort member was observed and did not select the
player. When no member was observed, counts remain zero but `elite_evidence_observed` is
false and shares are missing; consumers must use the flag and denominator together.

## 8. Phase C handoff

```python
from squadopt.features.evidence import build_player_evidence_table

table = build_player_evidence_table(
    target_gameweek=3,
    deadline_timestamp_utc="2026-09-04T17:30:00Z",
    snapshots=verified_snapshots,
    cohort_snapshot=verified_top200_snapshot,
)
```

Phase C reads this table directly. It must not reopen raw standings or picks, replace
missing values with zero, reinterpret capture-time market fields as deadline values, or
use GW N picks. This layer produces no probability and trains or promotes no model.

The locked 2025-26 holdout is refused immediately after deriving the season from the
deadline and before snapshot inputs are iterated, validated, listed or hashed.

## 9. Known limitations

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
- The captured B1 snapshot has no GW2 picks payloads, so real elite ownership coverage is
  currently 0/200. Producing those payloads is an operational capture step, not permission
  to treat missing members as zero or to use GW3 picks.
- Market and availability fields describe their chosen capture instant, not the exact
  deadline. The exact chosen snapshot and time travel with every row.
- Official news is represented only by a presence boolean. Text modelling, scraping and
  LLM classification are explicitly outside Phase B.
