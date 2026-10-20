"""The team-match block candidate on the calibration runner: the flag, the pinned v1 table,
its own fidelity verification and the control arm drawn beside it."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts.run_component_squad_calibration import (
    CANDIDATE_REPORT_VERSION,
    DEFAULT_OUTPUT,
    PHASE_C_MANIFEST_SHA256,
    PHASE_C_ROSTER_SHA256,
    PHASE_C_TABLE_SHA256,
    TEAM_MATCH_BLOCK_PREREG,
    BindingCalibrationError,
    ReferenceInputs,
    _arm_summary,
    _candidate_from_arguments,
    _candidate_record,
    _development_from_arguments,
    _history_rows,
    _load_verified_candidate_fidelity,
    _measure_fold,
    _paired_differences,
    _pooled_diagnostics,
    _reference_from_arguments,
    _report_contract_version,
    _sampler_record,
)
from tests.unit.test_run_component_squad_calibration import (
    _fidelity_document,
    _frozen_decision,
    _handoff,
    _squad_positions,
)

from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    TEAM_MATCH_BLOCK_CONTRACT_VERSION,
    TeamMatchBlockConfig,
)

DIGESTS = {
    "expected_table_sha256": PHASE_C_TABLE_SHA256,
    "expected_roster_sha256": PHASE_C_ROSTER_SHA256,
    "expected_manifest_sha256": PHASE_C_MANIFEST_SHA256,
}
REFERENCE = ReferenceInputs(
    table_sha256=PHASE_C_TABLE_SHA256,
    roster_sha256=PHASE_C_ROSTER_SHA256,
    manifest_sha256=PHASE_C_MANIFEST_SHA256,
)


def _arguments(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "phase_c_contract": "v1",
        "fidelity": Path("fidelity.json"),
        "folds": None,
        "team_match_block": True,
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
        "json_output": Path("candidate.json"),
        **DIGESTS,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_the_flag_selects_the_candidate_and_names_one_sampler() -> None:
    assert _candidate_from_arguments(_arguments()) == TeamMatchBlockConfig()
    assert _candidate_from_arguments(_arguments(team_match_block=False)) is None
    with pytest.raises(BindingCalibrationError, match="one"):
        _candidate_from_arguments(_arguments(conditional_residual_fraction=0.15))
    with pytest.raises(BindingCalibrationError, match="binding artifact path"):
        _candidate_from_arguments(_arguments(json_output=DEFAULT_OUTPUT))
    assert _report_contract_version(TeamMatchBlockConfig()) == CANDIDATE_REPORT_VERSION


def test_a_pinned_v1_run_needs_the_three_digests_and_stands_the_v1_refusal_aside() -> None:
    assert _reference_from_arguments(_arguments()) == REFERENCE
    unpinned = _arguments(team_match_block=False, **dict.fromkeys(DIGESTS))
    assert _reference_from_arguments(unpinned) is None
    assert _reference_from_arguments(_arguments(phase_c_contract="development_v2")) is None
    with pytest.raises(BindingCalibrationError, match="64-hex"):
        _reference_from_arguments(_arguments(expected_manifest_sha256=None))
    with pytest.raises(BindingCalibrationError, match="64-hex"):
        _reference_from_arguments(_arguments(expected_table_sha256="abc"))
    # The digests belong to the pinned run, so the v1 contract no longer refuses them there.
    assert _development_from_arguments(_arguments()) is None
    with pytest.raises(BindingCalibrationError, match="development_v2 only"):
        _development_from_arguments(_arguments(team_match_block=False))


def test_the_sampler_and_candidate_records_name_the_contract() -> None:
    assert _sampler_record(TeamMatchBlockConfig()) == {
        "contract_version": TEAM_MATCH_BLOCK_CONTRACT_VERSION,
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
    }
    assert _sampler_record(None)["contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION
    record = _candidate_record(TeamMatchBlockConfig())
    assert record is not None
    assert record["sampler_contract_version"] == TEAM_MATCH_BLOCK_CONTRACT_VERSION
    assert record["residual_selection"] == "team_match_block"
    assert record["prereg_document"] == TEAM_MATCH_BLOCK_PREREG
    assert record["binding"] is False


def _candidate_fidelity_document() -> dict[str, object]:
    document = _fidelity_document()
    document.update(
        {
            "contract_version": "phase_d_component_fidelity_candidate_v1",
            "binding": False,
            "development_only": False,
            "phase_c_contract": "phase_c_component_oof_v1",
            "sampler": {
                "contract_version": TEAM_MATCH_BLOCK_CONTRACT_VERSION,
                "residual_selection": "team_match_block",
                "conditional_residual_fraction": None,
                "conditional_residual_minimum_rows": None,
            },
        }
    )
    provenance = dict(document["provenance"])  # type: ignore[call-overload]
    provenance.update(
        {
            "phase_c_contract": "phase_c_component_oof_v1",
            "phase_c_producer_repository_commit": "d" * 40,
        }
    )
    document["provenance"] = provenance
    return document


def _verify(tmp_path: Path, document: dict[str, object], **overrides: object) -> str:
    path = tmp_path / "candidate_fidelity.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return _load_verified_candidate_fidelity(
        path,
        overrides.get("handoff", _handoff()),  # type: ignore[arg-type]
        overrides.get("sampler", TeamMatchBlockConfig()),  # type: ignore[arg-type]
        overrides.get("reference", REFERENCE),  # type: ignore[arg-type]
    )


def test_a_candidate_fidelity_record_is_verified_on_the_pinned_table_and_sampler(
    tmp_path: Path,
) -> None:
    assert len(_verify(tmp_path, _candidate_fidelity_document())) == 64

    with pytest.raises(BindingCalibrationError, match="candidate_v1"):
        _verify(tmp_path, _fidelity_document())  # the frozen v1 record is refused
    other_sampler = _candidate_fidelity_document()
    other_sampler["sampler"] = {**other_sampler["sampler"], "contract_version": "other"}  # type: ignore[dict-item]
    with pytest.raises(BindingCalibrationError, match="different sampler"):
        _verify(tmp_path, other_sampler)
    with pytest.raises(BindingCalibrationError, match="different sampler"):
        _verify(tmp_path, _candidate_fidelity_document(), sampler=None)
    with pytest.raises(BindingCalibrationError, match="digests differ"):
        _verify(
            tmp_path,
            _candidate_fidelity_document(),
            reference=ReferenceInputs(
                table_sha256="e" * 64,
                roster_sha256=PHASE_C_ROSTER_SHA256,
                manifest_sha256=PHASE_C_MANIFEST_SHA256,
            ),
        )
    other_commit = _candidate_fidelity_document()
    other_commit["provenance"] = {
        **other_commit["provenance"],  # type: ignore[dict-item]
        "phase_c_producer_repository_commit": "f" * 40,
    }
    with pytest.raises(BindingCalibrationError, match="describe this Phase C handoff"):
        _verify(tmp_path, other_commit)
    binding = _candidate_fidelity_document()
    binding["binding"] = True
    with pytest.raises(BindingCalibrationError, match="diagnostic-only"):
        _verify(tmp_path, binding)


def _handoff_with_clubs() -> tuple[PhaseCComponentHandoff, object, object]:
    """The frozen decision's handoff with the club held by the roster, as the v1 export does."""

    handoff, prepared, result = _frozen_decision()
    rows = handoff.rows.assign(
        season="2021-22",
        target_gameweek=[int(str(fold)[-2:]) for fold in handoff.rows["fold_id"]],
    )
    roster = rows.loc[:, ["season", "target_gameweek", "fold_id", "player_id"]].assign(
        team_id=[f"T{(int(player) - 1) // 3}" for player in rows["player_id"]]
    )
    return (
        PhaseCComponentHandoff(
            rows=rows,
            roster=roster,
            table_sha256=handoff.table_sha256,
            roster_sha256=handoff.roster_sha256,
            manifest_sha256=handoff.manifest_sha256,
            repository_commit=handoff.repository_commit,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            target_contract_version=handoff.target_contract_version,
            dataset_contract_version=handoff.dataset_contract_version,
        ),
        prepared,
        result,
    )


def test_measure_fold_draws_the_block_candidate_beside_the_foundation_control_arm() -> None:
    handoff, prepared, result = _handoff_with_clubs()
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())

    reading, record = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        selected,
        settings,
        TeamMatchBlockConfig(),
        control_arm=True,  # type: ignore[arg-type]
    )
    _, foundation = _measure_fold(handoff, prepared, result, 40.0, selected, settings, None)  # type: ignore[arg-type]

    assert reading.fold_id == prepared.fold_id  # type: ignore[attr-defined]
    assert record["sampler_contract_version"] == TEAM_MATCH_BLOCK_CONTRACT_VERSION
    control = record["control_arm"]
    assert control["sampler_contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION  # type: ignore[index]
    # The control arm is the foundation draw itself: same pool, seed and decision.
    assert control["scenario_fingerprint"] == foundation["scenario_fingerprint"]  # type: ignore[index]
    assert control["component_fingerprint"] == foundation["component_fingerprint"]  # type: ignore[index]
    assert record["scenario_fingerprint"] != foundation["scenario_fingerprint"]
    assert record["realized_score"] == control["realized_score"] == 40.0  # type: ignore[index]
    # Five clubs of three players: three same-club pairs each.
    correlation = record["within_club_points_correlation"]
    assert correlation["pairs"] == 15  # type: ignore[index]
    assert correlation["candidate"] is not None and correlation["control"] is not None  # type: ignore[index]
    diagnostics = record["block_diagnostics"]
    assert diagnostics["team_match_block_target_clubs"] == 5  # type: ignore[index]
    assert diagnostics["team_match_block_blocks_per_fold_mean"] == 5.0  # type: ignore[index]
    assert diagnostics["team_match_block_fixture_fallback_cells"] == 0  # type: ignore[index]
    assert "control_arm" not in foundation


def test_the_history_rows_take_each_clubs_identity_from_the_roster() -> None:
    handoff, _, _ = _frozen_decision()
    rows = handoff.rows.assign(season="2021-22", target_gameweek=11)
    roster = rows.loc[:, ["season", "target_gameweek", "fold_id", "player_id"]].assign(
        team_id="Club"
    )
    joined = PhaseCComponentHandoff(
        rows=rows,
        roster=roster,
        table_sha256=handoff.table_sha256,
        roster_sha256=handoff.roster_sha256,
        manifest_sha256=handoff.manifest_sha256,
        repository_commit=handoff.repository_commit,
        model_version=handoff.model_version,
        feature_contract_version=handoff.feature_contract_version,
        target_contract_version=handoff.target_contract_version,
        dataset_contract_version=handoff.dataset_contract_version,
    )

    assert "team_id" not in _history_rows(joined, None).columns
    with_clubs = _history_rows(joined, TeamMatchBlockConfig())
    assert len(with_clubs) == len(rows)
    assert set(with_clubs["team_id"]) == {"Club"}


def _fold_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for season, start in (("2022-23", 2), ("2023-24", 2)):
        for gameweek in range(start, start + 8):
            below = gameweek % 4 == 0
            records.append(
                {
                    "fold_id": f"{season}-gw{gameweek:02d}",
                    "probability_integral_transform": 0.5 + 0.01 * gameweek,
                    "realized_below_q10": below,
                    "q10_score": 40.0 + gameweek,
                    "scenario_standard_deviation": 10.0,
                    "control_arm": {
                        "probability_integral_transform": 0.5,
                        "realized_below_q10": gameweek % 2 == 0,
                        "q10_score": 42.0 + gameweek,
                        "scenario_standard_deviation": 9.0,
                    },
                    "within_club_points_correlation": {
                        "pairs": 3,
                        "candidate": 0.2,
                        "control": 0.0,
                    },
                    "block_diagnostics": {
                        "team_match_block_blocks_per_fold_mean": 19.0,
                        "team_match_block_position_fallback_rate": 0.1,
                    },
                }
            )
    return records


def test_the_arm_summaries_and_paired_differences_read_the_fold_records() -> None:
    records = _fold_records()

    candidate = _arm_summary(records)
    assert candidate["fold_count"] == 16
    assert candidate["realized_below_lower_quantile_count"] == 4
    assert candidate["realized_below_lower_quantile_rate"] == pytest.approx(0.25)
    assert candidate["tail_rate_within_s2_bounds"] is False
    assert candidate["mean_pit_within_s1_bounds"] is True
    assert set(candidate["seasons"]) == {"2022-23", "2023-24"}  # type: ignore[arg-type]
    assert candidate["seasons"]["2022-23"]["fold_count"] == 8  # type: ignore[index]

    paired = _paired_differences(records)
    tail = paired["realized_below_q10"]
    assert tail["fold_count"] == 16  # type: ignore[index]
    assert tail["mean"] == pytest.approx((4 - 8) / 16)  # type: ignore[index]
    lower, upper = tail["interval_90"]  # type: ignore[index, misc]
    assert lower <= tail["mean"] <= upper  # type: ignore[index]
    assert paired["bootstrap"]["resamples"] == 2000  # type: ignore[index]

    pooled = _pooled_diagnostics(records)
    assert pooled["within_club_points_correlation"]["candidate_mean"] == pytest.approx(0.2)  # type: ignore[index]
    assert pooled["within_club_points_correlation"]["control_mean"] == pytest.approx(0.0)  # type: ignore[index]
    assert pooled["block_diagnostics"]["team_match_block_blocks_per_fold_mean_mean"] == 19.0  # type: ignore[index]
    assert pd.notna(pooled["block_diagnostics"]["team_match_block_position_fallback_rate_mean"])  # type: ignore[index]
