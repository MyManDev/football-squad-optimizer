# Artifact Preflight Specification

## Purpose

The residual-export handoff ([residual export contract](residual_export_contract.md)) is
the seam between prediction ownership and measurement ownership. A corrupted, mislabeled,
or mispaired artifact that crosses that seam silently would contaminate recalibration
(#38), the candidate gate (#43), and live-risk evidence (#45) at once.

The preflight examines an artifact against its declared contract **before** any
measurement run consumes it. It never repairs, reinterprets, or drops data. Every
deviation becomes a named finding; a single failed finding blocks the handoff.

Contract version: `artifact_preflight_v1`.

## Scope

Implemented in `src/squadopt/preflight/` with the CLI
`scripts/run_artifact_preflight.py`. The preflight validates:

1. **One export** — the table's row-level rules, the manifest's required fields, and the
   agreement between them (checksum included).
2. **One reference/candidate pair** — the pairing rule: identical keys, identical
   realized points, shared population identity, no silent intersection.
3. **External expectations** — facts the receiving side already knows (for example the
   agreed 147-fold / 101447-row development population), so a manifest cannot quietly
   redefine the population it claims to cover.

## Findings, not exceptions

A preflight run reports **every** violated rule at once instead of failing one rule per
round-trip. `PreflightError` is reserved for inputs that cannot be examined at all (a
missing file, a manifest that is not a JSON object).

Each finding carries a stable check identifier. The main identifiers:

| Group | Checks |
| --- | --- |
| Manifest | `manifest_fields_present`, `manifest_contract_version`, `manifest_identity_text`, `manifest_development_seasons`, `manifest_population_counts`, `manifest_repository_commit`, `manifest_table_sha256_format`, `manifest_created_at_utc`, `manifest_opening_flag_type` |
| Table | `table_columns`, `table_row_population`, `table_key_uniqueness`, `table_fold_id_format`, `table_player_id_representation`, `table_identity_values`, `table_predicted_points`, `table_realized_points`, `table_residual_identity`, `table_sort_order` |
| Table vs manifest | `manifest_fold_count_matches_table`, `manifest_row_count_matches_table`, `manifest_seasons_match_table`, `manifest_opening_flag_matches_table`, `table_checksum_matches_manifest` |
| Expectations | `expected_fold_count`, `expected_row_count`, `expected_seasons`, `expected_objective`, `expected_repository_commit`, `expected_dataset_snapshot`, `expected_opening_flag` |
| Pair | `pair_labels_differ`, `pair_development_seasons`, `pair_evaluation_objective`, `pair_dataset_snapshot`, `pair_repository_commit`, `pair_opening_flag`, `pair_fold_policy`, `pair_row_keys`, `pair_realized_points`, `pair_row_identity` |

Column or emptiness violations short-circuit the row-level checks: a table with the
wrong shape cannot be examined row by row, and derived failures would bury the actual
defect.

## Notable rules

- **The opening flag is evidence.** A GW2+ export claiming
  `opening_gameweeks_included: true`, or a table containing GW1 rows the manifest does
  not declare, both fail. This is the preflight face of the GW1 evidence rule in
  [live risk diagnostics](live_risk_diagnostics_spec.md).
- **Rows are never intersected.** A `(fold_id, player_id)` key present on one side of a
  pair only is a failure, because dropping unmatched players would change both the
  prediction-error population and the optimizer decision being compared.
- **Pairs share one commit.** Reference and candidate artifacts produced from different
  repository commits fail `pair_repository_commit`.
- **Checksums bind bytes, not intent.** `table_checksum_matches_manifest` compares the
  manifest digest against the exact file bytes. In-memory tables with no file produce no
  checksum finding; the CLI always supplies the digest.

## CLI

```text
python -m scripts.run_artifact_preflight \
    --table artifacts/candidate.csv \
    --manifest artifacts/candidate.manifest.json \
    --reference-table artifacts/reference.csv \
    --reference-manifest artifacts/reference.manifest.json \
    --expect-fold-count 147 \
    --expect-row-count 101447 \
    --expect-seasons 2021-22,2022-23,2023-24,2024-25 \
    --json-output artifacts/preflight.json
```

Exit codes: `0` only when every check in every report passed; `1` on any failed finding
or unreadable input; `2` on inconsistent arguments. The command is therefore usable as
an automated gate in front of `scripts/run_calendar_recalibration.py` and the formal
candidate benchmark.

## Rehearsal

`tests/integration/test_decision_chain_rehearsal.py` runs the full synthetic chain —
declared candidate identity → exports with manifests → preflight → calendar
recalibration → live-risk diagnostics → live squad report — and proves that each broken
artifact (tampered bytes, foreign commit, missing folds, GW2-only evidence for a GW1
target, unpromoted candidate identity) is stopped at the seam where it first becomes
wrong.

## What the preflight does not do

- It does not produce or bless real-data artifacts; #38/#43/#45 closeouts still require
  the artifacts themselves.
- It does not compare prediction quality; that is the candidate gate's job.
- It does not validate the fixture/team bridge or recalibration outputs; its scope is
  the residual-export handoff.
