"""Public-output guards: the published member tree stays probability-free, provably.

Two guards the existing suites do not carry: (1) a sweep of every file the league
builder publishes, applying the web test's own bilingual regex backend-side (today
only the English substring 'probability' is checked there), with '%' scoped to
advice files because ownership percentages are the game's own facts elsewhere; and
(2) a pin that the ledger site path renders every probability field of the risk
block as null with no rivals — so switching the site build to a populated risk view
breaks a named test instead of silently shipping probabilities to pages that
already render them.
"""

import json
import re
from pathlib import Path
from typing import Any

import tests.unit.test_live_transfers as world_module

from squadopt.application.build import _risk_from_status
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN
from squadopt.data.snapshots import read_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff

SEASON = world_module.SEASON

world = world_module._world  # re-register the fixture in this module

#: The web guard's regex (adviceNoProbability.test.tsx), minus '%', which is scoped
#: to advice files below — league pages legitimately show ownership percentages.
_FORBIDDEN_TEXT = re.compile(r"probabilit|olas.l.k|\bP\(", re.IGNORECASE)


class _Provider:
    def __init__(self, picks_by_entry: dict[int, EntryPicks]) -> None:
        self._picks = picks_by_entry

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        if entry_id not in self._picks:
            raise EntryError(f"No picks captured for entry {entry_id}.")
        return self._picks[entry_id]


def _member_picks(world: dict[str, Any], entry_id: int, squad_codes: list[int]) -> EntryPicks:
    return EntryPicks(
        entry_id=entry_id,
        season=SEASON,
        gameweek=1,
        squad=tuple(squad_codes),
        starting_xi=tuple(squad_codes[:11]),
        captain=squad_codes[0],
        bank_tenths=5,
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=world["gw2_id"],
    )


def _legal_squad() -> list[int]:
    gk, defs = [1001, 1002], [1004, 1005, 1006, 1007, 1008]
    return gk + defs + [1012, 1013, 1014, 1015, 1016, 1020, 1021, 1022]


def _walk(node: object, path: str, offenders: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_FIELD_PATTERN.search(str(key)):
                offenders.append(f"{path}.{key} (key)")
            _walk(value, f"{path}.{key}", offenders)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", offenders)
    elif isinstance(node, str) and _FORBIDDEN_TEXT.search(node):
        offenders.append(f"{path} (text: {node[:60]!r})")


def test_every_published_league_file_is_probability_free(
    world: dict[str, Any], tmp_path: Path
) -> None:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    provider = _Provider({101: _member_picks(world, 101, _legal_squad())})
    out_dir = tmp_path / "league"
    build_league_views(
        provider,
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out_dir,
    )
    published = sorted(out_dir.rglob("*.json"))
    assert published, "the builder wrote nothing — the sweep has no subject"
    offenders: list[str] = []
    for file in published:
        raw = file.read_text(encoding="utf-8")
        relative = file.relative_to(out_dir).as_posix()
        _walk(json.loads(raw), relative, offenders)
        if relative.startswith("advice/") and "%" in raw:
            offenders.append(f"{relative} (advice text contains '%')")
    assert offenders == [], f"probability-shaped content in the published tree: {offenders}"


def test_the_ledger_site_path_nulls_every_probability_field() -> None:
    for status in ("not_requested", "unavailable", "available", "unexpected"):
        risk = _risk_from_status(status)
        assert risk.lower_quantile_probability is None
        assert risk.lower_quantile_score is None
        assert risk.mean_score is None
        assert risk.mean_worst_fraction_score is None
        assert risk.worst_fraction is None
        assert risk.points_threshold is None
        assert risk.probability_below_threshold is None
        assert risk.probability_below_threshold_interval is None
        assert risk.location_shift_points is None
        assert risk.rivals == ()
        assert risk.status == status
