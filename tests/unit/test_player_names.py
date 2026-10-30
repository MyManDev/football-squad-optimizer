"""A published page names a player as the game does, from the capture's own bootstrap."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import tests.unit.test_live_transfers as world_module
from tests.unit.test_league_views import _legal_squad, _member_picks, _Provider, _world_context
from tests.unit.test_publication_services import publication_world

from squadopt.application import league_publication, player_names
from squadopt.application.entries import EntryRegistration
from squadopt.application.league_publication import publish_league
from squadopt.application.league_views import build_league_views
from squadopt.application.player_names import (
    GameName,
    game_names,
    with_full_name_accents,
    with_game_short_names,
)

world = world_module._world  # re-register the fixture in this module


def _element(code: int, first: str, second: str, web_name: str | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": code,
        "id": code,
        "first_name": first,
        "second_name": second,
        "team": 1,
        "element_type": 4,
        "now_cost": 70,
    }
    if web_name is not None:
        record["web_name"] = web_name
    return record


def _bootstrap(*elements: dict[str, Any]) -> bytes:
    return json.dumps(
        {"teams": [{"id": 1, "name": "Brentford"}], "elements": list(elements)}
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("short", "full", "published"),
    [
        # The game drops the accents its own full name keeps; the page puts them back.
        ("Kinsky", "Antonín Kinský", "Kinský"),
        ("Vuskovic", "Luka Vušković", "Vušković"),
        ("Gomez", "Diego Gómez Amarilla", "Gómez"),
        # A letter the decomposition leaves whole is folded by hand.
        ("Odegaard", "Martin Ødegaard", "Ødegaard"),
        # Accents are only added: the game's own accent stays where the full name has none.
        ("Šeško", "Benjamin Sesko", "Šeško"),
        ("Horníček", "Lukás Hornícek", "Horníček"),
        # The game's own capitals, initials and dots stay as it wrote them.
        ("Van Hecke", "Jan Paul van Hecke", "Van Hecke"),
        ("B.Fernandes", "Bruno Borges Fernandes", "B.Fernandes"),
        ("Bruno G.", "Bruno Guimarães Rodriguez Moura", "Bruno G."),
        ("M.Sangaré", "Mamadou Sangaré", "M.Sangaré"),
        # A word the full name does not hold is left alone.
        ("Thiago", "Igor Thiago Nascimento Rodrigues", "Thiago"),
        # Two spellings of one word in the full name: neither is chosen.
        ("Jose", "José Jose Sá", "Jose"),
    ],
)
def test_a_short_name_takes_the_full_name_s_accents_and_nothing_else(
    short: str, full: str, published: str
) -> None:
    assert with_full_name_accents(short, full) == published


def test_the_capture_names_each_rostered_player_by_his_code_with_the_game_s_short_name() -> None:
    bootstrap = _bootstrap(
        _element(502500, "Igor Thiago", "Nascimento Rodrigues", "Thiago"),
        _element(495432, "Antonín", "Kinský", "Kinsky"),
        # No web_name: he is not named here, so he keeps the label he had.
        _element(111, "Given", "Name", None),
        _element(112, "Blank", "Label", "  "),
        # Not on the roster the publication read: nothing to name.
        _element(113, "Not", "Rostered", "Rostered"),
    )
    roster = pd.DataFrame(
        {
            "player_id": [111, 112, 495432, 502500],
            "name": [
                "Given Name",
                "Blank Label",
                "Antonín Kinský",
                "Igor Thiago Nascimento Rodrigues",
            ],
        }
    )

    assert game_names(bootstrap, roster) == {
        495432: GameName("Antonín Kinský", "Kinský"),
        502500: GameName("Igor Thiago Nascimento Rodrigues", "Thiago"),
    }


def test_only_a_player_record_of_the_named_player_is_relabelled() -> None:
    names = {502500: GameName("Igor Thiago Nascimento Rodrigues", "Thiago")}
    thiago = {
        "player_id": 502500,
        "name": "Igor Thiago Nascimento Rodrigues",
        "short_name": "Rodrigues",
        "position": "FWD",
    }
    document = {
        "starting_xi": [thiago],
        "moves": [{"player_in": dict(thiago), "player_out": None}],
        # The device tables key a player on ``id``.
        "players": ({**{k: v for k, v in thiago.items() if k != "player_id"}, "id": 502500},),
        # A record whose name is not the capture's for that code keeps its label.
        "renamed": {**thiago, "name": "Someone Else"},
        # A club is not a player even when its id matches a code.
        "team": {"id": 502500, "name": "Brentford", "short_name": "BRE"},
        "count": 502500,
    }

    relabelled = with_game_short_names(document, names)

    assert relabelled == {
        "starting_xi": [{**thiago, "short_name": "Thiago"}],
        "moves": [{"player_in": {**thiago, "short_name": "Thiago"}, "player_out": None}],
        "players": [
            {
                "name": "Igor Thiago Nascimento Rodrigues",
                "short_name": "Thiago",
                "position": "FWD",
                "id": 502500,
            }
        ],
        "renamed": {**thiago, "name": "Someone Else"},
        "team": {"id": 502500, "name": "Brentford", "short_name": "BRE"},
        "count": 502500,
    }
    # The input is not changed under its holder.
    assert document["starting_xi"] == [thiago] and thiago["short_name"] == "Rodrigues"
    # Without names the document itself comes back, so its bytes cannot move.
    assert with_game_short_names(document, {}) is document


def _tree(root: Path) -> dict[str, Any]:
    return {
        path.relative_to(root).as_posix(): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.rglob("*.json"))
    }


def test_the_short_names_move_every_label_in_the_tree_and_nothing_else(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    names = {
        int(code): GameName(str(name), f"Game {code}")
        for code, name in zip(inputs.players["player_id"], inputs.players["name"], strict=True)
    }

    def build(out: Path, **extra: Any) -> dict[str, Any]:
        build_league_views(
            _Provider({101: picks}),
            (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=out,
            now=datetime(2026, 8, 23, 9, tzinfo=UTC),
            **extra,
        )
        return _tree(out)

    before = build(tmp_path / "before")
    after = build(tmp_path / "after", short_names=names)

    assert after.keys() == before.keys()
    assert {path: with_game_short_names(document, names) for path, document in before.items()} == (
        after
    )
    entry = after["entries/101.json"]["payload"]
    squad = [*entry["starting_xi"], *entry["bench"]]
    assert [player["short_name"] for player in squad] == [
        f"Game {player['player_id']}" for player in squad
    ]
    table = after["device-plan.json"]["payload"]["players"]
    assert [player["short_name"] for player in table] == [
        f"Game {player['id']}" for player in table
    ]
    assert after != before


def test_the_publication_names_the_tree_and_the_capture_table_from_the_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def with_web_names(bootstrap: bytes, players: pd.DataFrame) -> dict[int, GameName]:
        document = json.loads(bootstrap)
        for element in document["elements"]:
            element["web_name"] = f"Game {element['code']}"
        return player_names.game_names(json.dumps(document).encode("utf-8"), players)

    monkeypatch.setattr(league_publication, "game_names", with_web_names)
    request = publication_world(tmp_path)
    publish_league(request)
    data = request.out_dir / "data"

    shared = json.loads(
        (data / "device" / request.snapshot_id / "device-plan.json").read_text(encoding="utf-8")
    )["payload"]["players"]
    assert shared and all(player["short_name"] == f"Game {player['id']}" for player in shared)
    tree = _tree(data / "leagues" / "352490")
    entries = [document for path, document in tree.items() if path.startswith("entries/")]
    assert entries
    for document in entries:
        squad = [*document["payload"]["starting_xi"], *document["payload"]["bench"]]
        assert squad and all(p["short_name"] == f"Game {p['player_id']}" for p in squad)
