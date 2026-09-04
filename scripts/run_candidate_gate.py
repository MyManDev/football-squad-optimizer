"""Run the frozen Issue #43 candidate through the development gate, exactly once.

    python -m scripts.run_candidate_gate --confirm-frozen

Stage B of `docs/candidate_declaration_review.md`. `docs/candidate_gate_spec.md:63` says
"run `run_declared_candidate_benchmark` exactly once for the formal development result", and
until now nothing did: the function had no caller outside its own module, and
`scripts/run_production_benchmark.py` hard-wires the two-stage builder and falls back to the
old `two_stage_calendar_candidate_v1` declaration. A formal run through that script would
have measured the wrong candidate under the wrong declaration.

**This command has no tuning knobs, by construction.** The benchmark configuration is
whatever `scripts/freeze_candidate_declaration.benchmark_config()` returns, and the
configuration fingerprint covers the evaluated seasons and the solver's deterministic budget
as well as the projection settings — so a `--season` or `--time-limit` flag here would move
the fingerprint and void the freeze it is supposed to honour. The only arguments are where
to read the archive, where to write, and how to name the machine.

Before running, both fingerprints are checked against the committed freeze record
(`docs/issue43_candidate_declaration.json`). A mismatch refuses the run rather than
producing a result: per `docs/candidate_declaration_review.md:44-46`, a run whose
fingerprints disagree with the frozen ones "is not the formal run".

What this cannot check is whether the freeze happened. Three owners recording a review is a
governance fact, not a state a script can read, and a `frozen: true` field this same script
wrote would be theatre. So the run refuses unless `--confirm-frozen` is passed, the flag
states exactly what the operator is asserting, and the record names who ran it and where.

The 2025-26 holdout is not read. Clearing the gates makes the candidate eligible for the
holdout protocol and nothing more.
"""

import argparse
import json
import platform
import sys
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, artifact_metadata
from scripts.freeze_candidate_declaration import benchmark_config

from squadopt.backtest.learned_candidate import make_learned_rate_projection_builder
from squadopt.backtest.production_benchmark import (
    ProductionBenchmarkConfig,
    ProductionBenchmarkResult,
    run_declared_candidate_benchmark,
)
from squadopt.backtest.production_reporting import judgement_to_dict, judgement_to_markdown
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    SUPPORTED_SEASONS,
    build_fixture_panel,
    build_panel,
    load_team_codes,
)
from squadopt.prediction.learned_rate import LearnedRateConfig

FROZEN_RECORD = REPOSITORY_ROOT / "docs" / "issue43_candidate_declaration.json"

# What the operator asserts by passing --confirm-frozen. Printed on refusal so the reason is
# actionable rather than a flag name.
FREEZE_REQUIREMENT = (
    "All three owners have recorded their Stage A review of the declaration "
    "(docs/candidate_declaration_review.md:27) and the freeze is recorded "
    "(docs/issue43_handoff_acceptance.md:45, item 17). Until then no formal gate run may "
    "start, and a run made anyway is not the formal run."
)


class GateRunRefused(Exception):
    """The run must not proceed. Raised before any measurement is made."""


def read_frozen_record(path: Path = FROZEN_RECORD) -> dict[str, object]:
    """Read the committed freeze record."""

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GateRunRefused(f"Cannot read the freeze record at {path}: {error}") from error
    if not isinstance(loaded, dict):
        raise GateRunRefused(f"The freeze record at {path} is not an object.")
    return loaded


def verify_frozen_fingerprints(
    record: dict[str, object],
    *,
    config: ProductionBenchmarkConfig,
) -> None:
    """Refuse unless the objects about to run reproduce the committed fingerprints.

    Step 7 of the review procedure, applied *before* the run rather than after: a mismatch
    means the code and the frozen record describe different candidates, and measuring first
    would spend the one permitted run on a result that cannot be claimed.
    """

    expected_declaration = str(record.get("declaration_fingerprint", ""))
    expected_configuration = str(record.get("benchmark_configuration_fingerprint", ""))
    if not expected_declaration or not expected_configuration:
        raise GateRunRefused(
            "The freeze record carries no fingerprints; it cannot authorise a run."
        )

    actual_declaration = config.candidate_declaration.declaration_fingerprint
    actual_configuration = config.configuration_fingerprint

    mismatches = [
        f"  {name}\n    frozen: {expected}\n    now:    {actual}"
        for name, expected, actual in (
            ("declaration", expected_declaration, actual_declaration),
            ("benchmark configuration", expected_configuration, actual_configuration),
        )
        if expected != actual
    ]
    if mismatches:
        raise GateRunRefused(
            "The code no longer reproduces the frozen fingerprints, so this would not be "
            "the formal run:\n"
            + "\n".join(mismatches)
            + "\n\nThe freeze is void. Either revert what moved the digest, or reissue the "
            "declaration as a new version with a fresh three-owner review "
            "(docs/candidate_declaration_review.md:35-37)."
        )


def run_record(
    result: ProductionBenchmarkResult,
    *,
    frozen: dict[str, object],
    metadata: dict[str, object],
    machine_label: str,
) -> dict[str, object]:
    """Assemble the record the review procedure requires a formal run to keep.

    `docs/candidate_declaration_review.md:69-74` lists declaration, both fingerprints, the
    reports, the commit, the dataset identity, the environment, and the verdict. The machine
    is named because `fit_learned_rate` solves a ridge system through LAPACK, which is not
    bit-identical across machines (`docs/issue43_handoff_acceptance.md:81-84`).
    """

    declared = frozen.get("declaration")
    return {
        "artifact_type": "candidate_gate_run",
        "issue": 43,
        "candidate_id": frozen.get("candidate_id"),
        "declaration": declared if isinstance(declared, dict) else {},
        "declaration_fingerprint": frozen.get("declaration_fingerprint"),
        "benchmark_configuration_fingerprint": frozen.get("benchmark_configuration_fingerprint"),
        "executed_on": machine_label,
        "judgement": judgement_to_dict(result),
        "verdict": result.verdict,
        "formal_run": True,
        "locked_holdout_accessed": False,
        **metadata,
    }


def run_record_markdown(record: dict[str, object]) -> str:
    """Render the run record as the committed summary."""

    judgement = record["judgement"]
    assert isinstance(judgement, dict)
    gates = judgement.get("gates")
    provenance = record.get("provenance")
    environment = record.get("environment")
    lines = [
        "# Issue #43 Formal Gate Run",
        "",
        "Stage B of `docs/candidate_declaration_review.md`, run once against the frozen "
        "declaration. A development gate verdict is not an operational promotion: clearing "
        "the gates makes the candidate eligible for the locked holdout protocol and nothing "
        "more. The 2025-26 holdout was not read.",
        "",
        f"- Candidate: `{record['candidate_id']}`",
        f"- Declaration fingerprint: `{record['declaration_fingerprint']}`",
        f"- Configuration fingerprint: `{record['benchmark_configuration_fingerprint']}`",
        f"- Executed on: {record['executed_on']}",
    ]
    if isinstance(provenance, dict):
        lines += [
            f"- Repository commit: `{provenance.get('repository_commit')}`"
            + (" (**working tree dirty**)" if provenance.get("working_tree_dirty") else ""),
            f"- Dataset snapshot: `{provenance.get('archive_repository')}"
            f"@{provenance.get('archive_commit')}`",
        ]
    if isinstance(environment, dict):
        lines.append(
            f"- Environment: Python {environment.get('python')}, "
            f"pandas {environment.get('pandas')}, ortools {environment.get('ortools')}"
        )
    lines += ["", f"## Verdict: `{record['verdict']}`", ""]
    if isinstance(gates, list):
        lines += ["| Gate | Requirement | Measured | Result |", "| --- | --- | ---: | --- |"]
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            outcome = "pass" if gate.get("passed") else "**FAIL**"
            lines.append(
                f"| `{gate.get('name')}` | {gate.get('requirement')} "
                f"| {float(gate.get('measured', 0.0)):+.4f} | {outcome} |"
            )
    lines += [
        "",
        "The full judgement, including per-fold results and the paired comparisons, is in "
        "the JSON beside this document.",
    ]
    return "\n".join(lines) + "\n"


def _history_seasons(evaluated: tuple[str, ...]) -> list[str]:
    """The evaluated seasons plus the one before the earliest, for carry-over."""

    earliest = min(evaluated)
    earlier = [season for season in SUPPORTED_SEASONS if season < earliest]
    return sorted({*evaluated, *earlier[-1:]})


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--confirm-frozen",
        action="store_true",
        help="assert that the declaration is frozen; see the module docstring",
    )
    parser.add_argument(
        "--machine-label",
        default=None,
        help="how to name the executing machine in the committed record; "
        "defaults to this host's name",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "artifacts" / "candidate_gate"
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "issue43_formal_gate_run.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    config = benchmark_config()

    try:
        frozen = read_frozen_record()
        verify_frozen_fingerprints(frozen, config=config)
    except GateRunRefused as error:
        print(f"Refusing to run:\n{error}")
        return 1

    if not arguments.confirm_frozen:
        print(
            "Refusing to run: --confirm-frozen was not given.\n\n"
            f"{FREEZE_REQUIREMENT}\n\n"
            "Both fingerprints match the committed record, so the code is ready; what is "
            "missing is the assertion that the reviews are in."
        )
        return 1

    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}. Run scripts.fetch_historical_data first.")
        return 1

    loaded = _history_seasons(tuple(config.seasons))
    print(f"Loading {', '.join(loaded)} from {archive_root}")
    try:
        panel = build_panel(archive_root, seasons=loaded)
        fixtures = build_fixture_panel(archive_root, seasons=loaded)
        team_codes = pd.concat(
            [load_team_codes(archive_root, season).assign(season=season) for season in loaded],
            ignore_index=True,
        )
    except DataError as error:
        print(f"Could not load the archive:\n  {error}")
        return 1

    builder = make_learned_rate_projection_builder(
        fixtures=fixtures,
        team_codes=team_codes,
        config=config.production_config,
        learned_config=LearnedRateConfig(window=config.production_config.rate_window),
        cross_season=config.cross_season_config,
    )

    print(
        f"Judging {len(config.seasons)} season(s) over {len(panel):,} rows, once, against "
        f"declaration {config.candidate_declaration.declaration_fingerprint[:16]}…"
    )
    try:
        result = run_declared_candidate_benchmark(panel, builder, config)
    except DataError as error:
        print(f"The run failed and produced no verdict:\n  {error}")
        return 1

    machine_label = arguments.machine_label or platform.node() or "unnamed"
    metadata = artifact_metadata(panel_rows=len(panel))
    record = run_record(result, frozen=frozen, metadata=metadata, machine_label=machine_label)

    print(f"\nFolds: {result.fold_count}")
    for label, value in sorted(result.mean_realized_points.items()):
        print(f"  {label:<11} mean realized {value:.4f}")
    print()
    for gate in result.gates:
        print(f"  {'PASS' if gate.passed else 'FAIL'}  {gate.name}: {gate.measured:+.4f}")
    print(f"\nVerdict: {result.verdict}")
    print("Recorded as produced. A development gate verdict is not an operational promotion.")

    output_dir: Path = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"issue43_formal_gate_run_{ARCHIVE_COMMIT[:12]}.json"
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    judgement_path = output_dir / "issue43_formal_gate_judgement.md"
    judgement_path.write_text(judgement_to_markdown(result), encoding="utf-8")
    summary_path: Path = arguments.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(run_record_markdown(record), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {judgement_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
