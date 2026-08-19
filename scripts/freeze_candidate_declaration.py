"""Print the Issue #43 candidate declaration and the two fingerprints to freeze.

    python -m scripts.freeze_candidate_declaration

Stage A of the declaration review requires both fingerprints to be computed and recorded
**before** the formal run. This command produces them from the same typed objects the
benchmark will use, so the values reviewed are the values executed rather than a
transcription of them.

It runs no benchmark, reads no archive, and touches no holdout. It only serialises what
has already been decided, which is the point: a declaration you have to run a measurement
to produce is not a pre-registration.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.backtest.learned_candidate import (
    LEARNED_RATE_FEATURE_CONTRACT_VERSION,
    LEARNED_RATE_MODEL_NAME,
    LEARNED_RATE_MODEL_VERSION,
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
)
from squadopt.backtest.production_benchmark import (
    CandidateDeclaration,
    ProductionBenchmarkConfig,
)
from squadopt.prediction.learned_rate import LearnedRateConfig, rate_input_columns
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

CANDIDATE_ID = "learned_rate_calendar_candidate_v1"
WINDOW = 6

# Stage A's review state, per steps 4 and 5 of docs/candidate_declaration_review.md.
#
# Data rather than prose in the renderer, because these were three literal strings that
# re-emitted "pending" on every regeneration — including for a review that had already
# happened. The record therefore contradicted docs/issue43_stage_a_review.md, which states
# the optimization/evaluation side's position as "v2 is clean enough to freeze", and left a
# reader unable to tell what the freeze was actually waiting on.
#
# Nothing here reaches either fingerprint: both are computed from the typed
# CandidateDeclaration and ProductionBenchmarkConfig, so recording a review cannot move the
# values it is a review of. A test holds that, because it is the property that makes editing
# this tuple safe.
#
# Each owner updates their own line when their review lands; the freeze line goes last, and
# only once every line above it is recorded.
STAGE_A_STATUS: Final = (
    (
        "Reviewed by the optimization/evaluation side",
        "recorded — `issue43_stage_a_review.md`: this side's position is that v2 is clean "
        "enough to freeze",
    ),
    ("Reviewed by the architecture/CI side", "**pending**"),
    (
        "Fingerprints frozen",
        "**pending** — both are computed and reproduce byte for byte; the freeze is recorded "
        "when the third review lands",
    ),
)

# Every component the declaration freezes. Listed explicitly rather than derived, because
# a frozen set that a code change can silently widen is not frozen.
FROZEN_COMPONENTS = (
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
)

CHANGE_SUMMARY = (
    "The expected-points rate is fitted per fold on the expanding visible history "
    "instead of read straight from the shifted rolling points-per-90 feature. That "
    "feature remains an input, joined by fixture count, home fixture count, appearance "
    "rate, and minutes per appearance. Closed-form ridge on standardised inputs, solved "
    "with numpy, so the fit carries no seed, iteration count, or solver choice."
)


def declaration() -> CandidateDeclaration:
    """Return the declaration under review."""

    return CandidateDeclaration(
        candidate_id=CANDIDATE_ID,
        model_name=LEARNED_RATE_MODEL_NAME,
        model_version=LEARNED_RATE_MODEL_VERSION,
        feature_contract_version=LEARNED_RATE_FEATURE_CONTRACT_VERSION,
        changed_component="expected_points_rate",
        change_summary=CHANGE_SUMMARY,
        frozen_components=FROZEN_COMPONENTS,
        source_reference="docs/candidate_gate_spec.md",
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
    return {
        "artifact_type": "candidate_declaration_freeze",
        "issue": 43,
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
        "rate_inputs": list(rate_input_columns(WINDOW)),
        "rate_controls": {
            "window": learned.window,
            "ridge_alpha": learned.ridge_alpha,
            "min_training_rows": learned.min_training_rows,
        },
        "declaration_fingerprint": declared.declaration_fingerprint,
        "benchmark_configuration_fingerprint": config.configuration_fingerprint,
        "development_seasons": list(config.seasons),
        "locked_holdout_accessed": False,
        "formal_run_completed": False,
    }


def markdown(record: dict[str, object]) -> str:
    declared = record["declaration"]
    assert isinstance(declared, dict)
    lines = [
        "# Issue #43 Candidate Declaration — frozen before execution",
        "",
        "Stage A of `docs/candidate_declaration_review.md`. Both fingerprints below are "
        "computed from the same typed objects the formal run constructs, so what is "
        "reviewed here is what executes. **No formal run has been made against this "
        "declaration.**",
        "",
        "## Fingerprints",
        "",
        f"- Candidate: `{declared['candidate_id']}`",
        f"- Declaration: `{record['declaration_fingerprint']}`",
        f"- Benchmark configuration: `{record['benchmark_configuration_fingerprint']}`",
        "",
        "## The single changed component",
        "",
        f"`{declared['changed_component']}`",
        "",
        str(declared["change_summary"]),
        "",
        "### Declared rate inputs",
        "",
    ]
    inputs = record["rate_inputs"]
    assert isinstance(inputs, list)
    lines += [f"- `{name}`" for name in inputs]
    lines += [
        "",
        "The first of these is the frozen rolling feature the replaced stage read "
        "directly. It stays an input because the handoff checklist freezes the feature "
        "windows: dropping it would change the feature mapping as well as the rate, "
        "which would be two changes rather than one. **If the intended reading was that "
        "the rate model may not see the player's own scoring history at all, this "
        "declaration is wrong and must be reissued before any run.**",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| `model_name` | `{declared['model_name']}` |",
        f"| `model_version` | `{declared['model_version']}` |",
        f"| `feature_contract_version` | `{declared['feature_contract_version']}` |",
        f"| `training_contract_version` | `{declared['training_contract_version']}` |",
        f"| `evaluation_objective` | `{declared['evaluation_objective']}` |",
        "",
        "These strings appear unchanged in both residual manifests and in every returned "
        "`PredictionSnapshot`; the benchmark refuses the run if they differ.",
        "",
        "## Frozen components",
        "",
    ]
    frozen = declared["frozen_components"]
    assert isinstance(frozen, list)
    lines += [f"- `{name}`" for name in frozen]
    lines += [
        "",
        "## Stage A status",
        "",
    ]
    lines += [f"- {label}: {state}" for label, state in STAGE_A_STATUS]
    lines += [
        "",
        "A change to anything above after the freeze voids it. There is no small-fix "
        "exception: a changed candidate is a new candidate with a new fingerprint.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "issue43_candidate_declaration.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "issue43_candidate_declaration.md",
    )
    arguments = parser.parse_args()

    record = document()
    text = markdown(record)
    print(text)
    print(json.dumps(record, indent=2, sort_keys=True))
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, text)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
