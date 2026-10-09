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


def test_retained_history_without_record_never_seals(case):
    tree = case["site_data_root"] / "league"
    dump(tree / "scoreboard.json", {"payload": {"as_of_snapshot_id": "previous"}})
    with pytest.raises(ValueError, match="Retained league history requires"):
        bundle.seal_football_bundle(**case)
    assert not bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"]).exists()


def test_legacy_ready_bundle_replays_after_source_gains_unrecorded_history(case):
    ready = bundle.seal_football_bundle(**case)
    before = ready.marker_path.read_bytes()
    dump(
        case["site_data_root"] / "league/scoreboard.json",
        {"payload": {"as_of_snapshot_id": "previous"}},
    )
    replay = bundle.seal_football_bundle(**case)
    assert replay.fingerprint == ready.fingerprint
    assert ready.marker_path.read_bytes() == before
    assert not any(role.startswith("site_tree_") for role in replay.files)


@pytest.mark.parametrize("layout", ["legacy", "directory"])
def test_seed_refuses_changed_inherited_tree_before_copy(tmp_path, layout):
    from types import SimpleNamespace

    from squadopt.platform.weekly_operations import WeeklyOperations

    source = tmp_path / "published"
    tree = release_tree(source, "decision", "settled")
    if layout == "directory":
        from squadopt.contracts.league_tree import PublishedLeague, write_league_directory

        target = source / "leagues/9"
        target.parent.mkdir()
        tree.rename(target)
        tree = target
        write_league_directory(
            source,
            [PublishedLeague(9, "Synthetic", "2026-27", 6, "leagues/9")],
            generated_at_utc="2026-10-08T00:00:00Z",
        )
    dump(tree / "history/1.json", {"payload": {"as_of_snapshot_id": "substituted"}})
    operation = SimpleNamespace(
        paths=SimpleNamespace(out=tmp_path / "preview"), _published_tree=lambda: source
    )
    with pytest.raises(ValueError, match=r"file changed: history/1\.json"):
        WeeklyOperations._seed_preview(operation)
    assert not (tmp_path / "preview/data").exists()


def test_seed_checks_once_and_does_not_reject_interrupted_preview(tmp_path):
    from types import SimpleNamespace

    from squadopt.platform.weekly_operations import WeeklyOperations

    source = tmp_path / "published"
    release_tree(source, "decision", "settled")
    operation = SimpleNamespace(
        paths=SimpleNamespace(out=tmp_path / "preview"), _published_tree=lambda: source
    )
    WeeklyOperations._seed_preview(operation)
    preview = tmp_path / "preview/data/league"
    dump(preview / "members.json", {"payload": {"interrupted": True}})
    WeeklyOperations._seed_preview(operation)
    assert json.loads((preview / "members.json").read_bytes())["payload"]["interrupted"] is True


def test_league_writer_resumes_after_files_were_written(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import timedelta

    from tests.unit.test_publication_services import NOW, publication_world

    from squadopt.application import league_publication as writer

    request = replace(publication_world(tmp_path), record_root=None)
    writer.publish_league(request)
    tree = request.out_dir / "data/leagues/352490"
    assert check_tree_identity(tree) is not None
    original = writer.write_league_directory

    def interrupt(*args, **kwargs):
        raise OSError("synthetic after league build")

    monkeypatch.setattr(writer, "write_league_directory", interrupt)
    changed = replace(request, now=NOW + timedelta(hours=1))
    with pytest.raises(OSError, match="after league build"):
        writer.publish_league(changed)
    with pytest.raises(ValueError, match=r"file (changed|inventory changed)"):
        check_tree_identity(tree)
    monkeypatch.setattr(writer, "write_league_directory", original)
    writer.publish_league(changed)
    assert check_tree_identity(tree)["source_snapshot_id"] == request.snapshot_id


def test_scoreboard_writer_resumes_and_records_completed_scoreboard(tmp_path, monkeypatch):
    from dataclasses import replace

    from tests.unit.test_publication_services import publication_world

    from squadopt.application import scoreboard as writer
    from squadopt.application.league_publication import publish_league

    request = replace(publication_world(tmp_path), record_root=None)
    publish_league(request)
    tree = request.out_dir / "data/leagues/352490"
    board = writer.ScoreboardPublicationRequest(
        snapshot_root=request.snapshot_root,
        snapshot_id=request.snapshot_id,
        registry_path=request.registry_path,
        ledger_root=tmp_path / "empty-ledger",
        out_dir=request.out_dir,
        league_id=request.league_id,
        season=request.season,
        now_utc="2026-08-27T11:00:00Z",
    )
    original = writer.record_tree_identity

    def interrupt(*args, **kwargs):
        raise OSError("synthetic after scoreboard write")

    monkeypatch.setattr(writer, "record_tree_identity", interrupt)
    with pytest.raises(OSError, match="after scoreboard write"):
        writer.publish_scoreboard(board)
    with pytest.raises(ValueError, match=r"file (changed|inventory changed)"):
        check_tree_identity(tree)
    monkeypatch.setattr(writer, "record_tree_identity", original)
    result = writer.publish_scoreboard(board)
    assert result.target.is_file()
    assert "scoreboard.json" in check_tree_identity(tree)["files"]


def test_check_script_names_changed_identity_and_prints_success(tmp_path, capsys):
    tree = release_tree(tmp_path, "decision", "settled")
    assert main([str(tree.parent)]) == 0
    assert "publication identity: verified" in capsys.readouterr().out
    dump(tree / "scoreboard.json", {"payload": {"source_snapshot_id": "substitute"}})
    assert main([str(tree.parent)]) == 1
    output = capsys.readouterr().out
    assert "publication identity: League publication file changed: scoreboard.json." in output
    assert "publication identity: unreadable tree" not in output
