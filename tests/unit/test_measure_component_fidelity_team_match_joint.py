"""The joint team-match candidate on the fidelity diagnostic: the flag, the pinned table and
the candidate document that names its sampler and its protocol."""

from pathlib import Path

import pytest
from scripts.measure_component_fidelity import (
    CANDIDATE_FIDELITY_CONTRACT_VERSION,
    DEFAULT_OUTPUT,
    TEAM_MATCH_JOINT_PREREG,
    FidelityBindingError,
    _candidate_from_arguments,
    _development_from_arguments,
    measure_fidelity,
)
from tests.unit.test_measure_component_fidelity import (
    CONFIG,
    MANIFEST,
    SAMPLER,
    _arguments,
    _development_arguments,
    _oof,
    _roster,
    _target_fold,
)

from squadopt.scenarios.components import (
    TEAM_MATCH_JOINT_CONTRACT_VERSION,
    TeamMatchBlockConfig,
    TeamMatchJointConfig,
)


def _joint_arguments(**overrides: object) -> object:
    fields: dict[str, object] = {
        "team_match_block": False,
        "team_match_joint": True,
        "expected_table_sha256": "a" * 64,
        "expected_roster_sha256": "b" * 64,
        "expected_manifest_sha256": "c" * 64,
        "json_output": Path("candidate.json"),
    }
    fields.update(overrides)
    return _arguments(**fields)


def test_a_v1_joint_run_is_pinned_and_names_one_sampler() -> None:
    pinned = _candidate_from_arguments(_joint_arguments())  # type: ignore[arg-type]
    assert pinned is not None and pinned.sampler == TeamMatchJointConfig()
    assert (pinned.table_sha256, pinned.roster_sha256, pinned.manifest_sha256) == (
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )
    assert _development_from_arguments(_joint_arguments()) is None  # type: ignore[arg-type]
    with pytest.raises(FidelityBindingError, match="one"):
        _candidate_from_arguments(_joint_arguments(team_match_block=True))  # type: ignore[arg-type]
    with pytest.raises(FidelityBindingError, match="one"):
        _candidate_from_arguments(_joint_arguments(conditional_residual_fraction=0.15))  # type: ignore[arg-type]
    # A missing digest is refused under the flag the run was given.
    with pytest.raises(FidelityBindingError, match="64-hex SHA-256 under --team-match-joint"):
        _candidate_from_arguments(_joint_arguments(expected_roster_sha256=None))  # type: ignore[arg-type]
    with pytest.raises(FidelityBindingError, match="64-hex SHA-256 under --team-match-block"):
        _candidate_from_arguments(
            _joint_arguments(
                team_match_block=True, team_match_joint=False, expected_roster_sha256=None
            )
        )  # type: ignore[arg-type]
    with pytest.raises(FidelityBindingError, match="frozen v1 artifact path"):
        _candidate_from_arguments(_joint_arguments(json_output=DEFAULT_OUTPUT))  # type: ignore[arg-type]
    # The block run is what it was, and a plain v1 run names no candidate.
    block = _candidate_from_arguments(
        _joint_arguments(team_match_block=True, team_match_joint=False)
    )  # type: ignore[arg-type]
    assert block is not None and block.sampler == TeamMatchBlockConfig()
    assert _candidate_from_arguments(_arguments()) is None  # type: ignore[arg-type]
    # On the development contract the flag selects the sampler the same way.
    development = _development_from_arguments(
        _development_arguments(
            team_match_joint=True,
            conditional_residual_fraction=None,
            conditional_residual_minimum_rows=None,
        )
    )  # type: ignore[arg-type]
    assert development is not None and development.sampler == TeamMatchJointConfig()
    with pytest.raises(FidelityBindingError, match="one"):
        _development_from_arguments(
            _development_arguments(
                team_match_joint=True,
                team_match_block=True,
                conditional_residual_fraction=None,
                conditional_residual_minimum_rows=None,
            )
        )  # type: ignore[arg-type]


def test_the_joint_document_names_its_contract_sampler_and_protocol() -> None:
    document = measure_fidelity(
        _oof(), _roster(), MANIFEST, config=CONFIG, team_match_joint=TeamMatchJointConfig()
    )

    assert document["contract_version"] == CANDIDATE_FIDELITY_CONTRACT_VERSION
    assert document["binding"] is False and document["development_only"] is False
    assert document["sampler"] == {
        "contract_version": TEAM_MATCH_JOINT_CONTRACT_VERSION,
        "residual_selection": "team_match_joint",
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
    }
    assert document["candidate_prereg_document"] == TEAM_MATCH_JOINT_PREREG
    # Every source row appeared at probability one, so every player appears and takes the
    # fixture's +1 points residual: the same five metrics, on the same fold.
    record = _target_fold(document)
    assert record["appearance_mean_difference"] == pytest.approx(0.0)
    assert record["points_conditional_mean_difference"] == pytest.approx(1.0)
    for other in (
        {"team_match_block": TeamMatchBlockConfig()},
        {"conditional_residuals": SAMPLER},
    ):
        with pytest.raises(FidelityBindingError, match="one candidate sampler"):
            measure_fidelity(
                _oof(),
                _roster(),
                MANIFEST,
                config=CONFIG,
                team_match_joint=TeamMatchJointConfig(),
                **other,  # type: ignore[arg-type]
            )
