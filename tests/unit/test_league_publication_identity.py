"""Two-publication substitutions must fail before a tree becomes a ready bundle."""

import json
from pathlib import Path

import pytest
from scripts.check_league_tree import main
from tests.unit.test_check_league_tree import _tree, _write
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle import dump
from tests.unit.test_football_bundle import publication_case as publication_case

from squadopt.application.league_tree_identity import check_tree_identity, record_tree_identity
from squadopt.contracts.league_publication_identity import IDENTITY_FILE
from squadopt.platform import football_bundle as bundle


def release_tree(root: Path, capture: str, older: str) -> Path:
    _tree(root)
    members = {
        "league_id": 9,
        "season": "2026-27",
        "gameweek": 6,
        "members": [{"entry_id": 1, "member_kind": "human"}],
    }
    _write(root, "members.json", members)
    _write(
        root,
        "entries/1.json",
        {**members, "entry": members["members"][0], "source_snapshot_id": capture},
    )
    _write(root, "history/1.json", {"as_of_snapshot_id": older, "weeks": [5]})
    _write(root, "series-horizon.json", {"as_of_snapshot_id": older, "keys": ["1:5"]})
    _write(root, "scoreboard.json", {"source_snapshot_id": older, "points": [10]})
    tree = root / "league"
    record_tree_identity(tree)
    return tree


@pytest.mark.parametrize(
    "substitute",
    ["members.json", "entries/1.json", "history/1.json", "scoreboard.json", "series-horizon.json"],
)
def test_two_publication_tree_is_refused_by_release_command(tmp_path, substitute, capsys):
    first = release_tree(tmp_path / "a", "decision-a", "settled-a")
    second = release_tree(tmp_path / "b", "decision-b", "settled-b")
    assert main([str(first.parent)]) == 0
    assert "ALL GOOD" in capsys.readouterr().out
    (first / substitute).write_bytes((second / substitute).read_bytes())
    # members have equal values here; change its generation as a real publication does.
    if substitute == "members.json":
        document = json.loads((first / substitute).read_bytes())
        document["generated_at_utc"] = "2026-10-08T01:00:00Z"
        (first / substitute).write_text(json.dumps(document), encoding="utf-8")
    assert main([str(first.parent)]) == 1
    assert f"League publication file changed: {substitute}" in capsys.readouterr().out


def test_added_or_removed_retained_files_cannot_escape_inventory(tmp_path):
    tree = release_tree(tmp_path, "decision", "settled")
    _write(tmp_path, "history/2.json", {})
    with pytest.raises(ValueError, match="inventory changed"):
        check_tree_identity(tree)


def test_record_refuses_two_human_captures_before_writing_identity(tmp_path):
    tree = release_tree(tmp_path, "decision", "settled")
    old = (tree / IDENTITY_FILE).read_bytes()
    members = json.loads((tree / "members.json").read_bytes())["payload"]
    members["members"].append({"entry_id": 2, "member_kind": "human"})
    _write(tmp_path, "members.json", members)
    _write(
        tmp_path,
        "entries/2.json",
        {**members, "entry": members["members"][1], "source_snapshot_id": "other-decision"},
    )
    with pytest.raises(ValueError, match="different human entry captures"):
        record_tree_identity(tree)
    assert (tree / IDENTITY_FILE).read_bytes() == old


def add_history(case):
    tree = case["site_data_root"] / "league"
    for name in ("scoreboard.json", "history/101.json", "series-horizon.json"):
        dump(tree / name, {"payload": {"as_of_snapshot_id": "previous", "weeks": [5]}})
    record_tree_identity(tree)
    return tree


def test_sealed_bundle_keeps_the_complete_previous_history_set(case):
    tree = add_history(case)
    result = bundle.seal_football_bundle(**case)
    for name in ("scoreboard.json", "history/101.json", "series-horizon.json", IDENTITY_FILE):
        sealed = result.files["site_members"].parent / name
        assert sealed.read_bytes() == (tree / name).read_bytes()
    check_tree_identity(result.files["site_members"].parent)
    assert (
        bundle.read_football_bundle(
            **{key: case[key] for key in ("artifact_root", "snapshot_root", "snapshot_id")}
        ).fingerprint
        == result.fingerprint
    )


def test_mixed_retained_history_never_becomes_ready(case):
    tree = add_history(case)
    dump(tree / "scoreboard.json", {"payload": {"as_of_snapshot_id": "other-publication"}})
    with pytest.raises(ValueError, match=r"scoreboard\.json"):
        bundle.seal_football_bundle(**case)
    assert not bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"]).exists()
