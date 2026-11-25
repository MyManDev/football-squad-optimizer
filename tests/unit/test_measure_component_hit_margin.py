"""The hit margin runner: what it merges, what it refuses and what the record holds.

The chain is not walked here; its arithmetic is tested in ``test_supplied_decision_week.py``
and the protocol's logic in ``test_component_hit_margin.py``. These tests hand the merge
eight synthetic per-process artifacts with a known shape (the component arm best at 10, the
control arm best at 8) and read the record back.
"""

import json
from pathlib import Path

import pytest
import scripts.measure_component_hit_margin as cli

from squadopt.experiments.component_hit_margin import (
    COMPONENT,
    COMPONENT_HIT_MARGIN_CONTRACT_VERSION,
    CONTROL,
    HIT_COST_LEVELS,
    arm_label,
)

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
GAMEWEEKS = tuple(range(2, 14))
HANDOFF = {"table_sha256": "t", "folds": 147, "model_version": "m", "matches_record": True}


def _chain(season: str, forecast: str, level: int) -> dict[str, object]:
    best = 10 if forecast == COMPONENT else 8
    weeks = [
        {
            "gameweek": gameweek,
            "net_points": 50.0 - abs(level - best) + (gameweek % 3),
            "realized_points": 54.0 - abs(level - best) + (gameweek % 3),
            "projected_points": 60.0,
            "solver_status": "OPTIMAL" if gameweek != 2 else "FEASIBLE",
        }
        for gameweek in GAMEWEEKS
    ]
    return {
        "season": season,
        "variant": arm_label(forecast, level),
        "forecast": forecast,
        "hit_cost": level,
        "decisions": len(weeks),
        "net_points": sum(float(week["net_points"]) for week in weeks),
        "realized_points": sum(float(week["realized_points"]) for week in weeks),
        "transfer_hit_points": 4.0 * len(weeks),
        "transfer_count": 20 - level,
        "paid_transfer_count": 12 - level,
        "proven_share": (len(weeks) - 1) / len(weeks),
        "mean_relative_gap": 0.01,
        "carried_blank_rows": 0,
        "carried_unexplained_rows": 0,
        "elapsed_seconds": 1.0,
        "weeks": weeks,
    }


def _artifact(season: str, forecast: str, **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "contract_version": COMPONENT_HIT_MARGIN_CONTRACT_VERSION,
        "repository_commit": "abc123",
        "working_tree_dirty": False,
        "archive_commit": "archive",
        "started_at_utc": "2026-11-23T21:00:00+00:00",
        "finished_at_utc": "2026-11-23T21:30:00+00:00",
        "provenance": {"repository_commit": "abc123"},
        "environment": {"python": "3.11"},
        "season": season,
        "forecast": forecast,
        "hit_costs": list(HIT_COST_LEVELS),
        "pilot_gameweeks": None,
        "component_handoff": HANDOFF if forecast == COMPONENT else None,
        "solver_limits": {
            "solver_time_limit_seconds": 60.0,
            "solver_deterministic_time_limit": 8.0,
        },
        "chains": [_chain(season, forecast, level) for level in HIT_COST_LEVELS],
        "measurement_only": True,
    }
    document.update(overrides)
    return document


def _write(root: Path, documents: list[dict[str, object]]) -> str:
    paths = []
    for index, document in enumerate(documents):
        path = root / f"cell-{index}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(str(path))
    return ",".join(paths)


def _merge(root: Path, documents: list[dict[str, object]]) -> tuple[int, Path]:
    record = root / "record.json"
    code = cli.main(
        [
            "--merge",
            _write(root, documents),
            "--json-output",
            str(record),
            "--markdown-output",
            str(root / "record.md"),
            "--expansion-output",
            str(root / "weeks.json"),
            "--bootstrap-resamples",
            "200",
        ]
    )
    return code, record


def _all_cells() -> list[dict[str, object]]:
    return [_artifact(season, forecast) for season in SEASONS for forecast in (COMPONENT, CONTROL)]


def test_the_merge_writes_the_reading_the_tables_and_the_expansion(tmp_path: Path) -> None:
    code, path = _merge(tmp_path, _all_cells())
    assert code == 0
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["contract_version"] == COMPONENT_HIT_MARGIN_CONTRACT_VERSION
    assert record["seasons"] == list(SEASONS) and record["locked_holdout_accessed"] is False
    assert record["reading"]["reading"] == "move"
    assert record["reading"]["candidate_hit_cost"] == 10
    assert record["reading"]["levels_passing_against_policy"] == [10]
    assert record["reading"]["changes_a_default"] is False
    assert len(record["chains"]) == 2 * len(SEASONS) * len(HIT_COST_LEVELS)
    assert all("weeks" not in chain for chain in record["chains"])
    component = record["pooled_by_level"][COMPONENT]
    assert component["10"]["net_points_per_week"] - component["8"]["net_points_per_week"] == 2.0
    assert component["8"]["decisions"] == len(SEASONS) * len(GAMEWEEKS)
    assert component["8"]["paid_transfers"] == len(SEASONS) * 4
    assert component["8"]["mean_projected_minus_realized"] == pytest.approx(60.0 - 53.0)
    assert record["pooled_by_level"][CONTROL]["8"]["net_points_per_week"] == 51.0
    by_pair = {(row["variant"], row["baseline"]): row for row in record["comparisons"]}
    primary = by_pair[("component_hit10", "component_hit8")]
    assert primary["mean_weekly_advantage_points"] == 2.0
    assert primary["paired_gameweeks"] == len(SEASONS) * len(GAMEWEEKS)
    assert record["solver"]["decisions"] == len(record["chains"]) * len(GAMEWEEKS)
    assert record["solver"]["proven_decisions"] == len(record["chains"]) * (len(GAMEWEEKS) - 1)
    expansion = json.loads((tmp_path / "weeks.json").read_text(encoding="utf-8"))
    assert len(expansion["chains"]) == len(record["chains"])
    assert len(record["expansion"]["sha256"]) == 64
    page = (tmp_path / "record.md").read_text(encoding="utf-8")
    assert "**move**, candidate planning hit cost 10." in page
    assert "Component base: each level against 8" in page
    assert "Form-window control: each level against 4" in page


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda cells: cells[:-1], "each season under each forecast once"),
        (lambda cells: [*cells[:-1], {**cells[-1], "repository_commit": "def456"}], "commits"),
        (lambda cells: [*cells[:-1], {**cells[-1], "pilot_gameweeks": 5}], "pilot"),
        (lambda cells: [*cells[:-1], {**cells[-1], "hit_costs": [4, 8]}], "hit cost grid"),
        (lambda cells: [*cells[:-1], {**cells[-1], "contract_version": "other"}], "contract"),
        (
            lambda cells: [
                {**cells[0], "component_handoff": {**HANDOFF, "table_sha256": "x"}},
                *cells[1:],
            ],
            "different handoffs",
        ),
    ],
)
def test_the_merge_refuses_what_is_not_the_protocol_s_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: object, message: str
) -> None:
    code, path = _merge(tmp_path, damage(_all_cells()))  # type: ignore[operator]
    assert code == 1 and not path.exists()
    assert message in capsys.readouterr().out


def test_a_run_needs_a_development_season_a_forecast_and_the_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--season", "2024-25"]) == 1
    assert "--season and --forecast are required" in capsys.readouterr().out
    assert cli.main(["--season", "2025-26", "--forecast", CONTROL]) == 1
    assert "is locked" in capsys.readouterr().out
    assert (
        cli.main(["--season", "2024-25", "--forecast", COMPONENT, "--archive-root", str(tmp_path)])
        == 1
    )
    assert "--handoff-dir" in capsys.readouterr().out
    target = cli.DOCS_ROOT / "research" / "never.json"
    assert (
        cli.main(
            [
                "--season",
                "2024-25",
                "--forecast",
                CONTROL,
                "--archive-root",
                str(tmp_path),
                "--json-output",
                str(target),
            ]
        )
        == 1
    )
    assert "belongs under artifacts/" in capsys.readouterr().out


def test_the_handoff_is_compared_with_the_component_record(tmp_path: Path) -> None:
    source = {
        "table_sha256": "a",
        "roster_sha256": "b",
        "manifest_sha256": "c",
        "model_version": "m",
        "producer_repository_commit": "p",
    }
    record = tmp_path / "evaluation.json"
    record.write_text(json.dumps({"source": source}), encoding="utf-8")
    assert all(cli.handoff_matches_record(source, record).values())
    changed = cli.handoff_matches_record({**source, "table_sha256": "z"}, record)
    assert changed["table_sha256"] is False and changed["roster_sha256"] is True
