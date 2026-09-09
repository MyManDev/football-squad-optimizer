"""Live E2 inputs preserve capture identity, raw downside and the full optimizer pool."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts import _phase_e_live as live
from tests.unit.test_phase_e_evaluation import _inputs


def _build(capture, projection, handoff, path, *, status="calibrated_internal"):
    evidence = live.PhaseDBindingEvidence(status, (), "e" * 64, projection.model_version)
    return live.live_component_decision(
        capture, projection, handoff, path, binding_evidence=evidence
    )


def _world(monkeypatch: pytest.MonkeyPatch):
    handoff, fold, _ = _inputs()
    handoff = replace(
        handoff,
        table_sha256=live.binding.PHASE_C_TABLE_SHA256,
        roster_sha256=live.binding.PHASE_C_ROSTER_SHA256,
        manifest_sha256=live.binding.PHASE_C_MANIFEST_SHA256,
        model_version=live.producer.COMPONENT_MODEL_VERSION,
    )
    pool = fold.projections.copy()
    projection = live.InSeasonProjection(
        season="2026-27",
        gameweek=2,
        source_snapshot_id="original",
        model_name=live.producer.CONTROL_MODEL_NAME,
        model_version=handoff.model_version,
        feature_contract_version=handoff.feature_contract_version,
        expected_points={
            int(row.player_id): float(row.expected_points) for row in pool.itertuples()
        },
        diagnostics={"component_fingerprint": "a" * 64},
    )
    capture = SimpleNamespace(
        payloads={
            live.BOOTSTRAP_PAYLOAD: b"original-bootstrap",
            live.FIXTURES_PAYLOAD: b"original-fixtures",
            live.live_payload(1): b"original-settled-history",
        },
        metadata=SimpleNamespace(captured_at_utc="2026-08-28T15:31:00Z"),
    )
    inputs = SimpleNamespace(deadline=SimpleNamespace(deadline_utc="2026-08-29T10:00:00Z"))
    monkeypatch.setattr(live, "infer_season", lambda capture: "2026-27")
    monkeypatch.setattr(live, "read_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(live, "project", lambda *args, **kwargs: SimpleNamespace(table=pool))
    components = handoff.rows.loc[handoff.rows["fold_id"].eq(fold.fold_id)].copy()
    components["expected_points"] = pool["expected_points"].to_numpy()
    components.loc[components["player_id"].eq(15), "composition_route"] = "direct_control"
    components.loc[components["player_id"].eq(1), "raw_expected_points_if_appearance"] = -5.0
    calls = []

    def rebuild(archive_root, **kwargs):
        calls.append(kwargs)
        assert kwargs["include_components"] is True
        assert kwargs["event_payloads"] == {1: b"original-settled-history"}
        return components, {
            "component_fingerprint": "a" * 64,
            "component_training_cutoff": "2024-25:GW38",
            "component_training_data_fingerprint": "d" * 64,
        }

    monkeypatch.setattr(live.producer, "_component_table", rebuild)
    return capture, projection, handoff, pool, components, calls


def test_real_sampler_uses_raw_components_full_pool_and_repeatable_capture_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture, projection, handoff, pool, _, calls = _world(monkeypatch)
    point = _build(capture, projection, handoff, tmp_path)
    pd.testing.assert_frame_equal(point.pool, pool)
    assert len(point.pool) == 15 and point.covered_player_ids == frozenset(range(1, 15))
    assert point.draw_factory is not None
    first, second = point.draw_factory(0), point.draw_factory(0)
    assert first.component_fingerprint == second.component_fingerprint
    assert first.scenarios.scenario_fingerprint == second.scenarios.scenario_fingerprint
    assert (
        first.inputs.table.set_index("player_id").loc[1, "raw_expected_points_if_appearance"]
        == -5.0
    )
    assert (first.scenarios.scenario_points[1] < 0).all()
    assert first.scenarios.target.season == "2026-27"
    assert len(calls) == 1
    assert calls[0]["source_snapshot_id"] == "original"
    assert point.source["projection_fingerprint"] == projection.fingerprint
    assert point.source["binding_artifact_sha256"] == "e" * 64


@pytest.mark.parametrize("status", ["failed", "abstained"])
def test_uncalibrated_binding_cannot_run_the_live_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    capture, projection, handoff, _, _, calls = _world(monkeypatch)
    with pytest.raises(live.probe.ProbeError, match="calibrated"):
        _build(capture, projection, handoff, tmp_path, status=status)
    assert calls == []


@pytest.mark.parametrize(
    "problem", ["opening", "model", "hash", "missing_history", "missing_fixtures", "capture_season"]
)
def test_invalid_live_inputs_refuse_before_model_or_archive_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, problem: str
) -> None:
    capture, projection, handoff, _, _, calls = _world(monkeypatch)
    if problem == "opening":
        projection = replace(projection, gameweek=1)
    elif problem == "model":
        handoff = replace(handoff, model_version="other")
    elif problem == "hash":
        handoff = replace(handoff, table_sha256="f" * 64)
    elif problem == "missing_history":
        capture.payloads.pop(live.live_payload(1))
    elif problem == "missing_fixtures":
        capture.payloads.pop(live.FIXTURES_PAYLOAD)
    else:
        monkeypatch.setattr(live, "infer_season", lambda capture: "other")
    with pytest.raises(live.probe.ProbeError):
        _build(capture, projection, handoff, tmp_path)
    assert calls == []


@pytest.mark.parametrize("problem", ["fingerprint", "means"])
def test_rebuilt_model_must_match_original_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, problem: str
) -> None:
    capture, projection, handoff, _, components, _ = _world(monkeypatch)
    if problem == "fingerprint":
        projection = replace(projection, diagnostics={"component_fingerprint": "e" * 64})
    else:
        components.loc[components.index[0], "expected_points"] += 0.01
    with pytest.raises(live.probe.ProbeError, match="Rebuilt"):
        _build(capture, projection, handoff, tmp_path)


def test_live_components_cli_requires_original_capture_and_frozen_handoff(tmp_path: Path) -> None:
    assert (
        live.probe.main(
            [
                "--live-components",
                "--live-decision",
                "2026-27:2:original:unused.json",
                "--json-output",
                str(tmp_path / "probe.json"),
            ]
        )
        == 1
    )
    assert not (tmp_path / "probe.json").exists()
