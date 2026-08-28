"""advise_entry: a wire-shaped request, injected collaborators, the same bytes."""

import dataclasses
import json
from pathlib import Path
from typing import Any, get_type_hints

import pytest
import tests.unit.test_league_views as league_views_tests
from tests.unit.test_league_views import (
    _legal_squad,
    _member_picks,
    _Provider,
    _world_context,
)

from squadopt.application.advice import AdviseEntryRequest, advise_entry
from squadopt.application.entries import EntryError, EntryRegistration
from squadopt.application.league_views import build_league_views

world = league_views_tests.world  # re-register the fixture in this module


def _request(**overrides: object) -> AdviseEntryRequest:
    fields: dict[str, object] = {
        "season": "2026-27",
        "gameweek": 2,
        "league_id": 352490,
        "entry_id": 101,
    }
    fields.update(overrides)
    return AdviseEntryRequest(**fields)  # type: ignore[arg-type]


def test_the_request_carries_no_path_anywhere() -> None:
    """DecideRequest carries filesystem paths because it is an operator command; a
    request that will travel over a network boundary must not."""

    hints = get_type_hints(AdviseEntryRequest)
    for name, annotation in hints.items():
        assert "Path" not in str(annotation), (name, annotation)
    assert not any(
        isinstance(field.default, Path) for field in dataclasses.fields(AdviseEntryRequest)
    )


def test_the_request_is_validated() -> None:
    with pytest.raises(EntryError, match="season"):
        _request(season=" ")
    with pytest.raises(EntryError, match="gameweek"):
        _request(gameweek=0)
    with pytest.raises(EntryError, match="entry_id"):
        _request(entry_id=-1)
    with pytest.raises(EntryError, match="rival_entry_id"):
        _request(rival_entry_id=0)


def test_advise_entry_produces_the_builders_bytes(world: dict[str, Any], tmp_path: Path) -> None:
    """The pure call and the batch builder agree byte for byte on the same member.

    The builder is the caller of ``advise_entry`` now, so this is close to a tautology —
    which is the point: the service path and the static path cannot drift, because they
    are one function.
    """

    import datetime

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    provider = _Provider({101: _member_picks(world, 101, squad)})
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    build_league_views(
        provider,
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "site",
        now=when,
    )
    published = json.loads(
        (tmp_path / "site" / "advice" / "101" / "saf-puan" / "1.json").read_text(encoding="utf-8")
    )["payload"]

    direct = advise_entry(
        _request(),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )

    assert direct == published


def test_uncomputed_combinations_are_refused_not_faked(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    provider = _Provider({101: _member_picks(world, 101, _legal_squad(world))})

    def call(request: AdviseEntryRequest) -> dict[str, object]:
        return advise_entry(
            request, provider=provider, inputs=inputs, projection=projection, rules=rules
        )

    with pytest.raises(EntryError, match="not computed"):
        call(_request(strategy="fark-yarat"))
    with pytest.raises(EntryError, match="not computed"):
        call(_request(window=3))
    with pytest.raises(EntryError, match="rival request parameter"):
        call(_request(rival_entry_id=202))
    with pytest.raises(EntryError, match="not the capture's"):
        call(_request(gameweek=7))
    with pytest.raises(EntryError, match="not the capture's"):
        call(_request(season="2025-26"))
