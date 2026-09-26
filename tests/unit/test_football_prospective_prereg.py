"""The football protocol scores a gameweek only from a capture whose own target it is.

``docs/football_prospective_prereg.md`` binds from the moment it merges, so a rule it
states wrongly cannot be corrected later. Its first draft scored a gameweek from "the last
live capture before the deadline". When no capture is taken between the previous
gameweek's deadline and this one, that capture targets the previous gameweek: its football
artifact reads as usable, its first week is the previous gameweek's forecast, and none of
the missing-week reasons applies. The tests below pin that premise in the code the protocol
cites, and pin that the protocol states the rule the code can honour.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.unit.test_live_recommendation import EVENTS, SEASON, _capture

from squadopt.application.advice import advise_entry
from squadopt.live.football_artifact import (
    ARTIFACT_CONTRACT,
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.recommendation import RecommendationInputs, read_inputs
from squadopt.platform.advice_submit import DeadlinePassedError
from squadopt.platform.capture_context import latest_snapshot_id, load_capture_identity
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "football_prospective_prereg.md"

# The two deadlines the shared fixture publishes.
FIRST_DEADLINE = EVENTS[0]["deadline_time"]
SECOND_DEADLINE = EVENTS[1]["deadline_time"]


def _artifact(inputs: RecommendationInputs) -> dict[str, Any]:
    """A v1 football artifact for ``inputs``' own target, as the producer writes one."""

    first = int(inputs.deadline.gameweek)
    frames = []
    for week in range(first, first + 5):
        table = inputs.players.copy()
        table["gameweek"] = week
        table["expected_points"] = 2.0 + week / 10
        table["appearance_probability"] = 0.8
        table["fixture_count"] = 1
        table["home_fixture_count"] = 0
        frames.append(table)
    document: dict[str, Any] = {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": FOOTBALL_MODEL_VERSION,
        "season": inputs.season,
        "gameweek": first,
        "source_snapshot_id": inputs.snapshot_id,
        "captured_at_utc": inputs.captured_at_utc,
        "rows": pd.concat(frames).to_dict("records"),
    }
    document["fingerprint"] = forecast_digest(document)
    return document


def _section(heading: str) -> str:
    """One ``## `` section of the protocol, with its line wrapping flattened."""

    text = PROTOCOL.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match is not None, f"The protocol has no section {heading!r}."
    return re.sub(r"\s+", " ", match.group(1))


def test_the_last_capture_before_a_deadline_can_target_the_previous_gameweek(
    tmp_path: Path,
) -> None:
    """The case the first draft's rule scored: every check passes, for the wrong week."""

    early = _capture(tmp_path / "early")
    assert early.metadata.captured_at_utc < FIRST_DEADLINE < SECOND_DEADLINE

    own = read_inputs(early, season=SEASON, gameweek=None)
    assert own.deadline.gameweek == 1

    path = football_artifact_path(tmp_path / "artifacts", early.metadata.snapshot_id)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_artifact(own)), encoding="utf-8")

    # Read for its own target, the artifact is usable and its first week is gameweek 1:
    # the decided forecast of a capture that also precedes gameweek 2's deadline.
    forecast = read_football_forecast(path, own)
    assert int(forecast.horizon.table.gameweek.min()) == 1

    # Read for gameweek 2 it is refused, so it can never be gameweek 2's football arm.
    named = read_inputs(early, season=SEASON, gameweek=2)
    with pytest.raises(ValueError, match="mismatches gameweek"):
        read_football_forecast(path, named)


def test_a_capture_taken_after_the_previous_deadline_is_the_one_that_targets_the_week(
    tmp_path: Path,
) -> None:
    late = _capture(tmp_path, captured_at="2026-08-22T09:00:00Z")
    assert FIRST_DEADLINE < late.metadata.captured_at_utc < SECOND_DEADLINE

    assert read_inputs(late, season=SEASON, gameweek=None).deadline.gameweek == 2


def test_the_names_the_rule_cites_are_the_code_it_means() -> None:
    assert issubclass(DeadlinePassedError, ValueError)
    for cited in (advise_entry, latest_snapshot_id, load_capture_identity, read_inputs):
        assert cited.__name__ in PROTOCOL.read_text(encoding="utf-8")


def test_the_protocol_scores_a_week_only_from_a_capture_that_targets_it() -> None:
    rule = _section("Which capture a gameweek is scored from")

    assert "whose own target is the gameweek" in rule
    assert "read_inputs(snapshot, season=..., gameweek=None).deadline.gameweek" in rule
    assert "whose capture instant precedes the gameweek's deadline" not in rule
    assert "`DeadlinePassedError`" in rule


def test_a_week_no_capture_targets_is_missing_and_never_borrows_the_previous_one() -> None:
    missing = _section("Missing weeks")

    assert "no `fpl-live` capture targets it" in missing
    assert "no `fpl-live` capture precedes its deadline" not in missing
    assert "is not scored from it" in missing
    assert "`DeadlinePassedError`" in missing


def test_the_input_check_and_the_record_name_each_weeks_capture_with_its_own_target() -> None:
    assert "the scored capture and its own target" in _section("When it is read")
    assert "the scored capture and its own target" in _section("Where the record lives")
