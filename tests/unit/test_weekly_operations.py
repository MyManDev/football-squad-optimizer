"""Weekly service composition keeps provenance, preflight and preview semantics."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.test_publication_services import publication_world

from squadopt.application.build import _recent_events
from squadopt.application.weekly_plan import WeekError, WeeklyRequest, rotation_artifact
from squadopt.contracts.run_logs import LOG_ROOT_NAME
from squadopt.platform import weekly_operations as weekly
from squadopt.platform.weekly_journal import WeeklyJournalError, fingerprint_paths, inspect_run


def world(tmp_path: Path, *, rotation: bool = False) -> weekly.WeeklyOperations:
    publication = publication_world(tmp_path)
    snapshots = tmp_path / "weekly-snapshots"
    shutil.copytree(
        publication.snapshot_root / publication.snapshot_id, snapshots / publication.snapshot_id
    )
    paths = replace(
        weekly.WeeklyPaths.under(tmp_path),
        snapshots=snapshots,
        archive=publication.archive_root,
        registry=publication.registry_path,
        handoffs=tmp_path / "published-handoffs",
        out=publication.out_dir,
    )
    request = WeeklyRequest(
        "2026-27",
        2,
        publication.league_id,
        snapshot_id=publication.snapshot_id,
        skip_top100=True,
        rotation=rotation,
        workers=1,
    )
    return weekly.WeeklyOperations(
        request,
        paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        handoff=publication.handoff_path,
    )


def test_real_weekly_services_complete_and_resume_without_rebuilding(tmp_path: Path) -> None:
    operation = world(tmp_path)
    receipt = operation.execute()
    doc = json.loads(receipt.read_bytes())
    assert doc["status"] == "completed"
    names = [stage["name"] for stage in doc["stages"]]
    assert names == [
        "preflight",
        "capture",
        "settled_outcomes",
        "handoff",
        "league",
        "site",
        "scoreboard",
    ]
    settled = doc["stages"][2]["value"]
    assert settled["gameweeks_exported"] == [] and settled["skipped"]
    assert not operation.paths.records.exists()
    members = json.loads((operation.paths.out / "data/league/members.json").read_bytes())
    assert members["payload"]["gameweek"] == 2 and members["payload"]["season"] == "2026-27"
    entry = json.loads((operation.paths.out / "data/league/entries/101.json").read_bytes())
    assert entry["payload"]["source_snapshot_id"] == operation.request.snapshot_id
    before = fingerprint_paths([operation.paths.out])
    resumed = weekly.WeeklyOperations(
        operation.request,
        operation.paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        resume=True,
        handoff=operation.supplied_handoff,
    )
    resumed.execute()
    assert fingerprint_paths([operation.paths.out]) == before
    assert inspect_run(operation.paths.journal, "synthetic")["status"] == "completed"
    # A mutable alias changed by another writer is not accepted just because the run succeeded.
    alias = operation.paths.handoffs / "2026-27-gw02.json"
    alias.write_bytes(alias.read_bytes() + b" ")
    assert inspect_run(operation.paths.journal, "synthetic")["status"] == "invalid_artifacts"
    with pytest.raises(WeeklyJournalError, match="changed"):
        resumed.execute()


def test_wrong_capture_handoff_is_rejected_before_alias_write(tmp_path: Path) -> None:
    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": "other-capture"}
    with pytest.raises(WeekError, match="exact capture"):
        operation._handoff()
    assert not operation.paths.handoffs.exists()


def _git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_checkout(tmp_path: Path) -> tuple[Path, weekly.WeeklyPaths, list[str]]:
    """A clean Git checkout holding the synthetic world, and the arguments that run it."""

    publication = publication_world(tmp_path / "fixtures")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    paths = weekly.WeeklyPaths.under(checkout)
    shutil.copytree(
        publication.snapshot_root / publication.snapshot_id,
        paths.snapshots / publication.snapshot_id,
    )
    shutil.copytree(publication.archive_root, paths.archive)
    paths.registry.parent.mkdir(parents=True)
    shutil.copyfile(publication.registry_path, paths.registry)
    handoff = checkout / "data/prebuilt.json"
    shutil.copyfile(publication.handoff_path, handoff)
    # Anchored: the published tree under web/public/data is tracked, as it is in the repo.
    (checkout / ".gitignore").write_text("/data/\n/artifacts/\n/.codex-tmp/\n")
    (checkout / "source.py").write_text("unchanged")
    public = checkout / "web/public/data/members.json"
    public.parent.mkdir(parents=True)
    public.write_text("previous publication")
    _git(checkout, "init", "-q")
    # The publish stage commits from a worktree of this repository; the identity has to
    # live in the repository, not in this helper's command line, or a runner without a
    # global identity refuses that commit.
    _git(checkout, "config", "user.name", "Synthetic")
    _git(checkout, "config", "user.email", "synthetic@example.invalid")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "fixture")
    args = [
        "--workspace",
        str(checkout),
        "--season",
        "2026-27",
        "--gameweek",
        "2",
        "--league",
        "352490",
        "--snapshot-id",
        publication.snapshot_id,
        "--skip-top100",
        "--workers",
        "1",
        "--handoff",
        str(handoff),
    ]
    return checkout, paths, args


def _origin_develop_behind_head(checkout: Path) -> str:
    """Publish HEAD as ``origin/develop``, then commit once more so HEAD is ahead of it."""

    origin = checkout.parent / "origin.git"
    _git(checkout, "init", "-q", "--bare", str(origin))
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/develop")
    (checkout / "source.py").write_text("committed here, not yet on develop")
    _git(checkout, "commit", "-qam", "unmerged")
    return _git(checkout, "rev-parse", "origin/develop")


def test_default_preview_can_resume_in_clean_git_checkout_but_source_drift_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout, paths, base = _git_checkout(tmp_path)
    source = checkout / "source.py"
    public = checkout / "web/public/data/members.json"
    args = [*base, "--run-id", "git-resume"]
    actual_scoreboard = weekly.publish_scoreboard

    def interrupt(request):
        raise OSError("synthetic interruption after preview member/site build")

    monkeypatch.setattr(weekly, "publish_scoreboard", interrupt)
    assert weekly.main(args) == 1
    assert inspect_run(paths.journal, "git-resume")["status"] == "failed"
    assert public.read_text() == "previous publication"
    monkeypatch.setattr(weekly, "publish_scoreboard", actual_scoreboard)
    assert weekly.main([*args, "--resume"]) == 0
    assert (paths.journal / "git-resume/preview/data/league/members.json").is_file()
    source.write_text("unrelated source edit")
    assert weekly.main([*args, "--resume"]) == 1


def test_a_publish_off_the_fresh_origin_develop_refuses_in_preflight(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The publication base is checked before a capture or a solve is spent on a run that
    the publish stage would refuse hours later; the refusal names the recovery."""

    checkout, paths, args = _git_checkout(tmp_path)
    base = _origin_develop_behind_head(checkout)
    head = _git(checkout, "rev-parse", "HEAD")
    assert base != head

    assert weekly.main([*args, "--publish", "--run-id", "off-develop"]) == 1

    stderr = capsys.readouterr().err
    assert "run_week stopped:" in stderr
    assert "origin/develop" in stderr and base[:12] in stderr and head[:12] in stderr
    assert "start a new run" in stderr
    doc = json.loads((paths.journal / "off-develop/run.json").read_bytes())
    assert doc["stages"][0]["name"] == "preflight" and doc["stages"][0]["status"] == "failed"
    assert all(stage["status"] == "pending" for stage in doc["stages"][1:])
    assert not (checkout / ".codex-tmp").exists()


def test_the_publish_stage_checks_the_base_again_before_touching_git(tmp_path: Path) -> None:
    """The backstop: develop can move during the run, so the last stage checks once more,
    before any worktree or branch exists, and names the same recovery."""

    from squadopt.platform.weekly_publish import PublishError, PublishNames, publish

    checkout, _, _ = _git_checkout(tmp_path)
    _origin_develop_behind_head(checkout)
    head = _git(checkout, "rev-parse", "HEAD")

    with pytest.raises(PublishError, match="origin/develop") as refusal:
        publish(
            PublishNames("2026-27", 2, "decision"),
            force_branch=False,
            dry_run=True,
            workspace=checkout,
            expected_commit=head,
        )
    assert "start a new run" in str(refusal.value)
    assert not (checkout / ".codex-tmp").exists()


def test_a_settled_outcome_refusal_is_stated_at_the_run_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's own refusal reaches the operator as a stated refusal with exit 1, not as
    an uncaught traceback, and the journal shows where the run stopped."""

    from squadopt.application.settled_outcomes import SettledOutcomeExportError

    _, paths, args = _git_checkout(tmp_path)

    def refuse(request):
        raise SettledOutcomeExportError("synthetic: manifest describes a different artifact")

    monkeypatch.setattr(weekly, "export_settled_outcomes", refuse)
    assert weekly.main([*args, "--run-id", "settled-refusal"]) == 1

    stderr = capsys.readouterr().err
    assert "run_week stopped: synthetic: manifest describes a different artifact" in stderr
    doc = json.loads((paths.journal / "settled-refusal/run.json").read_bytes())
    statuses = {stage["name"]: stage["status"] for stage in doc["stages"]}
    assert statuses["preflight"] == "completed" and statuses["capture"] == "completed"
    assert statuses["settled_outcomes"] == "failed"
    assert statuses["handoff"] == "pending" and statuses["league"] == "pending"


def test_prebuilt_handoff_cannot_claim_fresh_top100_composition(tmp_path: Path) -> None:
    operation = world(tmp_path)
    request = replace(
        operation.request, skip_top100=False, cohort_snapshot="cohort", elite_snapshot="elite"
    )
    with pytest.raises(WeekError, match="does not apply new evidence"):
        weekly.WeeklyOperations(
            request,
            operation.paths,
            run_id="bad",
            repository_commit="b" * 40,
            handoff=operation.supplied_handoff,
        )


@pytest.mark.parametrize("existing", [False, True])
def test_rotation_export_is_capture_pinned_and_existing_pair_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    operation = world(tmp_path)
    operation.run.directory.mkdir(parents=True)
    operation.values["capture"] = {
        "snapshot_id": operation.request.snapshot_id,
        "deadline_utc": "2026-08-28T17:30:00Z",
    }
    table, manifest = rotation_artifact(
        operation.paths.rotation, "2026-27", 2, operation.request.snapshot_id or ""
    )
    calls = []

    def export(request, *, repository_commit):
        calls.append(request)
        assert repository_commit == "b" * 40
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text("table")
        manifest.write_text("manifest")
        return {}

    if existing:
        export(None, repository_commit="b" * 40)
        calls.clear()
    checked = []
    monkeypatch.setattr(weekly, "export_rotation_evidence", export)
    monkeypatch.setattr(
        weekly, "read_rotation_evidence_artifact", lambda *args: checked.append(args)
    )
    result = operation._rotation()
    assert checked == [(table, manifest)]
    assert result.value["table"] == str(table)
    assert len(calls) == (0 if existing else 1)
    if calls:
        assert calls[0].snapshot == operation.request.snapshot_id
        assert calls[0].deadline_utc == "2026-08-28T17:30:00Z"


def test_a_named_capture_reaches_the_export_from_the_stage_that_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--rotation-capture` must arrive at the export, not merely be accepted by the plan.

    The stage flips three things together on the capture: the artifact name, the fixture
    source and ``club_news_snapshot``. Dropping the capture flips all three at once, so the
    request stays internally consistent, ``RotationExportRequest`` never raises its
    exactly-one-source refusal, and the week is read from the synthetic fixture in silence.
    Only an assertion on the request the stage built can tell those two apart.
    """

    capture = "club-news-20260912T143000Z-abcdef123456"
    base = world(tmp_path, rotation=True)
    operation = weekly.WeeklyOperations(
        replace(base.request, rotation_capture=capture),
        base.paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        handoff=base.supplied_handoff,
    )
    operation.run.directory.mkdir(parents=True, exist_ok=True)
    operation.values["capture"] = {
        "snapshot_id": operation.request.snapshot_id,
        "deadline_utc": "2026-08-28T17:30:00Z",
    }
    table, manifest = rotation_artifact(operation.paths.rotation, "2026-27", 2, capture)
    from_decision, _ = rotation_artifact(
        operation.paths.rotation, "2026-27", 2, operation.request.snapshot_id or ""
    )
    # The two names must differ, or the artifact assertion below would prove nothing.
    assert table != from_decision

    calls = []

    def export(request, *, repository_commit):
        calls.append(request)
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text("table")
        manifest.write_text("manifest")
        return {}

    monkeypatch.setattr(weekly, "export_rotation_evidence", export)
    monkeypatch.setattr(weekly, "read_rotation_evidence_artifact", lambda *args: None)
    result = operation._rotation()

    assert len(calls) == 1
    # The capture the claims came from reaches the export as the club-news source.
    assert calls[0].club_news_snapshot == capture
    # It displaces the fixture rather than joining it: naming both sources is refused.
    assert calls[0].club_news_fixture is None
    # The decision capture stays in its own field. A week carries two captures, not one.
    assert calls[0].snapshot == operation.request.snapshot_id
    # And the artifact is named after the claims, so a fixture read cannot reuse this pair.
    assert result.value["table"] == str(table)


def test_missing_reused_rotation_refuses_before_capture_or_export(tmp_path: Path) -> None:
    operation = world(tmp_path, rotation=True)
    with pytest.raises(WeekError, match="already on disk"):
        operation.execute()
    doc = json.loads(operation.run.path.read_bytes())
    assert doc["stages"][0]["status"] == "failed"
    assert all(stage["status"] == "pending" for stage in doc["stages"][1:])


def test_the_preview_records_advice_only_when_it_is_the_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publication records its preview before history reads it; a default preview does not.
    Explicit recording without publication is covered separately below."""

    week = tmp_path / "data/advice_records/2026-27/gw02/entry-101"
    earlier = week / "fpl-live-20260820T120000Z-earlier"
    earlier.mkdir(parents=True)
    (week / ".fpl-live-dying.staging-1-abcd").mkdir()
    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    calls = []

    def publish(request, **kwargs):
        calls.append(request)
        return SimpleNamespace(
            output_paths=(),
            snapshot_id=request.snapshot_id,
            gameweek=2,
            report=SimpleNamespace(members=(), removed=()),
            top100_note="",
        )

    monkeypatch.setattr(weekly, "publish_league", publish)
    assert operation._league().value["advice_recorded"] is False
    # No evidence stage ran, so no Top 100 table reaches the league build.
    assert calls[0].top100_evidence is None
    publishing = weekly.WeeklyOperations(
        replace(operation.request, publish=True),
        operation.paths,
        run_id="publishing",
        repository_commit="b" * 40,
        handoff=operation.supplied_handoff,
    )
    publishing.values.update(operation.values)
    assert publishing._league().value["advice_recorded"] is True
    assert calls[0].record_root is None and calls[0].out_dir == operation.paths.out
    assert calls[1].record_root == operation.paths.records
    assert calls[1].out_dir == operation.paths.out
    assert operation.record_inputs == publishing.record_inputs == [earlier]
    assert "rotation" not in operation.stages

    # When the evidence stage ran, its table reaches the league build; the loader's own
    # gate decides whether the menu is offered.
    table = tmp_path / "player_evidence_v1_2026-27_gw02_top100_111111111111.csv"
    publishing.values["top100_evidence"] = {"table": str(table), "manifest": str(table)}
    assert publishing._league().value["top100_note"] == ""
    assert calls[2].top100_evidence == table


def _origin_develop_at_head(checkout: Path) -> Path:
    """Publish HEAD as ``origin/develop``: the base a weekly publish is allowed from."""

    origin = checkout.parent / "origin.git"
    _git(checkout, "init", "-q", "--bare", str(origin))
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/develop")
    return origin


def _fake_gh(monkeypatch: pytest.MonkeyPatch, pr_url: str) -> None:
    """Git runs for real against the bare origin; only the three gh calls are answered."""

    from squadopt.platform import weekly_publish

    real = weekly_publish._run

    def run(arguments: list[str], *, cwd: Path, check: bool = True) -> str:
        if arguments[0] != "gh":
            return real(arguments, cwd=cwd, check=check)
        if arguments[1:3] == ["pr", "list"]:
            return ""
        if arguments[1:3] == ["pr", "create"]:
            return pr_url
        head = real(["git", "rev-parse", "HEAD"], cwd=cwd)
        return json.dumps({"url": pr_url, "headRefOid": head, "state": "OPEN"})

    monkeypatch.setattr(weekly_publish, "_run", run)


@pytest.mark.parametrize("suffix", ["", "8"])
def test_the_publication_is_the_preview_byte_for_byte(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    """The publish stage commits the tree the preview built rather than solving again, so
    the published documents, the history document included, are the previewed bytes."""

    # A short root: a record's staging sibling has to fit inside Windows' path limit.
    tmp_path = tmp_path_factory.mktemp("pub")
    checkout, paths, args = _git_checkout(tmp_path)
    origin = _origin_develop_at_head(checkout)
    _fake_gh(monkeypatch, "https://example.invalid/pr/1")

    assert weekly.main([*args, "--publish", "--publish-suffix", suffix, "--run-id", "shipped"]) == 0
    names = weekly.PublishNames("2026-27", 2, "decision", suffix)

    preview = paths.journal / "shipped/preview/data"
    published = tmp_path / "published"
    # The committed bytes, not a checkout's line-ending conversion of them.
    _git(
        tmp_path,
        "-c",
        "core.autocrlf=false",
        "clone",
        "-q",
        "--branch",
        names.branch,
        str(origin),
        str(published),
    )
    assert weekly.tree_digests(published / "web/public/data") == weekly.tree_digests(preview)
    history = json.loads((preview / "league/history/101.json").read_bytes())
    assert [week["gameweek"] for week in history["payload"]["weeks"]] == [2]
    assert (published / "web/public/data/league/history/101.json").read_bytes() == (
        preview / "league/history/101.json"
    ).read_bytes()
    snapshot = args[args.index("--snapshot-id") + 1]
    assert (paths.records / "2026-27/gw02/entry-101" / snapshot / "advice.json").is_file()
    doc = json.loads((paths.journal / "shipped/run.json").read_bytes())
    stages = {stage["name"]: stage for stage in doc["stages"]}
    assert stages["league"]["value"]["advice_recorded"] is True
    assert [row["path"] for row in stages["publish"]["inputs"]] == [str(preview)]
    assert stages["publish"]["value"]["status"] == "pr_open"
    assert stages["publish"]["value"]["published_files"] == len(weekly.tree_digests(preview))
    assert not (checkout / names.worktree_directory).exists()
    with pytest.raises(weekly.PublishError, match="already exists on origin"):
        weekly.publish(names, workspace=checkout, force_branch=False, dry_run=True)


def test_record_advice_without_publish_records_every_rendered_member(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    _, paths, args = _git_checkout(tmp_path_factory.mktemp("rec"))
    assert weekly.main([*args, "--record-advice", "--run-id", "recorded"]) == 0
    receipt = json.loads((paths.journal / "recorded/run.json").read_bytes())
    assert "publish" not in [stage["name"] for stage in receipt["stages"]]
    entries = paths.journal / "recorded/preview/data/league/entries"
    rendered = list(entries.glob("*.json"))
    assert rendered
    snapshot = args[args.index("--snapshot-id") + 1]
    for entry in rendered:
        record = paths.records / "2026-27/gw02" / f"entry-{entry.stem}" / snapshot / "advice.json"
        assert record.is_file()
    assert weekly.main([*args, "--record-advice", "--run-id", "recorded", "--resume"]) == 0
    history = json.loads((entries.parent / "history/101.json").read_bytes())
    assert [week["gameweek"] for week in history["payload"]["weeks"]] == [2]
    assert weekly.main([*args, "--run-id", "recorded", "--resume"]) == 1
    assert (
        weekly.main(
            [
                *args,
                "--record-advice",
                "--publish",
                "--publish-suffix",
                "9",
                "--run-id",
                "recorded",
                "--resume",
            ]
        )
        == 1
    )


def test_dry_run_prints_recording_and_the_suffixed_branch_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        weekly.main(
            [
                "--workspace",
                str(tmp_path),
                "--season",
                "2026-27",
                "--gameweek",
                "5",
                "--league",
                "352490",
                "--dry-run",
                "--record-advice",
                "--publish",
                "--publish-suffix",
                "8",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Record advice: True" in output
    assert "publish suffix: 8" in output
    assert "feature/gw05-decision-site-8" in output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "suffix", ["../branch", "space here", "x..y", "--", "x/lock", "-x", "x-", "8\n", "a;b"]
)
def test_invalid_publish_suffix_is_refused(suffix: str) -> None:
    with pytest.raises(weekly.PublishError, match="suffix"):
        weekly.PublishNames("2026-27", 5, "decision", suffix)


def test_a_publish_suffix_needs_publication(capsys):
    with pytest.raises(SystemExit) as error:
        weekly.main(["--publish-suffix", "8", "--dry-run"])
    assert error.value.code == 2
    assert "--publish-suffix requires --publish" in capsys.readouterr().err


def test_a_taken_suffix_refuses_before_the_capture_stage(tmp_path_factory, capsys):
    checkout, paths, args = _git_checkout(tmp_path_factory.mktemp("taken"))
    _origin_develop_at_head(checkout)
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/feature/gw02-decision-site-8")
    assert weekly.main([*args, "--publish", "--publish-suffix", "8", "--run-id", "taken"]) == 1
    receipt = json.loads((paths.journal / "taken/run.json").read_bytes())
    stages = {stage["name"]: stage["status"] for stage in receipt["stages"]}
    assert stages["preflight"] == "failed"
    assert stages["capture"] == "pending"
    assert not any(state == "completed" for state in stages.values())
    assert "choose another --publish-suffix" in capsys.readouterr().err


def test_a_publish_refused_after_the_preview_keeps_its_record_deliberately(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Develop moves between preflight and publish: nothing is committed or pushed, and the
    record the preview wrote for its capture stays. It is deliberate: the record is keyed
    by the capture, a rerun of the same capture is a replay of it, and a rerun from a
    fresher capture records its own; deleting it would make the record rewritable."""

    tmp_path = tmp_path_factory.mktemp("ref")
    checkout, paths, args = _git_checkout(tmp_path)
    origin = _origin_develop_at_head(checkout)
    real_publish = weekly.publish

    def moved(names, **kwargs):
        if kwargs.get("dry_run"):
            return real_publish(names, **kwargs)
        merged = _git(checkout, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "merged")
        _git(checkout, "push", "-q", "origin", f"{merged}:refs/heads/develop")
        return real_publish(names, **kwargs)

    monkeypatch.setattr(weekly, "publish", moved)
    assert weekly.main([*args, "--publish", "--run-id", "refused"]) == 1

    assert "origin/develop" in capsys.readouterr().err
    assert _git(checkout, "ls-remote", "--heads", str(origin), "feature/gw02-decision-site") == ""
    assert not (checkout / ".codex-tmp/publications/gw02-decision").exists()
    doc = json.loads((paths.journal / "refused/run.json").read_bytes())
    stages = {stage["name"]: stage["status"] for stage in doc["stages"]}
    assert stages["league"] == "completed" and stages["publish"] == "uncertain"
    snapshot = args[args.index("--snapshot-id") + 1]
    record = paths.records / "2026-27/gw02/entry-101" / snapshot / "advice.json"
    assert json.loads(record.read_bytes())["state"]["source_snapshot_id"] == snapshot
    history = paths.journal / "refused/preview/data/league/history/101.json"
    assert [w["gameweek"] for w in json.loads(history.read_bytes())["payload"]["weeks"]] == [2]


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--decide", "--chip", "bboost", "--rotation", "--publish"],
        ["--rotation", "--rotation-capture", "club-news-abc123456789"],
        ["--snapshot-id", "capture", "--skip-top100", "--projection", "component-only"],
    ],
)
def test_legacy_and_installed_dry_run_flags_match_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], options: list[str]
) -> None:
    from scripts import run_week as legacy

    args = [
        "--workspace",
        str(tmp_path),
        "--season",
        "2026-27",
        "--gameweek",
        "4",
        "--league",
        "352490",
        "--dry-run",
        *options,
    ]
    assert weekly.main(args) == 0
    installed = capsys.readouterr().out
    assert legacy.main(args) == 0
    assert capsys.readouterr().out == installed
    assert list(tmp_path.iterdir()) == []


def test_a_weekly_run_leaves_the_same_kind_of_run_log_record_a_tick_does(tmp_path: Path) -> None:
    """A completed weekly run was journalled but wrote nothing the status page could read.

    The journal under ``data/runtime/weekly`` records stages for a resume; the run log is
    what the operations status reads. The runner now configures the tick's own component,
    so a week driven by hand shows up beside a scheduled tick.
    """

    operation = world(tmp_path)
    operation.execute()

    root = operation.paths.log_root
    assert root == tmp_path / LOG_ROOT_NAME
    events = _recent_events(root, "season_tick", 200)
    assert events, "a weekly run must leave a record the status page can read"
    assert {event.run_id for event in events} == {"synthetic"}

    messages = [event.message for event in events]
    assert "tick.week.plan" in messages and "tick.week.done" in messages
    stages_started = {
        str(event.fields["stage"]) for event in events if event.message == "tick.week.stage.start"
    }
    assert stages_started == set(operation.stages)

    plan = next(event for event in events if event.message == "tick.week.plan")
    assert plan.fields["season"] == "2026-27" and plan.fields["gameweek"] == 2
    assert plan.level == "INFO" and plan.ts


# --- the rotation stage's source --------------------------------------------


def test_a_named_capture_reaches_the_export_and_names_its_artifact() -> None:
    """The eighth field, finally set.

    `RotationExportRequest` has carried `club_news_snapshot` and its exactly-one-source
    refusal since the capture path landed, and the weekly stage never set it -- because it
    built the request positionally and the eighth field was never reached. The artifact name
    follows the capture the claims came from, so it has to move with it.
    """

    from squadopt.application.weekly_plan import (
        WeeklyRequest,
        rotation_artifact,
        rotation_source_capture,
    )

    capture = "club-news-abcdef012345"
    decision = "decision-999999999999"
    request = WeeklyRequest(
        season="2026-27", gameweek=5, league_id=1, rotation=True, rotation_capture=capture
    )

    assert request.rotation_capture == capture
    assert rotation_source_capture(decision, capture) == capture
    assert rotation_source_capture(decision, None) == decision

    named, _manifest = rotation_artifact(
        Path("out"), "2026-27", 5, rotation_source_capture(decision, capture)
    )
    from_fixture, _unused = rotation_artifact(
        Path("out"), "2026-27", 5, rotation_source_capture(decision, None)
    )
    assert named != from_fixture
    assert capture[-12:] in named.name


def test_a_capture_without_the_rotation_stage_is_refused() -> None:
    """Naming a source for a step nobody asked for looks like a run and is not one."""

    from squadopt.application.weekly_plan import WeekError, WeeklyRequest

    with pytest.raises(WeekError, match="without --rotation"):
        WeeklyRequest(
            season="2026-27", gameweek=5, league_id=1, rotation_capture="club-news-abc"
        ).plan()


def test_no_capture_keeps_todays_behaviour_exactly() -> None:
    """With no flag the fixture is read and the plan says so, as it always did."""

    from squadopt.application.weekly_plan import WeeklyRequest

    plan = WeeklyRequest(season="2026-27", gameweek=5, league_id=1, rotation=True).plan()

    assert "rotation" in plan.steps
    assert WeeklyRequest(season="2026-27", gameweek=5, league_id=1).rotation_capture is None
