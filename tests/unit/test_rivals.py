"""The ownership template rival: legality, determinism, and the provider seam.

Synthetic pools and captures only — the point is the machinery, not the football.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from squadopt.application.rivals import (
    TEMPLATE_RIVAL_SOURCE,
    TemplateRivalProvider,
    iter_rivals,
)
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.optimization import OptimizationConfig
from squadopt.scenarios.models import ScenarioValidationError
from squadopt.scenarios.rivals import (
    TEMPLATE_RIVAL_LABEL,
    template_rival_diagnostics,
    template_rival_from_ownership,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")


def _pool(*, gk: int = 3, defenders: int = 6, mid: int = 6, fwd: int = 4) -> pd.DataFrame:
    """A pool whose ownership strictly decreases with player_id, so picks are predictable."""

    rows: list[dict[str, object]] = []
    identifier = 0
    for position, count in (("GK", gk), ("DEF", defenders), ("MID", mid), ("FWD", fwd)):
        for _ in range(count):
            identifier += 1
            rows.append(
                {
                    "player_id": identifier,
                    "position": position,
                    "ownership": 100.0 - identifier,
                }
            )
    return pd.DataFrame(rows)


def test_the_template_is_a_legal_eleven_of_the_most_owned() -> None:
    pool = _pool()
    rival = template_rival_from_ownership(pool)
    assert rival.label == TEMPLATE_RIVAL_LABEL
    assert len(rival.starter_ids) == 11
    positions = pool.set_index("player_id")["position"]
    formation = {position: 0 for position in POSITIONS}
    for player in rival.starter_ids:
        formation[str(positions.at[player])] += 1
    config = OptimizationConfig()
    for position in POSITIONS:
        assert formation[position] >= config.starting_position_min[position]
        assert formation[position] <= config.starting_position_max[position]
    assert formation["GK"] == 1


def test_the_captain_is_the_most_owned_starter() -> None:
    pool = _pool()
    rival = template_rival_from_ownership(pool)
    ownership = pool.set_index("player_id")["ownership"]
    best = max(rival.starter_ids, key=lambda player: float(ownership.at[player]))
    assert rival.captain_id == best


def test_selection_prefers_ownership_over_position_order() -> None:
    """A wildly owned forward must beat a barely owned midfielder for the free slots."""

    pool = _pool()
    pool.loc[pool["player_id"] == pool["player_id"].max(), "ownership"] = 999.0
    rival = template_rival_from_ownership(pool)
    assert pool["player_id"].max() in rival.starter_ids
    assert rival.captain_id == pool["player_id"].max()


def test_the_same_pool_always_yields_the_same_rival() -> None:
    pool = _pool()
    shuffled = pool.sample(frac=1.0, random_state=3).reset_index(drop=True)
    first = template_rival_from_ownership(pool)
    second = template_rival_from_ownership(shuffled)
    assert first.starter_ids == second.starter_ids
    assert first.captain_id == second.captain_id


def test_ties_break_on_player_id() -> None:
    pool = _pool()
    pool["ownership"] = 50.0
    first = template_rival_from_ownership(pool)
    second = template_rival_from_ownership(pool.iloc[::-1].reset_index(drop=True))
    assert first.starter_ids == second.starter_ids
    assert first.captain_id == second.captain_id


def test_a_pool_short_of_a_position_is_refused() -> None:
    with pytest.raises(ScenarioValidationError, match="at least"):
        template_rival_from_ownership(_pool(defenders=2))


def test_a_pool_with_negative_or_missing_ownership_is_refused() -> None:
    pool = _pool()
    pool.loc[0, "ownership"] = -1.0
    with pytest.raises(ScenarioValidationError, match="non-negative"):
        template_rival_from_ownership(pool)
    pool = _pool()
    pool.loc[0, "ownership"] = float("nan")
    with pytest.raises(ScenarioValidationError, match="non-negative"):
        template_rival_from_ownership(pool)


def test_a_duplicated_player_is_refused() -> None:
    pool = pd.concat([_pool(), _pool().iloc[[0]]], ignore_index=True)
    with pytest.raises(ScenarioValidationError, match="more than once"):
        template_rival_from_ownership(pool)


def test_diagnostics_describe_the_eleven() -> None:
    pool = _pool()
    rival = template_rival_from_ownership(pool)
    diagnostics = template_rival_diagnostics(pool, rival)
    assert diagnostics["starters"] == 11
    assert sum(dict(diagnostics["formation"]).values()) == 11
    assert diagnostics["captain_rule"] == "most_owned_starter"
    assert diagnostics["captaincy_share_available"] is False
    assert float(diagnostics["mean_ownership"]) > float(diagnostics["minimum_ownership"])


# --- the provider seam ---------------------------------------------------------


def _bootstrap_payload() -> bytes:
    teams = [{"id": 1, "code": 10, "name": "Club A"}, {"id": 2, "code": 20, "name": "Club B"}]
    elements = []
    identifier = 0
    for element_type, count in ((1, 3), (2, 6), (3, 6), (4, 4)):
        for _ in range(count):
            identifier += 1
            elements.append(
                {
                    "id": identifier,
                    "code": 1000 + identifier,
                    "first_name": "P",
                    "second_name": f"Player{identifier}",
                    "team": 1 + identifier % 2,
                    "element_type": element_type,
                    "now_cost": 50,
                    "selected_by_percent": str(100 - identifier),
                }
            )
    document = {"teams": teams, "elements": elements, "events": []}
    return json.dumps(document).encode("utf-8")


def _capture(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc="2026-08-16T08:00:00Z",
        payloads={"bootstrap-static.json": _bootstrap_payload()},
    )
    return metadata.snapshot_id


def test_the_template_provider_builds_one_rival_from_a_capture(tmp_path: Path) -> None:
    snapshot = read_snapshot(tmp_path, _capture(tmp_path))
    provider = TemplateRivalProvider(snapshot)
    assert provider.source == TEMPLATE_RIVAL_SOURCE
    rivals = provider.rivals()
    assert len(rivals) == 1
    assert len(rivals[0].starter_ids) == 11
    # The pool keys players by their persistent code, and so must the rival.
    assert all(int(str(player)) >= 1000 for player in rivals[0].starter_ids)


def test_the_provider_is_deterministic_and_diagnosable(tmp_path: Path) -> None:
    snapshot = read_snapshot(tmp_path, _capture(tmp_path))
    provider = TemplateRivalProvider(snapshot)
    assert provider.rivals() == provider.rivals()
    diagnostics = provider.diagnostics()
    assert diagnostics["snapshot_id"] == snapshot.metadata.snapshot_id
    assert diagnostics["starters"] == 11


def test_iter_rivals_flattens_providers(tmp_path: Path) -> None:
    snapshot = read_snapshot(tmp_path, _capture(tmp_path))
    provider = TemplateRivalProvider(snapshot)
    rivals = list(iter_rivals(iter([provider, provider])))
    assert len(rivals) == 2
    assert rivals[0].starter_ids == rivals[1].starter_ids
