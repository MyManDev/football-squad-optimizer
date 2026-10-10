"""The published difficulty protocol states rules the code it cites can honour.

``docs/research/published_difficulty_live_prereg.md`` binds from the moment it merges, so a
rule it states wrongly cannot be corrected later. These tests pin the frozen candidate to the
study record it is copied from, check that every function the protocol names exists under that
name, and pin the sentences where a draft named a settlement flag the fixtures do not carry,
could take an audit capture the backend never served, paired a handoff whose write time nothing
checked, left the interval's function, quantile rule and week order open, did not say whether
the pooled or the per-version figures decide, and did not say which side of a fixture the
signal reads.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from squadopt.data.sources import fpl_live
from squadopt.experiments import opponent_projection
from squadopt.live import InSeasonProjection, read_projection_handoff, recommendation
from squadopt.live.tick import handoff_path_for
from squadopt.platform import capture_context, projection_retention
from squadopt.platform.backend_runtime import BackendConfig, BackendConfigError

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "research" / "published_difficulty_live_prereg.md"
STUDY = REPOSITORY / "docs" / "opponent_projection_study.json"
CANDIDATE = "P_published_rating"


def _protocol() -> str:
    """The protocol's text with every run of whitespace read as one space."""

    return " ".join(PROTOCOL.read_text(encoding="utf-8").split())


def _section(heading: str) -> str:
    """One ``## `` section of the protocol, with its line wrapping flattened."""

    text = PROTOCOL.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match is not None, f"The protocol has no section {heading!r}."
    return " ".join(match.group(1).split())


def test_the_frozen_coefficients_are_the_study_records_published_rating_fit() -> None:
    table = {
        position: (float(slope), float(centre))
        for position, slope, centre in re.findall(
            r"^\| (GK|DEF|MID|FWD) \| (-?[0-9.]+) \| (-?[0-9.]+) \|$",
            PROTOCOL.read_text(encoding="utf-8"),
            re.M,
        )
    }
    record = json.loads(STUDY.read_text(encoding="utf-8"))
    (fit,) = (entry for entry in record["candidates"] if entry["candidate"] == CANDIDATE)

    assert set(table) == set(opponent_projection.POSITIONS)
    for position, (slope, centre) in table.items():
        assert slope == fit["coefficients"][position]["slope"]
        assert centre == fit["coefficients"][position]["centre"]
    assert CANDIDATE in opponent_projection.CANDIDATES
    assert f"candidate `{CANDIDATE}`" in _protocol()


def test_the_frozen_hash_is_the_study_record_with_crlf_read_as_lf() -> None:
    digest = hashlib.sha256(STUDY.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    assert f"`{digest}`" in _protocol()


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (fpl_live, "scored_gameweeks"),
        (capture_context, "handoff_fingerprint_for"),
        (recommendation, "read_inputs"),
        (recommendation, "project"),
        (opponent_projection, "apply_adjustment"),
        (opponent_projection, "_squad"),
        (opponent_projection, "_realized"),
        (opponent_projection, "_bootstrap"),
    ],
)
def test_every_name_the_protocol_cites_exists(module: object, name: str) -> None:
    assert callable(getattr(module, name, None)), f"{module} has no {name}"
    assert f"`{name}`" in _protocol()


def test_settlement_is_read_from_the_event_flags_scored_gameweeks_reads() -> None:
    """Fixtures carry `finished` but no `data_checked`; the pair is an event's.

    A trigger asking every GW20 fixture for `data_checked` can never hold, which would leave
    the settlement rule to whoever writes the runner.
    """

    verdict = _section("Binding start and one verdict")
    missing = _section("Missing weeks and provenance")

    assert "every GW20 fixture" not in verdict
    assert "marks the GW20 event `finished` and `data_checked`" in verdict
    assert "`scored_gameweeks` in `src/squadopt/data/sources/fpl_live.py`" in verdict
    assert "The verdict names the earliest such capture and its fingerprint." in verdict
    assert "bootstrap counts the week in `scored_gameweeks`" in missing
    assert "marks the week scored" not in missing


def test_the_roots_the_protocol_reads_are_the_ones_the_backend_serves_from() -> None:
    with pytest.raises(BackendConfigError) as refused:
        BackendConfig.from_environment({})
    paired = _section("Paired inputs and comparator")

    for variable in ("SQUADOPT_BACKEND_SNAPSHOT_ROOT", "SQUADOPT_BACKEND_HANDOFF_ROOT"):
        assert variable in str(refused.value)
        assert f"`{variable}`" in paired
    assert "owner-selected" not in paired
    assert "the record names both" in paired


def test_a_capture_the_backend_never_served_does_not_displace_the_served_one() -> None:
    """A late audit capture targets the same week but gets no handoff.

    Taken as the decision capture, it would drop the week as unpaired while the backend kept
    serving the earlier capture, in a population whose floor is eight weeks.
    """

    paired = _section("Paired inputs and comparator")
    missing = _section("Missing weeks and provenance")

    assert "whose own target is that week (`read_inputs`" in paired
    assert "that has a served baseline handoff" in paired
    assert "A capture without one was never served. It is passed over and listed" in paired
    assert "Two captures at the same latest instant make the week missing." in paired
    assert "no served pre-deadline capture targeting the week" in missing
    assert "two such captures at the same latest instant" in missing


def test_a_handoff_republished_for_the_same_capture_is_what_the_pairing_then_reads(
    tmp_path: Path,
) -> None:
    """The premise of the file-time rule: the pairing alone cannot see a late republish."""

    capture = "fpl-live-20261016T090000Z-000000000000"
    served = InSeasonProjection(
        season="2026-27",
        gameweek=7,
        source_snapshot_id=capture,
        model_name="test",
        model_version="test-v1",
        feature_contract_version="test-v1",
        expected_points={1: 4.5},
    )
    corrected = dataclasses.replace(served, expected_points={1: 5.0})
    assert served.fingerprint != corrected.fingerprint
    alias = handoff_path_for(tmp_path, "2026-27", 7)
    projection_retention.publish_retained_handoff(alias, served)
    projection_retention.publish_retained_handoff(alias, corrected)

    retained = {
        read_projection_handoff(path).fingerprint
        for path in (tmp_path / "by-capture" / capture).glob("*.json")
    }
    assert retained == {served.fingerprint, corrected.fingerprint}
    assert (
        capture_context.handoff_fingerprint_for(tmp_path, "2026-27", 7, capture)
        == corrected.fingerprint
    )

    paired = _section("Paired inputs and comparator")
    missing = _section("Missing weeks and provenance")
    assert "So the runner reads the paired handoff file itself" in paired
    assert "Its modification time, as the file system reports it, must fall before" in paired
    assert "file sha256 and modification time" in paired
    assert "a paired handoff file written at or after the deadline" in missing


def test_the_primary_interval_is_the_studys_bootstrap_on_weeks_in_order() -> None:
    """With the seed fixed, the interval moves with the order of the weeks it is given.

    So "2000 draws, seed 0, 5 and 95 percent" alone does not fix the endpoint the strict
    gate reads: the function, its quantile rule and the order of the values have to be named.
    """

    weeks = np.arange(14, dtype="float64") - 6.0
    in_order = opponent_projection._bootstrap(weeks, resamples=2000, seed=0)
    reversed_order = opponent_projection._bootstrap(weeks[::-1], resamples=2000, seed=0)
    assert in_order != reversed_order

    primary = _section("Three readings and the gate")
    assert (
        "the interval is `_bootstrap` in `src/squadopt/experiments/opponent_projection.py`"
        " with `resamples=2000` and `seed=0`, on the per-week values in ascending gameweek"
        " order" in primary
    )
    assert "`np.quantile` at 0.05 and 0.95 with the default linear method" in primary


def test_the_gate_reads_the_pooled_figures_and_the_version_split_has_no_verdict() -> None:
    """With pooled and per-version readings both reported, the text must say which decides.

    Otherwise a disagreement between them, once a new handoff version ships mid-population,
    lets either one be picked after the outcomes are read.
    """

    paired = _section("Paired inputs and comparator")
    gate = _section("Three readings and the gate")

    assert "The gate reads the pooled readings over all jointly scored weeks" in paired
    assert "the readings for each handoff version carry no verdict" in paired
    assert "**Pass** requires all three conditions, read from the pooled figures" in gate


def test_the_signal_reads_each_fixtures_difficulty_on_the_clubs_own_side() -> None:
    """A fixture carries two published ratings; the frozen fit read the club's own one.

    Reading the opponent's side instead inverts the ranking of easy and hard weeks, and the
    frozen coefficients would then be applied to a different signal from the one they fit.
    """

    matches = pd.DataFrame(
        {
            "season": ["2024-25"],
            "gameweek": [7],
            "home_club": [3],
            "away_club": [14],
            "home_difficulty": [2.0],
            "away_difficulty": [5.0],
        }
    )
    lookup = opponent_projection._difficulty_lookup(matches, "2024-25", 7)
    assert lookup[(3, 14, True)] == 2.0
    assert lookup[(14, 3, False)] == 5.0

    candidate = _section("Fixed candidate")
    assert "each read on the club's own side" in candidate
    assert "`team_h_difficulty` when it is at home and `team_a_difficulty` when it is away" in (
        candidate
    )
    assert "`_difficulty_lookup`" in candidate
