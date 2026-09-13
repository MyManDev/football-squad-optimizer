import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.unit.test_advice_record import _world_context
from tests.unit.test_live_transfers import _world
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard_baselines import baseline_score, human_baseline_rows
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.live import LedgerEntry

world = _world


def test_baseline_captain_uses_lagged_captain_counts_not_settled_points() -> None:
    _, pool, outcomes = decision_inputs()
    pool["name"] = pool["player_id"].astype(str)
    pool["team_id"] = [player % 5 for player in range(1, 16)]
    pool["price_tenths"] = 50
    pool["ownership"] = [
        100 if player in (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15) else 1 for player in range(1, 16)
    ]
    counts = {player: float(100 if player == 9 else 0) for player in range(1, 16)}
    result = baseline_score(pool, outcomes, captain_counts=counts)
    assert result["net"] == pytest.approx(100)
    assert result["diagnostics"]["captain_shortfall"] == 1
    assert result["construction"].endswith("replay")


@pytest.fixture
def baseline_world(
    world: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[LedgerEntry, tuple, pd.DataFrame]:
    inputs, projection, _ = _world_context(world)
    pre = read_snapshot(world["snapshot_root"], world["gw2_id"])
    bootstrap = json.loads(pre.payloads[BOOTSTRAP_PAYLOAD])
    for event in bootstrap["events"]:
        event["data_checked"] = event["finished"]
        if event["id"] == 2:
            event.update(finished=True, data_checked=True)
    for player in bootstrap["elements"]:
        player["selected_by_percent"] = "10.0"
    pre = replace(pre, payloads={**pre.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()})
    settled = replace(
        pre,
        metadata=replace(
            pre.metadata, snapshot_id="settled", captured_at_utc="2026-08-30T12:00:00Z"
        ),
        payloads={
            **pre.payloads,
            live_payload(2): json.dumps(
                {
                    "elements": [
                        {"id": row["id"], "stats": {"minutes": 90, "total_points": 2, "starts": 1}}
                        for row in bootstrap["elements"]
                    ]
                }
            ).encode(),
        },
    )
    projection.table.to_csv(tmp_path / "projections.csv", index=False)
    entry = LedgerEntry(
        "2026-27",
        2,
        {"snapshot_id": pre.metadata.snapshot_id, "deadline_utc": inputs.deadline.deadline_utc},
        {"source_snapshot_id": "settled"},
        tmp_path,
    )
    evidence = pd.DataFrame(
        {
            "player_id": projection.table["player_id"],
            "season": "2026-27",
            "target_gameweek": 2,
            "deadline_timestamp_utc": inputs.deadline.deadline_utc,
            "captured_at_utc": "2026-08-26T12:00:00Z",
            "source_snapshot_ids": "elite",
            "elite_start_count_lag1": 10,
            "elite_captain_count_lag1": 1,
            "elite_members_observed": 100,
            "elite_cohort_size": 100,
        }
    )
    (tmp_path / "player_evidence_v1_2026-27_gw02_top100.csv").touch()
    monkeypatch.setattr(
        "squadopt.application.scoreboard_baselines.read_player_evidence_artifact",
        lambda *args: evidence,
    )
    return entry, (pre, settled), evidence


def rows_for(baseline_world, *, evidence_root=None):
    entry, snapshots, _ = baseline_world
    return human_baseline_rows(
        (entry,), snapshots, evidence_root=evidence_root, as_of_utc="2026-08-30T12:00:00Z"
    ).get(2, {})


def test_standard_evidence_filename_is_read_and_late_evidence_is_excluded(
    baseline_world,
    tmp_path: Path,
) -> None:
    rows = rows_for(baseline_world, evidence_root=tmp_path)
    assert rows["elite_xi"]["net"] == 24
    assert rows["ownership_template"]["net"] == 24
    assert (
        rows["ownership_template"]["source_snapshot_id"]
        == baseline_world[1][0].metadata.snapshot_id
    )
    assert rows["elite_xi"]["outcome_snapshot_id"] == "settled"
    baseline_world[2]["captured_at_utc"] = "2026-08-28T12:00:00Z"
    assert "elite_xi" not in rows_for(baseline_world, evidence_root=tmp_path)


@pytest.mark.parametrize("missing", ["capture", "outcome", "ownership", "elite", "coverage"])
def test_missing_information_does_not_become_a_zero(baseline_world, tmp_path, missing) -> None:
    entry, snapshots, evidence = baseline_world
    if missing == "capture":
        snapshots = snapshots[1:]
    elif missing == "outcome":
        snapshots = snapshots[:1]
    elif missing == "ownership":
        bootstrap = json.loads(snapshots[0].payloads[BOOTSTRAP_PAYLOAD])
        del bootstrap["elements"][0]["selected_by_percent"]
        snapshots = (
            replace(
                snapshots[0],
                payloads={
                    **snapshots[0].payloads,
                    BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
                },
            ),
            snapshots[1],
        )
    elif missing == "elite":
        evidence["elite_members_observed"] = 99
    else:
        evidence.drop(evidence.index[0], inplace=True)
    rows = rows_for((entry, snapshots, evidence), evidence_root=tmp_path)
    if missing in ("capture", "outcome"):
        assert rows == {}
    elif missing == "ownership":
        assert "ownership_template" not in rows
        assert rows["elite_xi"]["net"] == 24
    else:
        assert "elite_xi" not in rows
        assert rows["ownership_template"]["net"] == 24


@pytest.mark.parametrize("invalid", ["deadline", "unchecked", "future", "season"])
def test_unusable_captures_do_not_supply_human_rows(baseline_world, tmp_path, invalid) -> None:
    entry, (pre, settled), evidence = baseline_world
    if invalid == "deadline":
        pre = replace(
            pre, metadata=replace(pre.metadata, captured_at_utc=entry.decision["deadline_utc"])
        )
    elif invalid == "unchecked":
        bootstrap = json.loads(settled.payloads[BOOTSTRAP_PAYLOAD])
        for event in bootstrap["events"]:
            event["data_checked"] = False
        settled = replace(
            settled,
            payloads={**settled.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()},
        )
    elif invalid == "future":
        settled = replace(
            settled, metadata=replace(settled.metadata, captured_at_utc="2026-08-31T00:00:00Z")
        )
    else:
        entry = replace(entry, season="2025-26")
    assert rows_for((entry, (pre, settled), evidence), evidence_root=tmp_path) == {}


def test_evidence_for_another_decision_refuses_publication(baseline_world, tmp_path) -> None:
    from squadopt.data.errors import DataError

    baseline_world[2]["target_gameweek"] = 3
    with pytest.raises(DataError, match="another decision"):
        rows_for(baseline_world, evidence_root=tmp_path)


def test_missing_projection_minutes_stay_unmeasured(baseline_world) -> None:
    entry, _, _ = baseline_world
    table = pd.read_csv(entry.directory / "projections.csv")
    table.drop(columns=["expected_minutes"], errors="ignore").to_csv(
        entry.directory / "projections.csv", index=False
    )
    row = rows_for(baseline_world)["ownership_template"]
    assert row["net"] == 24
    assert row["diagnostics"]["minutes_shortfall"] is None


@pytest.fixture
def publication_world(baseline_world, tmp_path):
    from squadopt.application.scoreboard import ScoreboardPublicationRequest
    from squadopt.data.snapshots import write_snapshot
    from squadopt.live.ledger import write_manifest

    entry, snapshots, _ = baseline_world
    root = tmp_path / "captures"
    captured = [
        write_snapshot(
            root,
            source="fpl-live",
            captured_at_utc=item.metadata.captured_at_utc,
            payloads=item.payloads,
        )
        for item in snapshots
    ]
    ledger = tmp_path / "ledger" / entry.season / "gw02"
    ledger.mkdir(parents=True)
    # Use the real fixture's projected pool and a matching legal fixture decision.
    pool = pd.read_csv(entry.directory / "projections.csv")
    from squadopt.evaluation.benchmarks import build_constrained_ownership_template

    players = pool.copy()
    players["ownership"] = 10
    frozen = build_constrained_ownership_template(players).decision
    decision = {
        **entry.decision,
        "snapshot_id": captured[0].snapshot_id,
        "squad_player_ids": frozen.squad["player_id"].tolist(),
        "starting_xi_player_ids": list(frozen.starting_xi),
        "bench_player_ids": list(frozen.bench),
        "ordered_bench_player_ids": list(frozen.bench),
        "captain_player_id": frozen.captain_id,
        "vice_captain_player_id": frozen.vice_captain_id,
        "projected_score": 24.0,
        "mode": "live",
    }
    (ledger / "decision.json").write_text(json.dumps(decision, default=int), encoding="utf-8")
    pool.to_csv(ledger / "projections.csv", index=False)
    write_manifest(ledger)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [{"entry_id": 11, "label": "member"}],
            }
        ),
        encoding="utf-8",
    )
    return ScoreboardPublicationRequest(
        root,
        captured[1].snapshot_id,
        registry,
        tmp_path / "ledger",
        tmp_path / "site",
        352490,
        season=entry.season,
    ), ledger


def test_publication_reads_verified_baselines_without_mutating_sources(publication_world) -> None:
    from tests.unit.test_build_scoreboard import _comparison_validator

    from squadopt.application.scoreboard import publish_scoreboard

    request, ledger = publication_world
    before = {p.name: p.read_bytes() for p in ledger.iterdir()}
    result = publish_scoreboard(request)
    week = result.document["payload"]["gameweeks"][1]
    row = week["comparisons"][3]
    assert row["net"] == 24
    assert row["outcome_snapshot_id"] == request.snapshot_id
    assert week["comparisons"][2]["net"] is None
    _comparison_validator().validate(week)
    assert before == {p.name: p.read_bytes() for p in ledger.iterdir()}


def test_corrupt_evidence_keeps_last_publication(publication_world, tmp_path, monkeypatch) -> None:
    from tests.unit.test_player_evidence_artifact import _artifact

    from squadopt.application.scoreboard import publish_scoreboard
    from squadopt.data.errors import DataError
    from squadopt.features.evidence_artifact import read_player_evidence_artifact

    request, _ = publication_world
    target = publish_scoreboard(request).target
    before = target.read_bytes()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    table, manifest = _artifact(evidence_root)
    named = evidence_root / "player_evidence_v1_2026-27_gw02_top100.csv"
    named.write_bytes(table.read_bytes() + b"\n")
    named.with_suffix(".manifest.json").write_bytes(manifest.read_bytes())
    monkeypatch.setattr(
        "squadopt.application.scoreboard_baselines.read_player_evidence_artifact",
        read_player_evidence_artifact,
    )
    with pytest.raises(DataError, match="checksum"):
        publish_scoreboard(replace(request, evidence_root=evidence_root))
    assert target.read_bytes() == before
