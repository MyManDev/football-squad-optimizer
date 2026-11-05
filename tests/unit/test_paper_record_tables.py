"""`scripts/paper_record_tables.py` on small synthetic records, never the committed ones.

The runner's promise is that every number it writes can be found again in a record: each
provenance row and each figure pointer is resolved here against the fixture it was read from.
The fixtures carry three decision folds and four sampler folds, written with the summaries the
records would hold, so the arithmetic checks hold until a test breaks one on purpose. Every
candidate record and every sampler arm has numbers of its own, and the expected pairing of
labels and records is written out below by path, so a label read from the wrong record fails.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import socket
import statistics
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import paper_record_tables as tables
from scripts.paper_record_tables import RecordError, Records, main, resolve

LINEAR_FOLDS = {"2021-22-gw02": 50.0, "2021-22-gw03": 60.0, "2022-23-gw02": 40.0}
CANDIDATE_FOLDS = {"2021-22-gw02": 52.0, "2021-22-gw03": 60.0, "2022-23-gw02": 35.0}

#: Each candidate's label, its record by path and the shift that gives its numbers their own
#: values: the candidate's folds, MAE and scope all move with it.
CANDIDATE_RECORDS: dict[str, tuple[str, float]] = {
    "Boosted pair": ("docs/research/phase_c_gradient_boosting_comparison.json", 0.0),
    "Boosted pair, v2 feature contract": (
        "docs/research/phase_c_feature_contract_v2_comparison.json",
        1.0,
    ),
    "Points-only boosting": ("docs/research/phase_c_gradient_boosting_points_comparison.json", 2.0),
    "Regime-gated experts": ("docs/research/moe_regime.json", 3.0),
    "Gated mixture": ("docs/research/moe_mixture.json", 4.0),
}

FOUNDATION = "docs/phase_d_component_squad_calibration.json"
BLOCK = "docs/research/team_match_block_sampler.json"
JOINT = "docs/research/moe_sampler.json"

#: Each sampler arm by record path and arm pointer: its label and four fold PITs of its own.
SAMPLER_ARMS: dict[tuple[str, str], tuple[str, tuple[float, ...]]] = {
    (FOUNDATION, "/verdict"): ("foundation", (0.05, 0.5, 0.6, 0.95)),
    (BLOCK, "/control_arm"): ("foundation", (0.04, 0.45, 0.55, 0.9)),
    (BLOCK, "/candidate_arm"): ("team_match_block", (0.08, 0.3, 0.7, 0.85)),
    (JOINT, "/control_arm"): ("foundation", (0.02, 0.06, 0.6, 0.8)),
    (JOINT, "/block_arm"): ("team_match_block", (0.07, 0.35, 0.65, 0.99)),
    (JOINT, "/candidate_arm"): ("team_match_joint", (0.2, 0.4, 0.5, 0.75)),
}

S1_BOUNDS = [0.43, 0.57]
S2_BOUNDS = [0.04, 0.16]


def _metrics(log_loss: float, minutes: float, points: float) -> dict[str, Any]:
    # Two seasons of ten rows each around the pooled MAE, so the pooled value is their mean.
    seasons = {
        season: {"points": {"mean_absolute_error": points + offset, "observations": 10}}
        for season, offset in (("2024-25", -0.01), ("2025-26", 0.01))
    }
    return {
        "overall": {
            "appearance": {"log_loss": log_loss},
            "minutes": {"mean_absolute_error": minutes},
            "points": {"mean_absolute_error": points, "observations": 20},
        },
        "by_season": seasons,
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


def _summary(prefix: str, candidate_folds: dict[str, float]) -> dict[str, Any]:
    differences = [candidate_folds[fold] - LINEAR_FOLDS[fold] for fold in LINEAR_FOLDS]
    wins = sum(difference > 0 for difference in differences)
    ties = sum(difference == 0 for difference in differences)
    return {
        "paired_folds": len(differences),
        f"{prefix}mean": sum(differences) / len(differences),
        f"{prefix}median": statistics.median(differences),
        f"{prefix}interval_90": [-3.0, 1.5],
        "wins_ties_losses": [wins, ties, len(differences) - wins - ties],
        "by_season_mean": {"2021-22": 1.0, "2022-23": -5.0},
    }


def _candidate_record(candidate: tables.Candidate, shift: float) -> dict[str, Any]:
    arm = candidate.candidate_arm.rsplit("/", 1)[1]
    linear = candidate.linear_arm.rsplit("/", 1)[1]
    folds = {fold: score + shift for fold, score in CANDIDATE_FOLDS.items()}
    arms = {arm: _arm(folds), linear: _arm(LINEAR_FOLDS)}
    if candidate.mean.endswith("/mean"):
        decision: dict[str, Any] = {"v2_features_minus_linear": _summary("", folds), "arms": arms}
    else:
        prefix = candidate.mean.rsplit("/", 1)[1].removesuffix("mean")
        decision = {**_summary(prefix, folds), "arms": arms}
    decision["scope"] = f"reading {shift:g}; how it was scored"
    return {
        "declaration": f"docs/research/declaration_{shift:g}.md",
        "arm_manifests": {
            "control_arm": {"fold_count": 6, "scored_fold_count": 6},
            "candidate_arm": {"fold_count": 6, "scored_fold_count": 5},
        },
        "comparison": {
            "arms": {"control": {"name": "control_arm"}, "candidate": {"name": "candidate_arm"}},
            "metrics": {
                "control": _metrics(0.35, 16.0, 1.07),
                "candidate": _metrics(0.33, 15.0, 1.05 + shift / 100),
            },
            "primary_season": _season("2025-26", 0.02),
            "control_era_season": _season("2024-25", 0.01),
            "verdict": {"verdict": "candidate_preferred"},
        },
        "decision_level_reading": decision,
    }


def _sampler_arm(pits: tuple[float, ...], seasons: bool = True) -> dict[str, Any]:
    below = sum(pit < 0.1 for pit in pits)
    mean = sum(pits) / len(pits)
    rate = below / len(pits)
    block: dict[str, Any] = {
        "fold_count": len(pits),
        "mean_probability_integral_transform": mean,
        "realized_below_lower_quantile_count": below,
        "realized_below_lower_quantile_rate": rate,
    }
    if seasons:
        block |= {
            "s1_bounds": S1_BOUNDS,
            "s2_bounds": S2_BOUNDS,
            "mean_pit_within_s1_bounds": S1_BOUNDS[0] <= mean <= S1_BOUNDS[1],
            "tail_rate_within_s2_bounds": S2_BOUNDS[0] <= rate <= S2_BOUNDS[1],
            "seasons": {"2021-22": {"fold_count": 2, "realized_below_lower_quantile_count": below}},
        }
    return block


def _sampler_fold(pit: float) -> dict[str, Any]:
    return {"probability_integral_transform": pit, "realized_below_q10": pit < 0.1}


def _sampler_record(record: str) -> dict[str, Any]:
    """The record's arms, and four folds holding its top-level arm and each other arm's PIT."""

    arms = {arm: pits for (path, arm), (_, pits) in SAMPLER_ARMS.items() if path == record}
    top = "/verdict" if "/verdict" in arms else "/candidate_arm"
    document: dict[str, Any] = {
        arm[1:]: _sampler_arm(pits, seasons=arm != "/verdict") for arm, pits in arms.items()
    }
    document["folds"] = [
        {
            "fold_id": f"2021-22-gw{index + 11:02d}",
            **_sampler_fold(arms[top][index]),
            **{arm[1:]: _sampler_fold(pits[index]) for arm, pits in arms.items() if arm != top},
        }
        for index in range(4)
    ]
    return document


def _seed_arm(counts: dict[str, int], ceiling: int) -> dict[str, Any]:
    within = [seed for seed, count in counts.items() if count <= ceiling]
    return {
        "counts_by_seed": counts,
        "min_count": min(counts.values()),
        "max_count": max(counts.values()),
        "mean_count": statistics.fmean(counts.values()),
        "seeds_within_s2_band": len(within),
        "seeds_within_s2_band_ids": within,
        "fixed_count_outside_the_redrawn_folds": 1,
    }


def _records() -> dict[str, Any]:
    structure = {candidate.record: candidate for candidate in tables.CANDIDATES}
    records: dict[str, Any] = {
        record: _candidate_record(structure[record], shift)
        for record, shift in CANDIDATE_RECORDS.values()
    }
    v2 = records["docs/research/phase_c_feature_contract_v2_comparison.json"]
    v2["decision_level_reading"] |= {"added_after_result": True, "descriptive_only": True}
    boosted = records["docs/research/phase_c_gradient_boosting_comparison.json"]
    boosted["decision_level_reading"]["note"] = "reported beside the rule; not part of it"
    for record in (FOUNDATION, BLOCK, JOINT):
        records[record] = _sampler_record(record)
    records[FOUNDATION]["verdict"].update({"s1_passes": True, "s2_passes": False})
    records[JOINT]["seed_sensitivity_added_after_the_result"] = {
        "status": "descriptive, added after the result; decides nothing",
        "arms": {
            "block_arm": _seed_arm({"0": 3, "1": 4}, ceiling=3),
            "candidate": _seed_arm({"0": 1, "1": 2, "2": 1}, ceiling=1),
        },
        "plug_in_lower_tail_count": {
            "block_arm": {"band_ceiling_count": 3},
            "candidate": {"band_ceiling_count": 1},
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
        path.write_text(json.dumps(document, indent=1), encoding="utf-8", newline="\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write(tmp_path, _records())
    return tmp_path


def _run(root: Path, folder: str = "tables") -> tuple[int, Path]:
    output = root / "artifacts" / folder
    return main(["--root", str(root), "--output-dir", str(output)]), output


def test_every_table_number_resolves_to_its_record_and_pointer(root: Path) -> None:
    code, output = _run(root)

    assert code == 0
    provenance = _read_csv(output / "provenance.csv")
    assert {row["table"] for row in provenance} == {
        "table_candidates_player_level",
        "table_candidates_decision_level",
        "table_candidates_reading_status",
        "table_sampler_calibration",
        "table_joint_sampler_seeds",
        "table_joint_sampler_seed_summary",
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


def test_each_candidate_label_reads_its_own_record(root: Path) -> None:
    _, output = _run(root)

    provenance = _read_csv(output / "provenance.csv")
    for name in (
        "table_candidates_player_level",
        "table_candidates_decision_level",
        "table_candidates_reading_status",
    ):
        for index, row in enumerate(_read_csv(output / f"{name}.csv")):
            if row["candidate"] not in CANDIDATE_RECORDS:
                continue
            record, shift = CANDIDATE_RECORDS[row["candidate"]]
            cited = {
                cell["record"]
                for cell in provenance
                if cell["table"] == name and cell["row"] == str(index)
            }
            assert cited == {record}, (name, row["candidate"])
            if name == "table_candidates_decision_level":
                assert float(row["candidate_minus_linear_mean"]) == shift - 1.0
            if name == "table_candidates_player_level":
                assert float(row["candidate_points_mae"]) == 1.05 + shift / 100
    for name, label in (
        ("figure_decision_fold_differences", "candidate"),
        ("figure_decision_by_season", "candidate"),
        ("figure_points_mae_against_squad_points", "arm"),
    ):
        for row in _read_csv(output / f"{name}.csv"):
            expected = CANDIDATE_RECORDS.get(row[label], (CANDIDATE_RECORDS["Boosted pair"][0],))
            assert row["record"] == expected[0], (name, row[label])


def test_each_sampler_arm_reads_its_own_folds(root: Path) -> None:
    _, output = _run(root)

    calibration = _read_csv(output / "table_sampler_calibration.csv")
    assert [(row["record"], row["arm"]) for row in calibration] == list(SAMPLER_ARMS)
    pits: dict[tuple[str, str], list[float]] = {}
    for row in _read_csv(output / "figure_sampler_pit.csv"):
        key = (row["record"], row["arm"])
        assert row["sampler"] == SAMPLER_ARMS[key][0], key
        pits.setdefault(key, []).append(float(row["pit"]))
    assert pits == {key: list(arm[1]) for key, arm in SAMPLER_ARMS.items()}
    for row in calibration:
        label, arm_pits = SAMPLER_ARMS[(row["record"], row["arm"])]
        assert row["sampler"] == label
        assert float(row["mean_pit"]) == sum(arm_pits) / len(arm_pits)


def test_the_fold_differences_reproduce_each_recorded_summary(root: Path) -> None:
    _, output = _run(root)

    checks = _read_csv(output / "checks.csv")
    assert checks
    assert all(check["holds"] == "true" for check in checks)
    differences = _read_csv(output / "figure_decision_fold_differences.csv")
    assert [row["difference"] for row in differences[:3]] == ["2.0", "0.0", "-5.0"]


def test_a_recorded_summary_that_its_detail_does_not_give_fails_its_check(root: Path) -> None:
    records = _records()
    records[tables.MIXTURE]["decision_level_reading"]["candidate_minus_linear_mean"] = 0.25
    records[JOINT]["candidate_arm"]["realized_below_lower_quantile_count"] = 3
    records[BLOCK]["candidate_arm"]["tail_rate_within_s2_bounds"] = True
    seeds = records[JOINT]["seed_sensitivity_added_after_the_result"]
    seeds["arms"]["candidate"]["seeds_within_s2_band"] = 3
    regime = records[tables.REGIME]["comparison"]["metrics"]["candidate"]
    regime["overall"]["points"]["mean_absolute_error"] = 0.9
    _write(root, records)

    code, output = _run(root)

    assert code == 1
    failed = [check for check in _read_csv(output / "checks.csv") if check["holds"] == "false"]
    assert [(check["record"], check["pointer"]) for check in failed] == [
        (tables.MIXTURE, "/decision_level_reading/candidate_minus_linear_mean"),
        (JOINT, "/candidate_arm/realized_below_lower_quantile_count"),
        (BLOCK, "/candidate_arm/tail_rate_within_s2_bounds"),
        (JOINT, "/seed_sensitivity_added_after_the_result/arms/candidate/seeds_within_s2_band"),
        (tables.REGIME, "/comparison/metrics/candidate/overall/points/mean_absolute_error"),
    ]


def test_each_seed_row_cites_the_band_ceiling_of_its_own_arm(root: Path) -> None:
    _, output = _run(root)

    rows = _read_csv(output / "table_joint_sampler_seeds.csv")
    assert {(row["arm"], row["band_ceiling_count"]) for row in rows} == {
        ("block_arm", "3"),
        ("candidate", "1"),
    }
    ceilings = [
        row
        for row in _read_csv(output / "provenance.csv")
        if row["table"] == "table_joint_sampler_seeds" and row["column"] == "band_ceiling_count"
    ]
    for cell, row in zip(ceilings, rows, strict=True):
        assert f"/plug_in_lower_tail_count/{row['arm']}/" in cell["pointer"]
    summary = _read_csv(output / "table_joint_sampler_seed_summary.csv")
    assert [(row["arm"], row["seeds_within_s2_band"]) for row in summary] == [
        ("block_arm", "1"),
        ("candidate", "2"),
    ]


def test_the_reading_status_is_shown_as_each_record_states_it(root: Path) -> None:
    _, output = _run(root)

    decision = {
        row["candidate"]: row for row in _read_csv(output / "table_candidates_decision_level.csv")
    }
    assert decision["Boosted pair, v2 feature contract"]["added_after_result"] == "true"
    assert decision["Boosted pair, v2 feature contract"]["descriptive_only"] == "true"
    assert decision["Boosted pair"]["added_after_result"] == ""
    assert decision["Gated mixture"]["scope"] == "reading 4; how it was scored"
    status = {
        row["candidate"]: row for row in _read_csv(output / "table_candidates_reading_status.csv")
    }
    assert status["Boosted pair"]["note"] == "reported beside the rule; not part of it"
    assert status["Gated mixture"]["declaration"] == "docs/research/declaration_4.md"
    markdown = (output / "tables.md").read_text(encoding="utf-8")
    decision_section = markdown.split("## table_candidates_decision_level")[1].split("## ")[0]
    assert "| reading 4; ... |" in decision_section
    status_section = markdown.split("## table_candidates_reading_status")[1].split("## ")[0]
    assert "| reading 4; how it was scored |" in status_section


def test_the_mae_figure_carries_each_season_beside_the_pooled_value(root: Path) -> None:
    _, output = _run(root)

    rows = _read_csv(output / "figure_points_mae_against_squad_points.csv")
    mixture = next(row for row in rows if row["arm"] == "Gated mixture")
    assert float(mixture["points_mae_2025-26"]) == 1.05 + 4.0 / 100 + 0.01
    assert mixture["points_observations_2025-26"] == "10"
    assert mixture["points_mae_2025-26_pointer"] == (
        "/comparison/metrics/candidate/by_season/2025-26/points/mean_absolute_error"
    )


def _extractor_lf() -> bytes:
    """The extractor this test imports, with CRLF read as LF, as a checkout commits it."""

    return tables.EXTRACTOR_SOURCE.read_bytes().replace(b"\r\n", b"\n")


def _commit_line(output: Path) -> str:
    """The line below the title of `tables.md`, where the commit is named."""

    return (output / "tables.md").read_text(encoding="utf-8").splitlines()[2]


def test_outside_a_git_checkout_the_records_name_no_commit(root: Path) -> None:
    code, output = _run(root)

    assert code == 0
    rows = _read_csv(output / "records.csv")
    assert len(rows) == 12
    assert [row["record"] for row in rows] == [*sorted(_records()), tables.EXTRACTOR]
    assert rows[-1]["sha256_lf"] == hashlib.sha256(_extractor_lf()).hexdigest()
    assert {(row["commit"], row["matches_commit"]) for row in rows} == {("", "")}
    checks = _read_csv(output / "checks.csv")
    assert not [check for check in checks if "committed" in check["check"]]
    assert _commit_line(output).startswith("Commit: no commit read (")


def _git(root: Path, *arguments: str) -> None:
    identity = ("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid")
    settings = ("-c", "commit.gpgsign=false", "-c", "core.autocrlf=false")
    command = ["git", "-C", str(root), *identity, *settings, *arguments]
    subprocess.run(command, check=True, capture_output=True)


def _commit(root: Path, extractor: bytes | None) -> str:
    """Commit the fixture records, and `extractor` at the extractor's path; return HEAD."""

    _git(root, "init", "-q")
    _git(root, "add", "docs")
    if extractor is not None:
        path = root / tables.EXTRACTOR
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(extractor)
        _git(root, "add", tables.EXTRACTOR)
    _git(root, "commit", "-q", "-m", "records")
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_each_record_is_compared_with_the_committed_one_line_endings_aside(root: Path) -> None:
    head = _commit(root, _extractor_lf())
    code, output = _run(root, "first")
    first = {row["record"]: row for row in _read_csv(output / "records.csv")}

    assert code == 0
    assert len(first) == 12
    assert {row["matches_commit"] for row in first.values()} == {"true"}
    assert {row["commit"] for row in first.values()} == {head}
    assert all(row["blob_at_commit"] == row["git_blob_lf"] for row in first.values())
    assert _commit_line(output) == (
        f"Commit: `{head}`; the extractor and every record read are the ones committed there."
    )

    # A Windows checkout under core.autocrlf holds the same record with CRLF line endings.
    path = root / tables.REGIME
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    code, output = _run(root, "crlf")
    crlf = {row["record"]: row for row in _read_csv(output / "records.csv")}

    assert code == 0
    assert crlf == first

    records = _records()
    records[tables.MIXTURE]["comparison"]["verdict"]["verdict"] = "edited"
    _write(root, records)
    code, output = _run(root, "edited")
    edited = {row["record"]: row for row in _read_csv(output / "records.csv")}

    assert code == 1
    assert edited[tables.MIXTURE]["matches_commit"] == "false"
    failed = [check for check in _read_csv(output / "checks.csv") if check["holds"] == "false"]
    assert [check["record"] for check in failed] == [tables.MIXTURE]
    assert _commit_line(output).startswith(
        f"Commit: `{head}`; the extractor or a record read is not the one committed there"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_an_extractor_edited_after_the_commit_fails_like_an_edited_record(
    root: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    committed = _extractor_lf()
    head = _commit(root, committed)
    # The records are the committed ones; the extractor run is the committed one edited locally.
    edited = tmp_path_factory.mktemp("edited") / "paper_record_tables.py"
    edited.write_bytes(committed + b"# edited after the commit\n")
    monkeypatch.setattr(tables, "EXTRACTOR_SOURCE", edited)

    code, output = _run(root)

    assert code == 1
    rows = _read_csv(output / "records.csv")
    assert [row["matches_commit"] for row in rows] == ["true"] * 11 + ["false"]
    extractor = rows[-1]
    assert extractor["record"] == tables.EXTRACTOR
    assert extractor["commit"] == head
    assert extractor["blob_at_commit"] == tables.git_blob_id(committed)
    assert extractor["git_blob_lf"] == tables.git_blob_id(edited.read_bytes())
    failed = [check for check in _read_csv(output / "checks.csv") if check["holds"] == "false"]
    assert [(check["record"], check["pointer"]) for check in failed] == [(tables.EXTRACTOR, "")]
    message = capsys.readouterr().out
    assert f"FAILS: {tables.EXTRACTOR}: the extractor run is the one committed" in message
    assert _commit_line(output).startswith(
        f"Commit: `{head}`; the extractor or a record read is not the one committed there"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_commit_without_the_extractor_fails_its_check(root: Path) -> None:
    head = _commit(root, None)

    code, output = _run(root)

    assert code == 1
    extractor = _read_csv(output / "records.csv")[-1]
    assert (extractor["record"], extractor["commit"]) == (tables.EXTRACTOR, head)
    assert (extractor["blob_at_commit"], extractor["matches_commit"]) == ("", "false")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_extractor_is_read_with_crlf_as_lf_like_a_record(
    root: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed = _extractor_lf()
    _commit(root, committed)
    # A Windows checkout under core.autocrlf runs the committed extractor with CRLF endings.
    crlf = tmp_path_factory.mktemp("crlf") / "paper_record_tables.py"
    crlf.write_bytes(committed.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(tables, "EXTRACTOR_SOURCE", crlf)

    code, output = _run(root)

    assert code == 0
    extractor = _read_csv(output / "records.csv")[-1]
    assert extractor["git_blob_lf"] == tables.git_blob_id(committed)
    assert extractor["matches_commit"] == "true"


def test_the_extractor_source_is_the_file_at_its_checkout_path() -> None:
    assert tables.EXTRACTOR_SOURCE == tables.REPOSITORY_ROOT / tables.EXTRACTOR
    assert Path(tables.__file__).resolve() == tables.EXTRACTOR_SOURCE


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


def test_a_git_blob_id_is_the_one_git_gives() -> None:
    # `printf 'hello\n' | git hash-object --stdin`
    assert tables.git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_a_json_pointer_unescapes_its_tokens_and_indexes_lists() -> None:
    document = {"a/b": {"c~d": [10, 20]}}

    assert resolve(document, "/a~1b/c~0d/1") == 20
    assert resolve(document, "") == document
    with pytest.raises(KeyError):
        resolve(document, "/a~1b/c~0d/2")
    with pytest.raises(KeyError):
        resolve(document, "a")
