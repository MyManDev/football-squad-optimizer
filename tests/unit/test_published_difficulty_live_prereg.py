"""The published difficulty protocol states rules the code it cites can honour.

``docs/research/published_difficulty_live_prereg.md`` binds from the moment it merges, so a
rule it states wrongly cannot be corrected later. These tests pin the frozen candidate to the
study record it is copied from, check that every function the protocol names exists under that
name, and pin the sentences where a draft named a settlement flag the fixtures do not carry.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from squadopt.data.sources import fpl_live
from squadopt.experiments import opponent_projection
from squadopt.live import recommendation
from squadopt.platform import capture_context

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
        (recommendation, "project"),
        (opponent_projection, "apply_adjustment"),
        (opponent_projection, "_squad"),
        (opponent_projection, "_realized"),
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
