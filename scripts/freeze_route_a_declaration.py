"""Print the Route A candidate declaration and the fingerprints to freeze.

    python -m scripts.freeze_route_a_declaration

Route A gives the scoring rate the opponent it faces (#88). This command freezes what the
formal run will be, before it is run, and computes the fingerprints from the same typed
objects the run will use, so the values reviewed are the values executed rather than a
transcription of them.

It runs no benchmark, reads no archive beyond the committed signal record, and touches no
holdout. A declaration you have to run a measurement to produce is not a pre-registration.

The three rulings on #88 are what this declaration obeys, and each one changes what is
written here rather than only how it is phrased:

1.  **The stop condition gates the pooled coefficient, not a per-position slope.** The rate
    model is pooled across positions and estimates no per-position parameter, so a
    per-position sign clause would test a quantity the model never fits. The expected sign is
    stated below, before the fit, and per-position slopes are recorded diagnostics that gate
    nothing.

2.  **The input is the fitted walk-forward signal frame, consumed as data and bound by
    fingerprint.** Not the archive's `fixture_difficulty` (post-hoc, #152) and not the
    published 1-5 rating (fails at the decision level, #137). The formal run re-derives the
    frame -- it is deterministic -- and this declaration records the digest, so the input is
    bound rather than described.

3.  **No shared contract constant moves for the measurement.** The signal joins as data, so
    `FEATURE_GENERATION_CONTRACT_VERSION` and `LEARNED_RATE_FEATURE_CONTRACT_VERSION` are
    untouched and #43's pending freeze stays valid. Route A is declared under the local
    identity below. A bump, if the gate ever passes, is a promotion act sequenced against #43
    explicitly.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.backtest.learned_candidate import (
    LEARNED_RATE_MODEL_NAME,
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
)
from squadopt.backtest.production_benchmark import (
    CandidateDeclaration,
    ProductionBenchmarkConfig,
)
from squadopt.prediction.learned_rate import LearnedRateConfig, rate_input_columns
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

CANDIDATE_ID: Final = "opponent_signal_rate_candidate_v1"
WINDOW: Final = 6

# Route A's own contract identity, per ruling 3. Deliberately *not* a bump of
# LEARNED_RATE_FEATURE_CONTRACT_VERSION: the signal joins as data, the measurement needs no
# change to a shared constant, and moving one would drag #43's pending declaration
# fingerprint with it. The shared constant moves only in a promotion PR.
ROUTE_A_FEATURE_CONTRACT_VERSION: Final = "route_a_opponent_signal_rate_v1"

# The model version this candidate would carry if promoted. Recorded here because a
# declaration names the thing it is declaring; nothing is pinned anywhere by writing it down.
ROUTE_A_MODEL_VERSION: Final = "learned-rate-opponent-signal-v1"

# The two columns the candidate adds, and what each one is.
#
# Both are the *player's own club's* row for that gameweek, and both already account for the
# opponent because that is how the rating produces them: expected_goals is the club's own
# Poisson rate in that fixture, and clean_sheet_probability is the chance that club concedes
# nothing. So both are higher-is-better for the player's own return.
SIGNAL_INPUT_COLUMNS: Final = ("rating_attacking_signal", "rating_defensive_signal")

SIGNAL_RECORD: Final = REPOSITORY_ROOT / "docs" / "opponent_signal.json"

# The a priori expectation the stop condition gates on, stated before the fit.
#
# Both coefficients are expected POSITIVE, and the reasoning matters more than the word.
# A club expected to score more gives its attackers more to score; a club more likely to keep
# a clean sheet gives its keeper and defenders the clean-sheet points and its midfielders the
# one-point version. Neither channel harms the other positions -- it merely does less for
# them -- so pooling across positions should not cancel either coefficient.
#
# This is also why S2's per-position slopes came out mixed (GK +0.262, DEF +0.228, MID -0.041,
# FWD -0.042, docs/opponent_rating_handoff.md). Those were fitted against a single conflated
# difficulty integer, which cannot be favourable to attackers and defenders at once, so a
# pooled fit on it would average opposing effects toward nothing. Separating the two channels
# is the substantive difference between Route A and what S2 measured, and it is the claim this
# run tests. If a coefficient comes back negative or straddling zero, that claim is wrong.
EXPECTED_COEFFICIENT_SIGNS: Final = {
    "rating_attacking_signal": "positive",
    "rating_defensive_signal": "positive",
}

STOP_CONDITION: Final = (
    "Route A stops if either declared signal's pooled coefficient fails to be positive with "
    "its 90% interval excluding zero. The gate is on the pooled coefficient because that is "
    "the parameter the model estimates; per-position slopes are recorded as diagnostics and "
    "gate nothing. Both clauses are evaluated once, on the formal run, and neither the "
    "expected sign nor the interval level is revisited afterwards."
)

CHANGE_SUMMARY: Final = (
    "The expected-points rate reads two more inputs: the fitted Dixon-Coles attacking and "
    "defensive signals for the player's own club at that gameweek, joined by "
    "(season, gameweek, club) from the walk-forward signal frame. Everything else the rate "
    "already read is unchanged, and the signal enters as data rather than through any shared "
    "feature contract."
)

# Everything the candidate does not touch. A component named here may not move, and the
# declaration is void if one does.
FROZEN_COMPONENTS: Final = (
    "expected_minutes_stage",
    "cold_start_ladder",
    "availability_post_processing",
    "two_stage_combination",
    "feature_window_mapping",
    "shrinkage_weights",
    "opening_price_prior",
    "development_fold_set",
    "baseline_control",
    "ridge_reference",
    "optimization_contract",
    "budget_and_formation_constraints",
    "promotion_gates",
    "evaluation_objective",
    "learned_rate_training_contract",
    "shared_feature_contract_constants",
)

DEFAULT_RECORD: Final = REPOSITORY_ROOT / "docs" / "route_a_declaration.json"
DEFAULT_SUMMARY: Final = REPOSITORY_ROOT / "docs" / "route_a_declaration.md"


def signal_frame_fingerprint(path: Path = SIGNAL_RECORD) -> str:
    """Read the digest of the frame this candidate declares as its input.

    Read from the committed record rather than recomputed here, because recomputing would
    make this command depend on the archive and on an hour of rating fits. The formal run
    re-derives the frame and must match this value; a mismatch means the input moved and the
    declaration no longer describes the candidate.
    """

    if not path.is_file():
        raise SystemExit(
            f"No signal record at {path}. Run 'python -m scripts.build_opponent_signal' first: "
            "the declaration binds its input by fingerprint and cannot invent one."
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = document.get("frame_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise SystemExit(
            f"{path} carries no usable frame_fingerprint. The signal record must be "
            "regenerated by a build that records one."
        )
    return fingerprint


def declaration() -> CandidateDeclaration:
    """Return the declaration under review."""

    return CandidateDeclaration(
        candidate_id=CANDIDATE_ID,
        model_name=LEARNED_RATE_MODEL_NAME,
        model_version=ROUTE_A_MODEL_VERSION,
        feature_contract_version=ROUTE_A_FEATURE_CONTRACT_VERSION,
        changed_component="expected_points_rate",
        change_summary=CHANGE_SUMMARY,
        frozen_components=FROZEN_COMPONENTS,
        source_reference="docs/route_a_declaration.md",
    )


def benchmark_config() -> ProductionBenchmarkConfig:
    """Return the benchmark configuration the formal run will use."""

    return ProductionBenchmarkConfig(
        production_config=ProductionProjectionConfig(
            rate_window=WINDOW, minutes=ExpectedMinutesConfig(window=WINDOW)
        ),
        candidate_declaration=declaration(),
    )


def document() -> dict[str, object]:
    """Return the reviewable record, fingerprints included."""

    declared = declaration()
    config = benchmark_config()
    learned = LearnedRateConfig(window=WINDOW)
    existing = list(rate_input_columns(WINDOW))
    return {
        "artifact_type": "candidate_declaration_freeze",
        "issue": 88,
        "candidate_id": declared.candidate_id,
        "declaration": {
            "candidate_id": declared.candidate_id,
            "model_name": declared.model_name,
            "model_version": declared.model_version,
            "feature_contract_version": declared.feature_contract_version,
            "training_contract_version": LEARNED_RATE_TRAINING_CONTRACT_VERSION,
            "changed_component": declared.changed_component,
            "change_summary": declared.change_summary,
            "frozen_components": list(declared.frozen_components),
            "evaluation_objective": declared.evaluation_objective,
            "source_reference": declared.source_reference,
            "contract_version": declared.contract_version,
        },
        "rate_inputs_before": existing,
        "rate_inputs_added": list(SIGNAL_INPUT_COLUMNS),
        "rate_inputs_after": existing + list(SIGNAL_INPUT_COLUMNS),
        "rate_controls": {
            "window": learned.window,
            "ridge_alpha": learned.ridge_alpha,
            "min_training_rows": learned.min_training_rows,
        },
        "signal_input": {
            "produced_by": "scripts/build_opponent_signal.py",
            "contract_version": "opponent_signal_v1",
            "grain": "season/gameweek/club",
            "joined_on": ["season", "gameweek", "club"],
            "frame_fingerprint": signal_frame_fingerprint(),
            "re_derived_in_the_run": True,
            "admissible_because": (
                "fitted walk-forward with as_of set to the target gameweek's first kickoff; "
                "not the archive's post-hoc fixture_difficulty (#152) and not the published "
                "1-5 rating (#137)"
            ),
        },
        "expected_coefficient_signs": dict(EXPECTED_COEFFICIENT_SIGNS),
        "stop_condition": STOP_CONDITION,
        "gated_quantity": "pooled_coefficient",
        "per_position_slopes_are": "recorded diagnostics, not gates",
        "shared_contract_constants_moved": [],
        "declaration_fingerprint": declared.declaration_fingerprint,
        "benchmark_configuration_fingerprint": config.configuration_fingerprint,
        "development_seasons": list(config.seasons),
        "operational_control_at_declaration": "fw05-bw0p1",
        "control_unchanged_by_the_fw10_holdout": True,
        "locked_holdout_accessed": False,
        "formal_run_completed": False,
    }


def _listed(record: dict[str, object], key: str) -> list[str]:
    value = record[key]
    return [str(item) for item in value] if isinstance(value, list) else []


def _mapping(record: dict[str, object], key: str) -> dict[str, object]:
    value = record[key]
    return dict(value) if isinstance(value, dict) else {}


def markdown(record: dict[str, object]) -> str:
    """Render the declaration as the reviewable document."""

    declared = _mapping(record, "declaration")
    signal = _mapping(record, "signal_input")
    signs = _mapping(record, "expected_coefficient_signs")
    controls = _mapping(record, "rate_controls")
    before = ", ".join(f"`{column}`" for column in _listed(record, "rate_inputs_before"))
    added = ", ".join(f"`{column}`" for column in _listed(record, "rate_inputs_added"))
    moved = ", ".join(_listed(record, "shared_contract_constants_moved"))
    lines = [
        "# Route A candidate declaration",
        "",
        f"Issue #{record['issue']} · candidate `{record['candidate_id']}` · "
        f"contract `{declared['contract_version']}`",
        "",
        "**Frozen before the run, not after.** The fingerprints below are computed from the "
        "same typed objects the formal run will use, so what is reviewed is what executes.",
        "",
        "## The one thing that changes",
        "",
        f"`{declared['changed_component']}`. {declared['change_summary']}",
        "",
        "| | |",
        "| --- | --- |",
        f"| rate inputs before | {before} |",
        f"| added | {added} |",
        f"| window | {controls.get('window')} |",
        f"| ridge alpha | {controls.get('ridge_alpha')} |",
        f"| minimum training rows | {controls.get('min_training_rows')} |",
        "",
        "Both added columns are the **player's own club's** row for that gameweek, and both",
        "already account for the opponent because that is how the rating produces them:",
        "`rating_attacking_signal` is the club's own expected goals in the fixture, and",
        "`rating_defensive_signal` is the chance that club concedes nothing. Higher is better",
        "for the player's own return in both cases.",
        "",
        "## The input, bound rather than described",
        "",
        f"- produced by `{signal.get('produced_by')}`, contract `{signal.get('contract_version')}`",
        f"- grain `{signal.get('grain')}`, joined on "
        f"{', '.join(f'`{c}`' for c in _listed(signal, 'joined_on'))}",
        f"- **frame fingerprint** `{signal.get('frame_fingerprint')}`",
        "- the formal run **re-derives** the frame rather than reading a stored artifact, and",
        "  must reproduce that digest. A mismatch means the input moved, and a moved input is a",
        "  different candidate.",
        "",
        f"Admissible because it is {signal.get('admissible_because')}.",
        "",
        "## The stop condition, and the quantity it gates",
        "",
        "Expected signs, stated **before** the fit:",
        "",
        "| input | expected pooled coefficient |",
        "| --- | --- |",
    ]
    for column, sign in sorted(signs.items()):
        lines.append(f"| `{column}` | **{sign}** |")
    lines += [
        "",
        f"> {record['stop_condition']}",
        "",
        "The reasoning behind the expected sign, because the reasoning is the commitment: a club",
        "expected to score more gives its attackers more to score, and a club more likely to keep",
        "a clean sheet gives its keeper and defenders the clean-sheet points and its midfielders",
        "the one-point version. Neither channel harms the other positions -- it does less for",
        "them -- so pooling across positions should not cancel either coefficient.",
        "",
        "That is also why S2's per-position slopes came out mixed (GK +0.262, DEF +0.228,",
        "MID -0.041, FWD -0.042 -- `docs/opponent_rating_handoff.md`). Those were fitted against",
        "a single conflated difficulty integer, which cannot be favourable to attackers and",
        "defenders at once, so a pooled fit on *that* would average opposing effects toward",
        "nothing. **Separating the two channels is the substantive difference between Route A and",
        "what S2 measured, and it is the claim this run tests.** If either coefficient returns",
        "negative or straddling zero, the claim is wrong and Route A stops.",
        "",
        f"Per-position slopes are {record['per_position_slopes_are']}. If per-position structure",
        "turns out to matter, the remedy is declaring a per-position model, not adding a",
        "per-position gate to a pooled one -- and not after results exist.",
        "",
        "## What does not move",
        "",
        f"Shared contract constants moved: **{moved or 'none'}**.",
        "",
        "The signal joins as data, so the measurement needs no change to",
        "`FEATURE_GENERATION_CONTRACT_VERSION` or `LEARNED_RATE_FEATURE_CONTRACT_VERSION`.",
        "Route A carries its own identity",
        f"(`{declared['feature_contract_version']}`) instead. This keeps #43's pending",
        "declaration fingerprint valid today, and makes an eventual bump a reviewed promotion",
        "act sequenced against #43 rather than a side effect of measuring.",
        "",
        "Frozen components, none of which the candidate may touch:",
        "",
    ]
    lines += [f"- `{name}`" for name in _listed(declared, "frozen_components")]
    lines += [
        "",
        "## Fingerprints to freeze",
        "",
        "```",
        f"declaration_fingerprint              {record['declaration_fingerprint']}",
        f"benchmark_configuration_fingerprint  {record['benchmark_configuration_fingerprint']}",
        f"signal frame_fingerprint             {signal.get('frame_fingerprint')}",
        "```",
        "",
        "A changed candidate is a new candidate with a new fingerprint. If any of these three",
        "moves, this declaration describes something that is not being run.",
        "",
        "## The control this was written against",
        "",
        f"`{record['operational_control_at_declaration']}`, and the fw10 locked holdout did not",
        "promote its challenger, so the control is unchanged. This declaration was deliberately",
        "written after that run rather than before it, so it does not chase a moving control.",
        "",
        f"Development seasons: {', '.join(_listed(record, 'development_seasons'))}. "
        f"Locked holdout accessed: **{record['locked_holdout_accessed']}**. "
        f"Formal run completed: **{record['formal_run_completed']}**.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    arguments = parser.parse_args()

    record = document()
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, markdown(record))

    declared = _mapping(record, "declaration")
    signal = _mapping(record, "signal_input")
    print(f"Candidate   {record['candidate_id']}")
    print(f"Changed     {declared['changed_component']}")
    print(f"Added       {', '.join(_listed(record, 'rate_inputs_added'))}")
    print(f"Contract id {declared['feature_contract_version']}  (Route-A-local, no shared bump)")
    print()
    print(f"declaration_fingerprint             {record['declaration_fingerprint']}")
    print(f"benchmark_configuration_fingerprint {record['benchmark_configuration_fingerprint']}")
    print(f"signal frame_fingerprint            {signal.get('frame_fingerprint')}")
    print()
    print(f"Expected signs  {json.dumps(_mapping(record, 'expected_coefficient_signs'))}")
    print(f"Gated quantity  {record['gated_quantity']}")
    print(f"Control         {record['operational_control_at_declaration']} (unchanged)")
    print()
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
