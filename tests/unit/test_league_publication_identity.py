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
from squadopt.data.errors import DataError
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


def test_markerless_interrupted_legacy_copies_do_not_admit_unrecorded_history(case, monkeypatch):
    marker_path = bundle.football_bundle_path(case["artifact_root"], case["snapshot_id"])
    original = bundle.write_bytes_once

    def interrupt_at_marker(raw, target):
        if target == marker_path:
            raise OSError("synthetic interruption after copies")
        return original(raw, target)

    monkeypatch.setattr(bundle, "write_bytes_once", interrupt_at_marker)
    with pytest.raises(OSError, match="after copies"):
        bundle.seal_football_bundle(**case)
    monkeypatch.setattr(bundle, "write_bytes_once", original)
    assert not marker_path.exists()
    copies = {
        path.relative_to(case["artifact_root"]).as_posix(): path.read_bytes()
        for path in case["artifact_root"].rglob("*")
        if path.is_file()
    }
    assert any(name.endswith("site/league/members.json") for name in copies)
    dump(
        case["site_data_root"] / "league/scoreboard.json",
        {"payload": {"as_of_snapshot_id": "previous"}},
    )
    with pytest.raises(ValueError, match="Retained league history requires"):
        bundle.seal_football_bundle(**case)
    assert not marker_path.exists()
    assert copies == {
        path.relative_to(case["artifact_root"]).as_posix(): path.read_bytes()
        for path in case["artifact_root"].rglob("*")
        if path.is_file()
    }


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
    assert tree / IDENTITY_FILE in result.output_paths
    assert "scoreboard.json" in check_tree_identity(tree)["files"]


@pytest.mark.parametrize(
    "record",
    [
        [],
        None,
        "not-an-object",
        {},
        {"source_snapshot_id": None},
        {"source_snapshot_id": ""},
        {"source_snapshot_id": "   "},
        {"source_snapshot_id": True},
        {"source_snapshot_id": 3},
    ],
)
def test_scoreboard_refuses_malformed_retained_identity_before_writing(tmp_path, record):
    from dataclasses import replace

    from tests.unit.test_publication_services import publication_world

    from squadopt.application import scoreboard as writer
    from squadopt.application.league_publication import publish_league

    request = replace(publication_world(tmp_path), record_root=None)
    publish_league(request)
    tree = request.out_dir / "data/leagues/352490"
    identity_path = tree / IDENTITY_FILE
    dump(identity_path, record)
    before = {path.name: path.read_bytes() for path in tree.iterdir() if path.is_file()}
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
    with pytest.raises(DataError, match=r"publication-identity\.json") as refused:
        writer.publish_scoreboard(board)
    assert type(refused.value) is DataError
    assert str(identity_path) in str(refused.value)
    assert before == {path.name: path.read_bytes() for path in tree.iterdir() if path.is_file()}
    assert not (tree / "scoreboard.json").exists()


def test_retained_scoreboard_identity_reads_through_addressable_path(tmp_path, monkeypatch):
    from squadopt.application import scoreboard as writer

    tree = tmp_path / "league"
    identity_path = tree / IDENTITY_FILE
    redirected = tmp_path / "addressable-record.json"
    dump(identity_path, {"source_snapshot_id": "wrong-unwrapped-capture"})
    dump(redirected, {"source_snapshot_id": "wrapped-capture"})
    calls = []

    def addressable_record(path):
        calls.append(path)
        return str(redirected) if path == identity_path else str(path)

    monkeypatch.setattr(writer, "addressable", addressable_record)
    assert writer._retained_publication_capture(tree) == "wrapped-capture"
    assert calls == [identity_path]


def test_retained_scoreboard_identity_unreadable_json_has_named_data_error(tmp_path):
    from squadopt.application import scoreboard as writer

    tree = tmp_path / "league"
    tree.mkdir()
    identity_path = tree / IDENTITY_FILE
    identity_path.write_bytes(b"{not-json")
    with pytest.raises(DataError, match=r"publication-identity\.json") as refused:
        writer._retained_publication_capture(tree)
    assert type(refused.value) is DataError
    assert isinstance(refused.value.__cause__, ValueError)


def test_check_script_names_changed_identity_and_prints_success(tmp_path, capsys):
    tree = release_tree(tmp_path, "decision", "settled")
    assert main([str(tree.parent)]) == 0
    assert "publication identity: verified" in capsys.readouterr().out
    dump(tree / "scoreboard.json", {"payload": {"source_snapshot_id": "substitute"}})
    assert main([str(tree.parent)]) == 1
    output = capsys.readouterr().out
    assert "publication identity: League publication file changed: scoreboard.json." in output
    assert "publication identity: unreadable tree" not in output
    assert output.rstrip().endswith("FINAL: FAILURE(S)")


def test_release_command_refuses_an_unrecorded_extra_history_file(tmp_path, capsys):
    tree = release_tree(tmp_path, "decision", "settled")
    dump(tree / "history/2.json", {"payload": {"as_of_snapshot_id": "extra"}})
    assert main([str(tree.parent)]) == 1
    output = capsys.readouterr().out
    assert "inventory changed" in output
    assert output.rstrip().endswith("FINAL: FAILURE(S)")


def test_league_with_every_member_refused_still_records_writer_capture(tmp_path):
    from dataclasses import replace

    from tests.unit.test_backend_runtime import _handoff
    from tests.unit.test_publication_services import publication_world

    from squadopt.application.league_publication import publish_league
    from squadopt.data.snapshots import read_snapshot, write_snapshot

    request = publication_world(tmp_path)
    previous = read_snapshot(request.snapshot_root, request.snapshot_id)
    payloads = {k: v for k, v in previous.payloads.items() if not k.startswith("entry-")}
    capture = write_snapshot(
        request.snapshot_root,
        source=previous.metadata.source,
        captured_at_utc=previous.metadata.captured_at_utc,
        payloads=payloads,
    )
    request = replace(
        request,
        snapshot_id=capture.snapshot_id,
        record_root=None,
        handoff_path=_handoff(tmp_path / "new-handoff", capture.snapshot_id),
    )
    publish_league(request)
    tree = request.out_dir / "data/leagues/352490"
    identity = check_tree_identity(tree)
    assert identity["source_snapshot_id"] == request.snapshot_id
    assert not any(name.startswith("entries/") for name in identity["files"])


@pytest.mark.parametrize("stage", ["league", "scoreboard"])
def test_same_weekly_run_resumes_interrupted_writers_and_completes(tmp_path, monkeypatch, stage):
    import shutil
    from dataclasses import replace

    from tests.unit.test_publication_services import publication_world
    from tests.unit.test_weekly_operations import world

    from squadopt.application import league_publication, scoreboard
    from squadopt.platform.weekly_journal import inspect_run
    from squadopt.platform.weekly_operations import WeeklyOperations

    prior = replace(publication_world(tmp_path / "previous"), record_root=None)
    league_publication.publish_league(prior)
    operation = world(tmp_path / "next")
    source = operation._published_tree()
    source.parent.mkdir(parents=True)
    shutil.copytree(prior.out_dir / "data", source)
    writer = league_publication if stage == "league" else scoreboard
    name = "write_league_directory" if stage == "league" else "record_tree_identity"
    original = getattr(writer, name)

    def interrupted(*args, **kwargs):
        raise OSError("synthetic completed files before identity")

    monkeypatch.setattr(writer, name, interrupted)
    with pytest.raises(OSError, match="completed files before identity"):
        operation.execute()
    failed = inspect_run(operation.paths.journal, operation.run_id)
    assert next(s for s in failed["stages"] if s["name"] == stage)["status"] == "failed"
    monkeypatch.setattr(writer, name, original)
    resumed = WeeklyOperations(
        operation.request,
        operation.paths,
        run_id=operation.run_id,
        repository_commit=operation.repository_commit,
        resume=True,
        handoff=operation.supplied_handoff,
    )
    receipt = json.loads(resumed.execute().read_bytes())
    assert receipt["status"] == "completed"
    assert all(s["status"] == "completed" for s in receipt["stages"])
    tree = operation.paths.out / "data/leagues/352490"
    assert check_tree_identity(tree)["source_snapshot_id"] == operation.request.snapshot_id
    assert "scoreboard.json" in check_tree_identity(tree)["files"]


def test_deep_path_bundle_seals_and_reads_the_retained_tree(case, tmp_path):
    from squadopt.data._long_paths import addressable

    add_history(case)
    deep = tmp_path.joinpath(*("deep-path-" + str(i) + "x" * 35 for i in range(5)))
    assert (
        len(str(deep / "football" / (case["snapshot_id"] + ".bundle/site/league") / IDENTITY_FILE))
        > 260
    )
    artifact_root = deep / "artifacts"
    for role in ("forecast", "components"):
        current = (
            bundle.football_artifact_path if role == "forecast" else bundle.football_components_path
        )
        source = current(case["artifact_root"], case["snapshot_id"])
        target = current(artifact_root, case["snapshot_id"])
        Path(addressable(target.parent)).mkdir(parents=True, exist_ok=True)
        Path(addressable(target)).write_bytes(source.read_bytes())
    ready = bundle.seal_football_bundle(**{**case, "artifact_root": artifact_root})
    tree = ready.files["site_members"].parent
    assert Path(addressable(tree / IDENTITY_FILE)).is_file()
    assert check_tree_identity(tree) is not None
    read = bundle.read_football_bundle(
        artifact_root=artifact_root,
        snapshot_root=case["snapshot_root"],
        snapshot_id=case["snapshot_id"],
    )
    assert read.fingerprint == ready.fingerprint
