"""The companion boundary admits typed canonical data, never Python identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from squadopt.features.football_score_projection import ScoreDurationForecast, ScorePastDuration
from squadopt.features.football_unit_inputs import SourceRecord
from squadopt.live.football_composite_codec import composite_source_bytes, read_composite_source


def _duration() -> ScoreDurationForecast:
    return ScoreDurationForecast(
        "2026-27",
        7,
        61,
        "2026-10-15T12:00:00Z",
        "2026-10-15T12:00:00Z",
        "2026-10-15T12:01:00Z",
        (
            ScorePastDuration(
                "2025-26",
                1,
                1,
                "2025-08-16T14:00:00Z",
                "2025-08-16T17:00:00Z",
                (2800, 3000),
                "a" * 64,
                "b" * 64,
            ),
        ),
    )


def test_current_source_roundtrip_keeps_exact_canonical_bytes_and_frozen_nested_rows() -> None:
    original = _duration()
    payload = composite_source_bytes(original)
    restored = read_composite_source(
        payload,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        source_type=ScoreDurationForecast,
    )
    assert restored == original
    assert isinstance(restored.history, tuple)
    assert isinstance(restored.history[0].period_seconds, tuple)
    assert composite_source_bytes(restored) == payload


@pytest.mark.parametrize(
    "change", ["unknown", "boolean_id", "wrong_tuple", "type_name", "nonfinite"]
)
def test_redigested_malformed_source_cannot_enter_typed_runtime(change: str) -> None:
    document = json.loads(composite_source_bytes(_duration()))
    if change == "unknown":
        document["history"][0]["extra_source"] = "arbitrary"
    elif change == "boolean_id":
        document["history"][0]["fixture_id"] = True
    elif change == "wrong_tuple":
        document["history"][0]["period_seconds"] = [2800]
    elif change == "type_name":
        document["history"][0] = {"__module__": "os", "__class__": "system"}
    else:
        document["history"][0]["period_seconds"][0] = float("inf")
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError):
        read_composite_source(
            payload,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            source_type=ScoreDurationForecast,
        )


def test_duplicate_json_field_and_wrong_expected_digest_are_refused() -> None:
    payload = composite_source_bytes(_duration())
    with pytest.raises(ValueError, match="digest"):
        read_composite_source(payload, expected_sha256="f" * 64, source_type=ScoreDurationForecast)
    duplicate = payload.replace(b'"target_gameweek":7', b'"target_gameweek":7,"target_gameweek":7')
    with pytest.raises(ValueError, match="repeats"):
        read_composite_source(
            duplicate,
            expected_sha256=hashlib.sha256(duplicate).hexdigest(),
            source_type=ScoreDurationForecast,
        )


def test_aware_source_clocks_and_literal_source_scope_survive_restore() -> None:
    clock = datetime(2026, 10, 15, 12, tzinfo=UTC)
    source = SourceRecord(
        "fm", "provider", "v1", "fm", "a" * 64, clock, clock, clock, clock, "owner-use", True
    )
    payload = composite_source_bytes(source)
    assert (
        read_composite_source(
            payload, expected_sha256=hashlib.sha256(payload).hexdigest(), source_type=SourceRecord
        )
        == source
    )
    with pytest.raises(ValueError):
        composite_source_bytes(replace(source, kind="importlib"))  # type: ignore[arg-type]


def test_noncanonical_whitespace_and_unbounded_input_are_refused() -> None:
    payload = composite_source_bytes(_duration()) + b"\n"
    with pytest.raises(ValueError, match="canonical"):
        read_composite_source(
            payload,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            source_type=ScoreDurationForecast,
        )
    with pytest.raises(ValueError, match="bound"):
        composite_source_bytes(replace(_duration(), history=_duration().history * 20001))
