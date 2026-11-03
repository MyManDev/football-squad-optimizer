"""`squadopt-backend-release`, root's half of the backend following every release (#1243).

The command takes one request the release chain left in the spool and runs the five steps of
`scripts/release/vm_football_release.py` on the schedule's host. These tests load it from
`deploy/weekly-schedule` and run it on scratch directories, with every outside command recorded
instead of run: what a request may name and what it is refused for, the order of the steps and
the stop at the first that fails, the advice job only while the deadline is ahead, the prune
that keeps the live release and the two before it, and one move per run. Nothing here builds an
image, starts a container or reads GitHub.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_FILES = ROOT / "deploy" / "weekly-schedule"
COMMAND = HOST_FILES / "squadopt-backend-release"
RUN_ID = "2026-27-gw11-tuesday-20261113T0200Z"
TAG = "site-2026-27-gw11-fix1"
CAPTURE = "fpl-live-20261113T020000Z-0123456789ab"
NEWS = "club-news-20261121T065000Z-ba9876543210"
TOP100 = "player_evidence_v1_2026-27_gw11_top100_cc.manifest.json"
ROTATION = "rotation_evidence_v4_2026-27_gw11_aa_decision_bb.manifest.json"
EARLY = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)
LATE = datetime(2026, 11, 21, 10, 50, tzinfo=UTC)
PACKED = {
    "stage": "packed",
    "name": "gw11-fix1-0123456789ab-20261113t0430z",
    "files": 1790,
    "football": False,
    "news_capture": None,
    "rotation_table": None,
    "tarball": "/root/squadopt/incoming/gw11-fix1-0123456789ab-20261113t0430z.tar.gz",
    "tarball_bytes": 1,
    "tarball_sha256": "f" * 64,
}


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("squadopt_backend_release", str(COMMAND))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass reads its module's globals while it is made, so the module is registered first.
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The command with its four places on scratch directories, and the tool's source read."""

    module = _load()
    base = tmp_path / "root" / "squadopt"
    for name, value in (
        ("WEEKLY", tmp_path / "weekly"),
        ("SPOOL", tmp_path / "spool"),
        ("STATE", tmp_path / "state"),
        ("BASE", base),
        ("REPO", base / "repo"),
        ("RELEASES", base / "releases"),
        ("INCOMING", base / "incoming"),
    ):
        monkeypatch.setattr(module, name, value)
    (base / "releases").mkdir(parents=True)
    monkeypatch.setattr(module, "tool_source", lambda tag: b"# the tool at " + tag.encode())
    _top100(module, [CAPTURE, PICKS])
    return module


PICKS = "fpl-elite-picks-20261113T015500Z-b114c859f532"


def _top100(module: ModuleType, names: list[str]) -> None:
    snapshots = module.WEEKLY / "data" / "snapshots"
    for name in names:
        if module.SNAPSHOT.fullmatch(name):
            (snapshots / name).mkdir(parents=True, exist_ok=True)
    manifest = module.WEEKLY / "artifacts" / "phase_b" / TOP100
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"source_snapshot_ids": names}), encoding="utf-8")


def _request(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "run_id": RUN_ID,
        "tag": TAG,
        "season": "2026-27",
        "gameweek": 11,
        "capture": CAPTURE,
        "deadline_utc": "2026-11-21T11:00:00Z",
        "top100_manifest": TOP100,
        "news": "",
        "rotation_manifest": "",
    }
    return {**document, **changes}


class _Host:
    """Every outside command, recorded; the tool's pack prints its report, one step can fail."""

    def __init__(self, command: ModuleType, failing: str = "") -> None:
        self.calls: list[list[str]] = []
        self.command = command
        self.failing = failing

    def run(self, arguments: Sequence[str]) -> object:
        call = [str(argument) for argument in arguments]
        self.calls.append(call)
        step = call[2] if call[0] == sys.executable else call[0]
        output = json.dumps(PACKED, indent=2) if step == "pack" else ""
        return self.command.Completed(5 if step == self.failing else 0, output)


def _steps(host: _Host) -> list[str]:
    return [call[2] if call[0] == sys.executable else " ".join(call[:2]) for call in host.calls]


def test_a_request_takes_exactly_its_shape(command: ModuleType) -> None:
    parsed = command.parse_request(json.dumps(_request()).encode())
    assert (parsed.run_id, parsed.tag, parsed.gameweek, parsed.news) == (RUN_ID, TAG, 11, "")
    assert parsed.handoff == command.WEEKLY / "data" / "handoffs" / "2026-27-gw11.json"
    refused = [
        _request(tag="site-2026-27-gw11-fix1; rm -rf /"),
        _request(top100_manifest="../../etc/passwd.json"),
        _request(top100_manifest="phase_b/" + TOP100),
        _request(capture="fpl-live-latest"),
        _request(gameweek=True),
        _request(gameweek=39),
        _request(deadline_utc="soon"),
        _request(news=NEWS),
        _request(rotation_manifest=ROTATION),
        _request(run_id="-rf"),
    ]
    for document in refused:
        with pytest.raises(command.Refused):
            command.parse_request(json.dumps(document).encode())
    with_news = command.parse_request(
        json.dumps(_request(news=NEWS, rotation_manifest=ROTATION)).encode()
    )
    assert (with_news.news, with_news.rotation_manifest) == (NEWS, ROTATION)
    for raw in (b"not json", b"[1]", "{}".encode("utf-16")):
        with pytest.raises(command.Refused):
            command.parse_request(raw)


def test_the_oldest_request_is_taken_and_removed(command: ModuleType) -> None:
    spool = command.SPOOL
    spool.mkdir()
    (spool / "b.json").write_text("second", encoding="utf-8")
    (spool / "a.json.partial").write_text("half", encoding="utf-8")
    os.utime(spool / "b.json", (2_000_000_000, 2_000_000_000))
    (spool / "a.json").write_text("first", encoding="utf-8")
    os.utime(spool / "a.json", (1_000_000_000, 1_000_000_000))
    assert command.take_request(spool) == b"first"
    assert command.take_request(spool) == b"second"
    assert command.take_request(spool) is None
    assert [path.name for path in spool.iterdir()] == ["a.json.partial"]


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs privileges on Windows")
def test_a_request_that_is_a_link_is_never_followed(command: ModuleType, tmp_path: Path) -> None:
    command.SPOOL.mkdir()
    secret = tmp_path / "shadow"
    secret.write_text("root's", encoding="utf-8")
    (command.SPOOL / "x.json").symlink_to(secret)
    assert command.take_request(command.SPOOL) is None
    assert secret.read_text(encoding="utf-8") == "root's"
    assert not list(command.SPOOL.iterdir())


def test_the_advice_job_runs_only_while_the_deadline_is_ahead(command: ModuleType) -> None:
    assert command.with_jobs("2026-11-21T11:00:00Z", EARLY) is True
    assert command.with_jobs("2026-11-21T11:00:00Z", LATE) is False
    assert command.with_jobs("2026-11-21T11:00:00Z", datetime(2026, 11, 22, tzinfo=UTC)) is False


def test_the_five_steps_run_in_order_from_the_tag_and_the_checkouts_files(
    command: ModuleType,
) -> None:
    host = _Host(command)
    said: list[str] = []
    request = command.parse_request(
        json.dumps(_request(news=NEWS, rotation_manifest=ROTATION)).encode()
    )
    assert command.move(request, host.run, EARLY, said.append) == 0
    assert _steps(host) == ["git -C", "pack", "stage", "prepare", "candidate", "activate"]
    fetch, pack, stage, prepare, candidate, activate = host.calls
    assert fetch[-1] == f"refs/tags/{TAG}:refs/tags/{TAG}"
    tool = command.STATE / "tools" / f"{TAG}.py"
    assert tool.read_bytes() == b"# the tool at " + TAG.encode()
    assert pack[:3] == [sys.executable, str(tool), "pack"]
    weekly = command.WEEKLY
    named = dict(zip(pack[3::2], pack[4::2], strict=False))
    assert named == {
        "--repo": str(command.REPO),
        "--season": "2026-27",
        "--gameweek": "11",
        "--capture": CAPTURE,
        "--tag": TAG,
        "--snapshot-root": str(weekly / "data" / "snapshots"),
        "--handoff": str(weekly / "data" / "handoffs" / "2026-27-gw11.json"),
        "--top100-manifest": str(weekly / "artifacts" / "phase_b" / TOP100),
        "--out": str(command.INCOMING),
        "--rotation-manifest": str(weekly / "artifacts" / "rotation" / ROTATION),
        "--news-capture": NEWS,
    }
    assert stage[3:] == ["--tarball", PACKED["tarball"], "--sha256", PACKED["tarball_sha256"]]
    name = str(PACKED["name"])
    assert prepare[3:] == ["--release", name]
    assert candidate[3:] == activate[3:] == ["--release", name]
    assert said == [
        f"packed {name}: 1790 files, football False",
        "prepare: done",
        "candidate: done",
        "activate: done",
        f"live: the backend serves {name}",
    ]


def test_after_the_deadline_the_candidate_and_activation_run_no_advice_job(
    command: ModuleType,
) -> None:
    host = _Host(command)
    request = command.parse_request(json.dumps(_request()).encode())
    assert command.move(request, host.run, LATE, lambda text: None) == 0
    *_, prepare, candidate, activate = host.calls
    assert "--no-jobs" not in prepare
    assert candidate[-1] == activate[-1] == "--no-jobs"


@pytest.mark.parametrize(
    ("failing", "ran", "line"),
    [
        ("pack", ["git -C", "pack"], "stopped: pack exited 5; nothing was staged"),
        (
            "prepare",
            ["git -C", "pack", "stage", "prepare"],
            "stopped: prepare exited 5; the live backend was not touched",
        ),
        (
            "candidate",
            ["git -C", "pack", "stage", "prepare", "candidate"],
            "stopped: candidate exited 5; the live backend was not touched",
        ),
        (
            "activate",
            ["git -C", "pack", "stage", "prepare", "candidate", "activate"],
            "stopped: activate exited 5; activate restored the kept configuration",
        ),
    ],
)
def test_the_first_step_that_fails_stops_the_move(
    command: ModuleType, failing: str, ran: list[str], line: str
) -> None:
    host = _Host(command, failing)
    said: list[str] = []
    request = command.parse_request(json.dumps(_request()).encode())
    assert command.move(request, host.run, EARLY, said.append) == 5
    assert (_steps(host), said[-1]) == (ran, line)


def _release(command: ModuleType, name: str, created: str, build: str = "") -> Path:
    path = command.RELEASES / name
    path.mkdir()
    (path / "package.json").write_text(json.dumps({"created_at": created}), encoding="utf-8")
    image = {"image": f"squadopt-backend:{name}", "build_dir": build} if build else {}
    (path / "image.json").write_text(json.dumps(image), encoding="utf-8")
    return path


def test_the_prune_keeps_the_live_release_and_the_two_packed_before_it(
    command: ModuleType,
) -> None:
    builds = command.BASE / "build"
    for day in range(1, 6):
        (builds / f"tag{day}").mkdir(parents=True)
        _release(command, f"gw11-r{day}", f"2026-11-1{day}T04:00:00Z", str(builds / f"tag{day}"))
    (command.RELEASES / "undated").mkdir()
    host = _Host(command)
    said: list[str] = []
    command.prune("gw11-r5", host.run, said.append)
    kept = sorted(path.name for path in command.RELEASES.iterdir())
    assert kept == ["gw11-r3", "gw11-r4", "gw11-r5", "undated"]
    assert host.calls == [
        ["docker", "image", "rm", "squadopt-backend:gw11-r1"],
        ["docker", "image", "rm", "squadopt-backend:gw11-r2"],
    ]
    assert sorted(path.name for path in builds.iterdir()) == ["tag3", "tag4", "tag5"]
    assert said == [
        "pruned gw11-r1 and image squadopt-backend:gw11-r1",
        "pruned gw11-r2 and image squadopt-backend:gw11-r2",
    ]


def test_the_command_refuses_a_user_who_is_not_root(
    command: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 999, raising=False)
    assert command.main() == 2
    assert "Refused: run as root" in capsys.readouterr().err


def test_a_run_is_moved_once_and_its_result_is_left_for_the_chain(
    command: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    host = _Host(command)
    monkeypatch.setattr(command, "run_command", lambda log: host.run)
    command.SPOOL.mkdir()
    (command.SPOOL / f"{RUN_ID}.json").write_text(json.dumps(_request()), encoding="utf-8")
    assert command.main(now=lambda: EARLY) == 0
    result = json.loads((command.STATE / f"{RUN_ID}.result.json").read_text(encoding="utf-8"))
    assert (result["run_id"], result["tag"], result["code"]) == (RUN_ID, TAG, 0)
    assert result["lines"][0] == f"backend: run {RUN_ID}: moving to {TAG}, capture {CAPTURE}"
    assert result["lines"][-1].startswith("backend: live: the backend serves ")
    assert not list(command.SPOOL.iterdir())
    host.calls.clear()
    (command.SPOOL / f"{RUN_ID}.json").write_text(json.dumps(_request()), encoding="utf-8")
    assert command.main(now=lambda: EARLY) == 2
    assert host.calls == []
    assert f"Refused: {RUN_ID} was moved before" in capsys.readouterr().err
    assert command.main() == 0  # an empty spool: nothing to do


def test_the_units_start_the_command_from_the_spool_as_root() -> None:
    path = (HOST_FILES / "squadopt-backend-release.path").read_text(encoding="utf-8")
    service = (HOST_FILES / "squadopt-backend-release.service").read_text(encoding="utf-8")
    assert "PathExistsGlob=/srv/squadopt/spool/backend/*.json" in path.splitlines()
    assert "Unit=squadopt-backend-release.service" in path.splitlines()
    lines = service.splitlines()
    assert "ExecStart=/usr/local/sbin/squadopt-backend-release" in lines
    assert not [line for line in lines if line.startswith(("User=", "Group="))]
    assert "Type=oneshot" in lines and "Requires=docker.service" in lines
    module = _load()
    assert (
        Path("/srv/squadopt/spool/backend"),
        Path("/var/lib/squadopt/backend"),
    ) == (module.SPOOL, module.STATE)


def test_the_chain_and_the_command_name_the_same_spool_and_state() -> None:
    from squadopt.platform import weekly_release

    module = _load()
    assert (weekly_release.BACKEND_SPOOL, weekly_release.BACKEND_STATE) == (
        module.SPOOL,
        module.STATE,
    )
    assert weekly_release.RUN_ID.pattern == module.RUN_ID.pattern


def test_the_new_files_hold_no_long_dash() -> None:
    for name in (
        "squadopt-backend-release",
        "squadopt-backend-release.path",
        "squadopt-backend-release.service",
    ):
        text = (HOST_FILES / name).read_text(encoding="utf-8")
        assert not {chr(0x2013), chr(0x2014)} & set(text), name


@pytest.mark.parametrize(
    "names",
    [["../../../root"], [CAPTURE, "fpl-live-latest"], [], "fpl-live", [CAPTURE, 7]],
    ids=["traversal", "unshaped", "none", "not-a-list", "not-a-name"],
)
def test_pack_is_refused_a_top100_manifest_naming_a_capture_it_should_not_copy(
    command: ModuleType, names: object
) -> None:
    manifest = command.WEEKLY / "artifacts" / "phase_b" / TOP100
    manifest.write_text(json.dumps({"source_snapshot_ids": names}), encoding="utf-8")
    host = _Host(command)
    request = command.parse_request(json.dumps(_request()).encode())
    with pytest.raises(command.Refused):
        command.move(request, host.run, EARLY, lambda text: None)
    assert _steps(host) == ["git -C"]


def test_pack_is_refused_a_named_capture_that_is_not_on_disk(command: ModuleType) -> None:
    manifest = command.WEEKLY / "artifacts" / "phase_b" / TOP100
    missing = "fpl-top100-20261113T015000Z-59306b9ebd52"
    manifest.write_text(json.dumps({"source_snapshot_ids": [CAPTURE, missing]}), encoding="utf-8")
    with pytest.raises(command.Refused, match="not a plain directory"):
        command.check_captures(manifest, command.WEEKLY / "data" / "snapshots")
