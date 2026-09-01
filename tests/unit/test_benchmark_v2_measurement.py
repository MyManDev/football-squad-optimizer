"""Binding-input and arithmetic tests for Benchmark V2 measurement."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, league_standings_page_payload
from squadopt.evaluation import EvaluationValidationError
from squadopt.experiments.benchmark_v2 import (
    measure_historical_v1_v2,
    measure_settled_entry_parity,
    validate_top100_capture,
)


def _snapshot(source: str, payloads: dict[str, bytes], *, captured: str) -> CapturedSnapshot:
    return CapturedSnapshot(
        metadata=SnapshotMetadata(
            snapshot_id=f"{source}-test",
            source=source,
            captured_at_utc=captured,
            schema_version="snapshot_v1",
            checksums={},
            fingerprint="test-fingerprint",
        ),
        payloads=payloads,
    )


def _top100_page(page: int, first_rank: int) -> bytes:
    return json.dumps(
        {
            "league": {"id": 314, "name": "Overall"},
            "standings": {
                "page": page,
                "has_next": True,
                "results": [
                    {
                        "entry": 1000 + rank_sort,
                        "entry_name": f"Entry {rank_sort}",
                        "player_name": f"Manager {rank_sort}",
                        "rank": rank_sort,
                        "rank_sort": rank_sort,
                    }
                    for rank_sort in range(first_rank, first_rank + 50)
                ],
            },
            "last_updated_data": "2026-09-01T03:34:24Z",
        }
    ).encode("utf-8")


def _deadline_bootstrap() -> bytes:
    return json.dumps(
        {
            "events": [
                {
                    "id": 3,
                    "deadline_time": "2026-09-04T17:30:00Z",
                    "finished": False,
                }
            ]
        }
    ).encode("utf-8")


def test_top100_capture_requires_and_freezes_rank_sort_one_through_100() -> None:
    snapshot = _snapshot(
        "fpl-top100",
        {
            BOOTSTRAP_PAYLOAD: _deadline_bootstrap(),
            league_standings_page_payload(314, 1): _top100_page(1, 1),
            league_standings_page_payload(314, 2): _top100_page(2, 51),
        },
        captured="2026-09-01T04:07:25Z",
    )

    cohort, diagnostics = validate_top100_capture(snapshot, target_gameweek=3)

    assert len(cohort.entry_ids) == 100
    assert diagnostics["member_count"] == 100
    assert diagnostics["status"] == "pending_settlement"
    assert "entry_ids" not in diagnostics


def test_top100_capture_after_deadline_is_rejected() -> None:
    snapshot = _snapshot(
        "fpl-top100",
        {
            BOOTSTRAP_PAYLOAD: _deadline_bootstrap(),
            league_standings_page_payload(314, 1): _top100_page(1, 1),
            league_standings_page_payload(314, 2): _top100_page(2, 51),
        },
        captured="2026-09-04T18:00:00Z",
    )

    with pytest.raises(EvaluationValidationError, match="not be later"):
        validate_top100_capture(snapshot, target_gameweek=3)


def _parity_snapshot(*, official_points: int = 12) -> CapturedSnapshot:
    positions = [1, 1, *([2] * 5), *([3] * 5), *([4] * 3)]
    starters = {1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14}
    elements = []
    for element_id, element_type in enumerate(positions, start=1):
        minutes = 0 if element_id == 3 else 90
        elements.append(
            {
                "id": element_id,
                "code": 1000 + element_id,
                "first_name": "Player",
                "second_name": str(element_id),
                "team": 1 + (element_id - 1) % 5,
                "element_type": element_type,
                "now_cost": 50,
                "event_points": 0 if minutes == 0 else 1,
                "minutes": minutes,
            }
        )
    bootstrap = json.dumps(
        {
            "events": [
                {
                    "id": 1,
                    "deadline_time": "2026-08-21T17:30:00Z",
                    "finished": True,
                    "data_checked": True,
                }
            ],
            "teams": [{"id": team, "name": f"Team {team}"} for team in range(1, 6)],
            "elements": elements,
        }
    ).encode("utf-8")
    ordered = [*sorted(starters), 2, 7, 12, 15]
    picks = json.dumps(
        {
            "active_chip": None,
            "entry_history": {
                "points": official_points,
                "event_transfers_cost": 0,
                "bank": 0,
            },
            "picks": [
                {
                    "element": element,
                    "position": position,
                    "multiplier": 2 if element == 8 else (1 if position <= 11 else 0),
                    "is_captain": element == 8,
                    "is_vice_captain": element == 9,
                }
                for position, element in enumerate(ordered, start=1)
            ],
        }
    ).encode("utf-8")
    history = json.dumps({"current": [], "past": [], "chips": []}).encode("utf-8")
    return _snapshot(
        "fpl-live",
        {
            BOOTSTRAP_PAYLOAD: bootstrap,
            "entry-99-picks-gw01.json": picks,
            "entry-99-history.json": history,
        },
        captured="2026-08-26T08:31:33Z",
    )


def test_settled_entry_parity_applies_the_real_autosub_and_captain_rules() -> None:
    result = measure_settled_entry_parity(_parity_snapshot(), season="2026-27", gameweek=1)

    assert result["entries_compared"] == 1
    assert result["exact_matches"] == 1
    assert result["max_absolute_difference"] == 0.0
    assert result["status"] == "passed"


def test_settled_entry_parity_reports_a_mismatch_instead_of_hiding_it() -> None:
    result = measure_settled_entry_parity(
        _parity_snapshot(official_points=13), season="2026-27", gameweek=1
    )

    assert result["exact_matches"] == 0
    assert result["max_absolute_difference"] == 1.0
    assert result["status"] == "failed"


def _historical_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    identifier = 0
    for position, count in (("GK", 4), ("DEF", 12), ("MID", 14), ("FWD", 10)):
        for _ in range(count):
            identifier += 1
            rows.append(
                {
                    "fold_id": "2021-22-gw02",
                    "season": "2021-22",
                    "gameweek": 2,
                    "player_id": identifier,
                    "team_id": 1 + (identifier - 1) % 15,
                    "position": position,
                    "predicted_points": 10.0 - identifier / 100,
                    "realized_points": float(identifier % 7),
                }
            )
    residuals = pd.DataFrame(rows)
    panel = residuals.loc[:, ["season", "gameweek", "player_id"]].copy()
    panel["name"] = panel["player_id"].map(lambda value: f"Player {value}")
    panel["price_tenths"] = 50
    panel["minutes"] = 90
    panel.loc[panel["player_id"] == 1, "minutes"] = 0
    ownership = residuals.loc[:, ["season", "gameweek", "player_id"]].copy()
    ownership["selected"] = 100.0 - ownership["player_id"]
    return residuals, panel, ownership


def test_historical_comparison_keeps_v1_and_v2_on_the_same_fold() -> None:
    residuals, panel, ownership = _historical_inputs()

    result = measure_historical_v1_v2(residuals, panel, ownership)

    assert result["status"] == "descriptive_unverified_ownership_timing"
    rows = result["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["overall_gap_change"] == pytest.approx(
        row["v2_gap_template_minus_system"] - row["v1_gap_template_minus_system"]
    )


def test_historical_comparison_rejects_a_holdout_season() -> None:
    residuals, panel, ownership = _historical_inputs()
    residuals["season"] = "2025-26"
    panel["season"] = "2025-26"
    ownership["season"] = "2025-26"

    with pytest.raises(EvaluationValidationError, match="Unexpected benchmark season"):
        measure_historical_v1_v2(residuals, panel, ownership)
