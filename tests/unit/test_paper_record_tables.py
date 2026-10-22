"""`scripts/paper_record_tables.py` on small synthetic records, never the committed ones.

The runner's promise is that every number it writes can be found again in a record: each
provenance row and each figure pointer is resolved here against the fixture it was read from.
The fixtures carry three decision folds and four sampler folds, written with the summaries the
records would hold, so the arithmetic checks hold until a test breaks one on purpose.
"""

from __future__ import annotations

import csv
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from scripts import paper_record_tables as tables
from scripts.paper_record_tables import RecordError, Records, main, resolve

LINEAR_FOLDS = {"2021-22-gw02": 50.0, "2021-22-gw03": 60.0, "2022-23-gw02": 40.0}
CANDIDATE_FOLDS = {"2021-22-gw02": 52.0, "2021-22-gw03": 60.0, "2022-23-gw02": 35.0}


def _metrics(log_loss: float, minutes: float, points: float) -> dict[str, Any]:
    return {
        "overall": {
            "appearance": {"log_loss": log_loss},
            "minutes": {"mean_absolute_error": minutes},
            "points": {"mean_absolute_error": points},
        }
    }


def _season(season: str, difference: float) -> dict[str, Any]:
    return {
        "season": season,
        "control_points_mae": 1.0,
        "candidate_points_mae": 1.0 - difference,
        "mean_paired_difference": difference,
        "interval_low": difference - 0.01,
        "interval_high": difference + 0.01,
    }


def _arm(folds: dict[str, float]) -> dict[str, Any]:
    mean = sum(folds.values()) / len(folds)
    return {
        "ridge_control_mean": 45.0,
        "component_mean": mean,
        "diagnostics": {"mean_difference": mean - 45.0},
        "folds": dict(folds),
    }


def _summary(prefix: str) -> dict[str, Any]:
    differences = [CANDIDATE_FOLDS[fold] - LINEAR_FOLDS[fold] for fold in LINEAR_FOLDS]
    return {
        "paired_folds": len(differences),
        f"{prefix}mean": sum(differences) / len(differences),
        f"{prefix}median": 0.0,
        f"{prefix}interval_90": [-3.0, 1.5],
        "wins_ties_losses": [1, 1, 1],
        "by_season_mean": {"2021-22": 1.0, "2022-23": -5.0},
    }


def _candidate_record(candidate: tables.Candidate) -> dict[str, Any]:
    arm = candidate.candidate_arm.rsplit("/", 1)[1]
    linear = candidate.linear_arm.rsplit("/", 1)[1]
    arms = {arm: _arm(CANDIDATE_FOLDS), linear: _arm(LINEAR_FOLDS)}
    if candidate.mean.endswith("/mean"):
        decision: dict[str, Any] = {"v2_features_minus_linear": _summary(""), "arms": arms}
    else:
        prefix = candidate.mean.rsplit("/", 1)[1].removesuffix("mean")
        decision = {**_summary(prefix), "arms": arms}
    return {
        "comparison": {
            "arms": {"control": {"name": "control_arm"}, "candidate": {"name": "candidate_arm"}},
            "metrics": {
                "control": _metrics(0.35, 16.0, 1.07),
                "candidate": _metrics(0.33, 15.0, 1.05),
            },
            "primary_season": _season("2025-26", 0.02),
            "control_era_season": _season("2024-25", 0.01),
            "verdict": {"verdict": "candidate_preferred"},
        },
        "decision_level_reading": decision,
    }


PITS = (0.05, 0.5, 0.6, 0.95)


def _sampler_arm(pits: tuple[float, ...], seasons: bool = True) -> dict[str, Any]:
    below = sum(pit < 0.1 for pit in pits)
    block: dict[str, Any] = {
        "fold_count": len(pits),
        "mean_probability_integral_transform": sum(pits) / len(pits),
        "realized_below_lower_quantile_count": below,
        "realized_below_lower_quantile_rate": below / len(pits),
        "mean_pit_within_s1_bounds": True,
        "tail_rate_within_s2_bounds": False,
    }
    if seasons:
        block["seasons"] = {
            "2021-22": {"fold_count": 2, "realized_below_lower_quantile_count": below}
        }
    return block


def _fold(index: int, pit: float, **arms: dict[str, Any]) -> dict[str, Any]:
    return {
        "fold_id": f"2021-22-gw{index + 11:02d}",
        "probability_integral_transform": pit,
        "realized_below_q10": pit < 0.1,
        **arms,
    }


def _sampler_fold_arm(pit: float) -> dict[str, Any]:
    return {"probability_integral_transform": pit, "realized_below_q10": pit < 0.1}


def _records() -> dict[str, Any]:
    records: dict[str, Any] = {c.record: _candidate_record(c) for c in tables.CANDIDATES}
    verdict = _sampler_arm(PITS, seasons=False)
    verdict.update({"s1_passes": True, "s2_passes": False})
    records[tables.FOUNDATION] = {
        "verdict": verdict,
        "folds": [_fold(i, pit) for i, pit in enumerate(PITS)],
    }
    records[tables.BLOCK] = {
        "candidate_arm": _sampler_arm(PITS),
        "control_arm": _sampler_arm(PITS),
        "folds": [_fold(i, pit, control_arm=_sampler_fold_arm(pit)) for i, pit in enumerate(PITS)],
    }
    records[tables.JOINT] = {
        "candidate_arm": _sampler_arm(PITS),
        "block_arm": _sampler_arm(PITS),
        "control_arm": _sampler_arm(PITS),
        "folds": [
            _fold(i, pit, control_arm=_sampler_fold_arm(pit), block_arm=_sampler_fold_arm(pit))
            for i, pit in enumerate(PITS)
        ],
        "seed_sensitivity_added_after_the_result": {
            "arms": {"candidate": {"counts_by_seed": {"0": 1, "1": 2}}},
            "plug_in_lower_tail_count": {"candidate": {"band_ceiling_count": 1}},
        },
    }
    scores = {
        "mean_log_score": -2.0,
        "mean_pit": 0.5,
        "lower_tail_rate": 0.04,
        "upper_tail_rate": 0.05,
        "rows": 10,
    }
    fold_block = {
        "folds": 2,
        "wins": 2,
        "ties": 0,
        "losses": 0,
        "mean_difference": 0.4,
        "interval_low": 0.3,
        "interval_high": 0.5,
    }
    records[tables.MIXTURE]["distribution_scoring"] = {
        "components": {
            "points": {
                "pooled": {"control": scores, "candidate": scores},
                "primary_season": {"season": "2025-26", **fold_block},
                "control_era_season": {"season": "2024-25", **fold_block},
            }
        }
    }
    records[tables.FROZEN_EVALUATION] = {
        "decision_comparison": {
            "diagnostics": {"comparable_folds": 3, "mean_difference": 4.5},
            "control": {"mean_realized_squad_points": 45.0},
            "component_base": {"mean_realized_squad_points": 49.5},
        }
    }
    comparison = {
        "arm": "rank_debias",
        "against": "control",
        "paired_folds": 3,
        "mean_difference": -0.8,
    }
    records[tables.RANK_SHRINKAGE] = {
        "primary_comparison": {**comparison, "interval_90": [-1.5, -0.1]},
        "secondary_comparison": {**comparison, "interval_90": [-0.5, 0.5]},
        "gate": {"noise_floor_points_per_gameweek": 1.5},
        "verdict": "measured, not certified",
    }
    records[tables.MEAN_REVERSION] = {
        "comparisons": [
            {
                "variant": "L3_mr_0.75",
                "baseline": "L3_naive",
                "paired_gameweeks": 3,
                "mean_weekly_advantage_points": -0.5,
                "weekly_advantage_block_bootstrap_interval": [-1.5, 0.9],
            }
        ],
        "verdict": {"noise_floor_points_per_gameweek": 1.5, "status": "measured, not certified"},
    }
    return records


def _write(root: Path, records: dict[str, Any]) -> None:
    for record, document in records.items():
        path = root / record
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write(tmp_path, _records())
    return tmp_path


def _run(root: Path) -> tuple[int, Path]:
    output = root / "artifacts" / "tables"
    return main(["--root", str(root), "--output-dir", str(output)]), output


def test_every_table_number_resolves_to_its_record_and_pointer(root: Path) -> None:
    code, output = _run(root)

    assert code == 0
    provenance = _read_csv(output / "provenance.csv")
    assert {row["table"] for row in provenance} == {
        "table_candidates_player_level",
        "table_candidates_decision_level",
        "table_sampler_calibration",
        "table_joint_sampler_seeds",
        "table_mixture_distribution",
        "table_mixture_log_score_folds",
        "table_planning_measurements",
    }
    for row in provenance:
        document = json.loads((root / row["record"]).read_text(encoding="utf-8"))
        assert tables._text(resolve(document, row["pointer"])) == row["value"], row


def test_every_figure_value_resolves_to_its_pointer(root: Path) -> None:
    _, output = _run(root)

    figures = sorted(output.glob("figure_*.csv"))
    assert [path.stem for path in figures] == [
        "figure_decision_by_season",
        "figure_decision_fold_differences",
        "figure_points_mae_against_squad_points",
        "figure_s2_counts",
        "figure_sampler_pit",
    ]
    for path in figures:
        rows = _read_csv(path)
        assert rows, path.name
        for row in rows:
            document = json.loads((root / row["record"]).read_text(encoding="utf-8"))
            for column in (name for name in row if name.endswith("_pointer")):
                value = row[column.removesuffix("_pointer")]
                pointers = row[column].split(" - ")
                resolved = [resolve(document, pointer) for pointer in pointers]
                if len(resolved) == 2:
                    assert float(value) == resolved[0] - resolved[1]
                else:
                    assert tables._text(resolved[0]) == value


def test_the_fold_differences_reproduce_each_recorded_summary(root: Path) -> None:
    _, output = _run(root)

    checks = _read_csv(output / "checks.csv")
    assert checks
    assert all(check["holds"] == "true" for check in checks)
    differences = _read_csv(output / "figure_decision_fold_differences.csv")
    assert [row["difference"] for row in differences[:3]] == ["2.0", "0.0", "-5.0"]


def test_a_recorded_mean_that_its_folds_do_not_give_fails_its_check(root: Path) -> None:
    records = _records()
    records[tables.MIXTURE]["decision_level_reading"]["candidate_minus_linear_mean"] = 0.25
    records[tables.JOINT]["candidate_arm"]["realized_below_lower_quantile_count"] = 0
    _write(root, records)

    code, output = _run(root)

    assert code == 1
    failed = [check for check in _read_csv(output / "checks.csv") if check["holds"] == "false"]
    assert [(check["record"], check["pointer"]) for check in failed] == [
        (tables.MIXTURE, "/decision_level_reading/candidate_minus_linear_mean"),
        (tables.JOINT, "/candidate_arm/realized_below_lower_quantile_count"),
    ]


def test_a_missing_key_is_refused_with_its_record_and_pointer(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    records = _records()
    del records[tables.REGIME]["comparison"]["verdict"]
    _write(root, records)

    code, output = _run(root)

    assert code == 1
    message = capsys.readouterr().out
    assert tables.REGIME in message
    assert "/comparison/verdict/verdict" in message
    assert not output.exists()


@pytest.mark.parametrize(
    "record", ["src/squadopt/record.json", "docs/../outside.json", "docs/record.md"]
)
def test_only_json_records_under_docs_are_read(root: Path, record: str) -> None:
    (root / "outside.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RecordError, match="only JSON records under docs/"):
        Records(root).document(record)


@pytest.mark.parametrize(
    "directory", ["docs/tables", "src/tables", "scripts/tables", "tests/tables", ".", "artifacts"]
)
def test_inside_the_checkout_only_a_folder_under_artifacts_is_written(
    root: Path, directory: str
) -> None:
    before = sorted(root.rglob("*"))

    code = main(["--root", str(root), "--output-dir", directory])

    assert code == 1
    assert sorted(root.rglob("*")) == before


def test_a_folder_outside_the_checkout_is_written(
    root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("elsewhere") / "tables"

    code = main(["--root", str(root), "--output-dir", str(outside)])

    assert code == 0
    assert (outside / "tables.md").is_file()


def test_the_default_output_directory_is_git_ignored() -> None:
    gitignore = (tables.REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert tables.DEFAULT_OUTPUT.parts[0] == "artifacts"
    assert "artifacts/" in gitignore.splitlines()


def test_the_extraction_opens_no_connection(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the extraction opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    code, _ = _run(root)

    assert code == 0


def test_a_json_pointer_unescapes_its_tokens_and_indexes_lists() -> None:
    document = {"a/b": {"c~d": [10, 20]}}

    assert resolve(document, "/a~1b/c~0d/1") == 20
    assert resolve(document, "") == document
    with pytest.raises(KeyError):
        resolve(document, "/a~1b/c~0d/2")
    with pytest.raises(KeyError):
        resolve(document, "a")
