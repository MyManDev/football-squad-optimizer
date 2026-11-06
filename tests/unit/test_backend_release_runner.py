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
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_FILES = ROOT / "deploy" / "weekly-schedule"
COMMAND = HOST_FILES / "squadopt-backend-release"
RUN_ID = "2026-27-gw11-tuesday-20261113T0200Z"
TAG = "site-2026-27-gw11-fix1"
COMMIT = "a" * 40
GIT_STEPS = ["git fetch", "git cat-file", "git rev-parse", "git merge-base"]
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
    retained = module.WEEKLY / "data" / "handoffs" / "by-capture" / CAPTURE / HANDOFF
    retained.parent.mkdir(parents=True)
    retained.write_text(json.dumps({"source_snapshot_id": CAPTURE}), encoding="utf-8")
    alias = module.WEEKLY / "data" / "handoffs" / "2026-27-gw11.json"
    alias.write_text('{"source_snapshot_id": "a later run of the week"}', encoding="utf-8")
    rotation = module.WEEKLY / "artifacts" / "rotation"
    rotation.mkdir(parents=True)
    (rotation / ROTATION).write_text('{"table_file": "rotation.csv"}', encoding="utf-8")
    (rotation / "rotation.csv").write_text("player,minutes\n1,90\n", encoding="utf-8", newline="\n")
    (module.WEEKLY / "data" / "snapshots" / NEWS).mkdir()
    if sys.platform == "win32":
        # Windows exercises the orchestration with a plain-file copy stand-in. The host's
        # actual descriptor and link defenses below execute only on POSIX (both CI gates).
        def copy_input(source: Path, target: Path, *, tree: bool = False) -> None:
            if source.is_symlink() or not (source.is_dir() if tree else source.is_file()):
                raise module.Refused("not a plain input")
            target.parent.mkdir(parents=True, exist_ok=True)
            if tree:
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)

        monkeypatch.setattr(module, "copy_input", copy_input)
    return module


PICKS = "fpl-elite-picks-20261113T015500Z-b114c859f532"
HANDOFF = "e" * 64 + ".json"


def _top100(module: ModuleType, names: list[str]) -> None:
    snapshots = module.WEEKLY / "data" / "snapshots"
    for name in names:
        if module.SNAPSHOT.fullmatch(name):
            (snapshots / name).mkdir(parents=True, exist_ok=True)
    manifest = module.WEEKLY / "artifacts" / "phase_b" / TOP100
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"source_snapshot_ids": names, "table_file": "top100.csv"}), encoding="utf-8"
    )
    manifest.with_name("top100.csv").write_text(
        "player,ownership\n1,0.2\n", encoding="utf-8", newline="\n"
    )


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
        "handoff_retained": HANDOFF,
    }
    return {**document, **changes}


class _Host:
    """Every outside command, recorded; the tool's pack prints its report, one step can fail."""

    def __init__(self, command: ModuleType, failing: str = "") -> None:
        self.calls: list[list[str]] = []
        self.command = command
        self.failing = failing
        self.staged: dict[str, bytes] = {}
        self.staging_root: Path | None = None

    def run(self, arguments: Sequence[str]) -> object:
        call = [str(argument) for argument in arguments]
        self.calls.append(call)
        step = call[2] if call[0] == sys.executable else call[0]
        output = json.dumps(PACKED, indent=2) if step == "pack" else ""
        if step == "pack":
            named = dict(zip(call[3::2], call[4::2], strict=False))
            self.staging_root = Path(named["--snapshot-root"]).parent
            if sys.platform != "win32":
                assert stat.S_IMODE(self.staging_root.stat().st_mode) == 0o700
            self.staged = {
                path.relative_to(self.staging_root).as_posix(): path.read_bytes()
                for path in self.staging_root.rglob("*")
                if path.is_file()
            }
        if call[0] == "git" and call[3] == "cat-file":
            output = "tag\n"
        elif call[0] == "git" and call[3] == "rev-parse":
            output = COMMIT + "\n"
        return self.command.Completed(5 if step == self.failing else 0, output)


def _steps(host: _Host) -> list[str]:
    return [
        call[2] if call[0] == sys.executable else f"git {call[3]}" if call[0] == "git" else call[0]
        for call in host.calls
    ]


def test_a_request_takes_exactly_its_shape(command: ModuleType) -> None:
    parsed = command.parse_request(json.dumps(_request()).encode())
    assert (parsed.run_id, parsed.tag, parsed.gameweek, parsed.news) == (RUN_ID, TAG, 11, "")
    assert parsed.retained_handoff == (
        command.WEEKLY / "data" / "handoffs" / "by-capture" / CAPTURE / HANDOFF
    )
    assert parsed.handoff_name == "2026-27-gw11.json"
    refused = [
        _request(tag="site-2026-27-gw11-fix1; rm -rf /"),
        _request(top100_manifest="../../etc/passwd.json"),
        _request(top100_manifest="phase_b/" + TOP100),
        _request(capture="fpl-live-latest"),
        _request(handoff_retained=""),
        _request(handoff_retained="2026-27-gw11.json"),
        _request(handoff_retained="../" + HANDOFF),
        _request(gameweek=True),
        _request(gameweek=39),
        _request(deadline_utc="soon"),
        _request(deadline_utc="2026-11-31T11:00:00Z"),
        _request(deadline_utc="2026-11-21T25:00:00Z"),
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


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
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


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
def test_a_broken_request_link_is_removed_without_blocking_the_queue(command: ModuleType) -> None:
    command.SPOOL.mkdir()
    (command.SPOOL / "broken.json").symlink_to(command.SPOOL / "missing")
    (command.SPOOL / "valid.json").write_bytes(b"valid")
    assert command.take_request(command.SPOOL) == b"valid"
    assert not list(command.SPOOL.iterdir())


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_non_file_requests_are_quarantined_without_reading_or_blocking(
    command: ModuleType, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.SPOOL.mkdir()
    invalid = command.SPOOL / "invalid.json"
    if kind == "directory":
        invalid.mkdir()
        (invalid / "keep.txt").write_bytes(b"keep")
    else:
        os.mkfifo(invalid)
    opened = os.open

    def nonblocking(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path).name == invalid.name:
            assert flags & os.O_NONBLOCK
        return opened(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", nonblocking)
    assert command.take_request(command.SPOOL) is None
    assert not invalid.exists()
    refused = command.SPOOL / "invalid.json.refused"
    assert refused.exists()
    if kind == "directory":
        assert (refused / "keep.txt").read_bytes() == b"keep"


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
def test_a_link_in_a_spool_parent_cannot_read_or_remove_outside_files(
    command: ModuleType, tmp_path: Path
) -> None:
    outside = tmp_path / "outside" / "backend"
    outside.mkdir(parents=True)
    held = outside / "held.json"
    held.write_bytes(b"keep")
    parent = tmp_path / "linked-parent"
    parent.symlink_to(outside.parent, target_is_directory=True)
    with pytest.raises(command.Refused, match="plain directory"):
        command.take_request(parent / "backend")
    assert held.read_bytes() == b"keep"


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
def test_replacing_the_spool_after_open_cannot_redirect_a_read_or_delete(
    command: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.SPOOL.mkdir()
    (command.SPOOL / "request.json").write_bytes(b"request")
    outside = tmp_path / "outside"
    outside.mkdir()
    held = outside / "request.json"
    held.write_bytes(b"keep")
    listdir = os.listdir
    swapped = False

    def replace_before_listing(descriptor: Any) -> list[str]:
        nonlocal swapped
        if isinstance(descriptor, int) and not swapped:
            command.SPOOL.rename(command.SPOOL.with_name("retained-spool"))
            command.SPOOL.symlink_to(outside, target_is_directory=True)
            swapped = True
        return listdir(descriptor)

    monkeypatch.setattr(os, "listdir", replace_before_listing)
    assert command.take_request(command.SPOOL) == b"request"
    assert swapped
    assert held.read_bytes() == b"keep"


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
    assert _steps(host) == [*GIT_STEPS, "pack", "stage", "prepare", "candidate", "activate"]
    fetch, _kind, _commit, _approval, pack, stage, prepare, candidate, activate = host.calls
    assert fetch[-1] == f"refs/tags/{TAG}:refs/tags/{TAG}"
    assert "--force" not in fetch
    assert "refs/heads/main:refs/remotes/origin/main" in fetch
    tool = command.STATE / "tools" / f"{TAG}.py"
    assert tool.read_bytes() == b"# the tool at " + COMMIT.encode()
    assert pack[:3] == [sys.executable, str(tool), "pack"]
    staged = host.staging_root
    assert staged is not None and staged.parent == command.STATE / "inputs"
    named = dict(zip(pack[3::2], pack[4::2], strict=False))
    assert named == {
        "--repo": str(command.REPO),
        "--season": "2026-27",
        "--gameweek": "11",
        "--capture": CAPTURE,
        "--tag": TAG,
        "--snapshot-root": str(staged / "snapshots"),
        "--handoff": str(staged / "handoffs" / "2026-27-gw11.json"),
        "--top100-manifest": str(staged / "artifacts" / "phase_b" / TOP100),
        "--out": str(command.INCOMING),
        "--rotation-manifest": str(staged / "artifacts" / "rotation" / ROTATION),
        "--news-capture": NEWS,
    }
    # pack reads the run's own retained handoff, never the alias a later run rewrote.
    copied = host.staged["handoffs/2026-27-gw11.json"].decode()
    assert CAPTURE in copied
    assert host.staged["artifacts/phase_b/top100.csv"] == b"player,ownership\n1,0.2\n"
    assert host.staged["artifacts/rotation/rotation.csv"] == b"player,minutes\n1,90\n"
    assert not staged.exists()
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


def test_an_unreviewed_tag_stops_before_reading_or_running_the_root_tool(
    command: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _Host(command)

    def run(arguments: Sequence[str]) -> object:
        answer = host.run(arguments)
        if arguments[0] == "git" and arguments[3] == "merge-base":
            return command.Completed(1, "")
        return answer

    def forbidden_source(commit: str) -> bytes:
        pytest.fail("an unreviewed tag must not supply executable code")

    monkeypatch.setattr(command, "tool_source", forbidden_source)
    request = command.parse_request(json.dumps(_request()).encode())
    with pytest.raises(command.Refused, match="protected main"):
        command.move(request, run, EARLY, lambda text: None)
    assert _steps(host) == GIT_STEPS
    assert not (command.STATE / "tools").exists()


def test_release_approval_uses_real_git_ancestry_and_an_annotated_tag(command: ModuleType) -> None:
    command.REPO.mkdir(parents=True)

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(command.REPO), *arguments],
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    (command.REPO / "release.txt").write_text("reviewed", encoding="utf-8")
    git("add", "release.txt")
    git("commit", "-m", "Reviewed release")
    approved = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", approved)
    git("tag", "-a", TAG, "-m", "Release")
    git("checkout", "-b", "unreviewed")
    (command.REPO / "release.txt").write_text("unreviewed", encoding="utf-8")
    git("commit", "-am", "Unreviewed change")
    unreviewed = "site-2026-27-gw11-fix2"
    git("tag", "-a", unreviewed, "-m", "Not released")
    lightweight = "site-2026-27-gw11-fix3"
    git("tag", lightweight, approved)

    def run(arguments: Sequence[str]) -> object:
        completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
        return command.Completed(completed.returncode, completed.stdout)

    assert command.trusted_release_commit(TAG, run) == approved
    with pytest.raises(command.Refused, match="protected main"):
        command.trusted_release_commit(unreviewed, run)
    with pytest.raises(command.Refused, match="annotated"):
        command.trusted_release_commit(lightweight, run)


@pytest.mark.parametrize(
    ("failing", "ran", "line"),
    [
        ("pack", [*GIT_STEPS, "pack"], "stopped: pack exited 5; nothing was staged"),
        (
            "prepare",
            [*GIT_STEPS, "pack", "stage", "prepare"],
            "stopped: prepare exited 5; the live backend was not touched",
        ),
        (
            "candidate",
            [*GIT_STEPS, "pack", "stage", "prepare", "candidate"],
            "stopped: candidate exited 5; the live backend was not touched",
        ),
        (
            "activate",
            [*GIT_STEPS, "pack", "stage", "prepare", "candidate", "activate"],
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


def test_prune_cannot_delete_the_backend_base_through_a_parent_component(
    command: ModuleType,
) -> None:
    builds = command.BASE / "build"
    builds.mkdir()
    held = command.BASE / "keep.txt"
    held.write_text("backend state", encoding="utf-8")
    for day in range(1, 5):
        build = str(builds / "..") if day == 1 else ""
        _release(command, f"gw11-r{day}", f"2026-11-1{day}T04:00:00Z", build)
    host = _Host(command)
    command.prune("gw11-r4", host.run, lambda text: None)
    assert held.read_text(encoding="utf-8") == "backend state"
    assert (command.RELEASES / "gw11-r4").is_dir()


def test_the_command_refuses_a_user_who_is_not_root(
    command: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 999, raising=False)
    assert command.main() == 2
    assert "Refused: run as root" in capsys.readouterr().err


@pytest.mark.skipif(
    sys.platform == "win32", reason="the host spool uses POSIX directory descriptors"
)
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
    manifest.write_text(
        json.dumps({"source_snapshot_ids": names, "table_file": "top100.csv"}), encoding="utf-8"
    )
    host = _Host(command)
    request = command.parse_request(json.dumps(_request()).encode())
    with pytest.raises(command.Refused):
        command.move(request, host.run, EARLY, lambda text: None)
    assert _steps(host) == GIT_STEPS


def test_pack_is_refused_a_named_capture_that_is_not_on_disk(command: ModuleType) -> None:
    manifest = command.WEEKLY / "artifacts" / "phase_b" / TOP100
    missing = "fpl-top100-20261113T015000Z-59306b9ebd52"
    manifest.write_text(json.dumps({"source_snapshot_ids": [CAPTURE, missing]}), encoding="utf-8")
    with pytest.raises(command.Refused, match="not a plain directory"):
        command.check_captures(manifest, command.WEEKLY / "data" / "snapshots")


def test_pack_is_refused_a_retained_handoff_that_is_not_on_disk(command: ModuleType) -> None:
    host = _Host(command)
    request = command.parse_request(
        json.dumps(_request(handoff_retained="f" * 64 + ".json")).encode()
    )
    with pytest.raises(command.Refused, match="retained handoff"):
        command.move(request, host.run, EARLY, lambda text: None)
    assert _steps(host) == GIT_STEPS


@pytest.mark.parametrize("table", ["../outside.csv", "/outside.csv", "nested/table.csv", 7])
def test_a_manifest_cannot_name_a_table_outside_its_directory(
    command: ModuleType, table: object
) -> None:
    manifest = command.WEEKLY / "artifacts" / "phase_b" / TOP100
    manifest.write_text(json.dumps({"source_snapshot_ids": [CAPTURE], "table_file": table}))
    host = _Host(command)
    with pytest.raises(command.Refused, match="unsafe table"):
        command.move(command.parse_request(json.dumps(_request()).encode()), host.run, EARLY, print)
    assert _steps(host) == GIT_STEPS
    assert not list((command.STATE / "inputs").iterdir())


def test_pack_uses_the_manifest_copy_even_if_the_original_changes(
    command: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = command.copy_input

    def changed_after_copy(source: Path, target: Path, *, tree: bool = False) -> None:
        copy(source, target, tree=tree)
        if source.name == TOP100:
            source.write_text('{"table_file": "../outside.csv", "source_snapshot_ids": ["../"]}')

    monkeypatch.setattr(command, "copy_input", changed_after_copy)
    host = _Host(command)
    request = command.parse_request(json.dumps(_request()).encode())
    assert command.move(request, host.run, EARLY, print) == 0
    manifest = json.loads(host.staged[f"artifacts/phase_b/{TOP100}"])
    assert manifest["table_file"] == "top100.csv"
    assert manifest["source_snapshot_ids"] == [CAPTURE, PICKS]


@pytest.mark.skipif(sys.platform == "win32", reason="the host reads POSIX directory descriptors")
@pytest.mark.parametrize("kind", ["symlink", "directory-link", "fifo", "hardlink"])
def test_input_copy_refuses_links_and_special_files_without_reading_them(
    command: ModuleType, tmp_path: Path, kind: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "private.txt"
    secret.write_bytes(b"must not be copied")
    bad = source / "bad"
    if kind == "symlink":
        bad.symlink_to(secret)
    elif kind == "directory-link":
        bad.symlink_to(outside, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(bad)
    else:
        os.link(secret, bad)
    target = tmp_path / "copied"
    with pytest.raises(command.Refused):
        command.copy_input(source, target, tree=True)
    assert not (target / "bad").exists()
    assert secret.read_bytes() == b"must not be copied"


@pytest.mark.skipif(sys.platform == "win32", reason="the host reads POSIX directory descriptors")
def test_input_copy_refuses_a_link_in_any_parent(command: ModuleType, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_bytes(b"must not be copied")
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    target = tmp_path / "copied"
    with pytest.raises(command.Refused):
        command.copy_input(linked / "private.txt", target)
    assert not target.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the host reads POSIX directory descriptors")
def test_swapping_a_capture_after_open_cannot_redirect_its_files(
    command: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "capture"
    source.mkdir()
    (source / "payload.json").write_bytes(b"public capture")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.json").write_bytes(b"must not be copied")
    listdir = os.listdir
    swapped = False

    def replace_before_listing(descriptor: Any) -> list[str]:
        nonlocal swapped
        if isinstance(descriptor, int) and not swapped:
            source.rename(tmp_path / "old-capture")
            source.symlink_to(outside, target_is_directory=True)
            swapped = True
        return listdir(descriptor)

    monkeypatch.setattr(os, "listdir", replace_before_listing)
    target = tmp_path / "copied"
    command.copy_input(source, target, tree=True)
    assert swapped
    assert (target / "payload.json").read_bytes() == b"public capture"


@pytest.mark.skipif(sys.platform == "win32", reason="the host reads POSIX directory descriptors")
def test_swapping_a_file_after_stat_cannot_redirect_its_read(
    command: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "capture"
    source.mkdir()
    payload = source / "payload.json"
    payload.write_bytes(b"public capture")
    secret = tmp_path / "private.txt"
    secret.write_bytes(b"must not be copied")
    original_stat = os.stat
    swapped = False

    def replace_after_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        result = original_stat(path, *args, **kwargs)
        if path == "payload.json" and kwargs.get("dir_fd") is not None and not swapped:
            payload.unlink()
            payload.symlink_to(secret)
            swapped = True
        return result

    monkeypatch.setattr(os, "stat", replace_after_stat)
    target = tmp_path / "copied"
    with pytest.raises(command.Refused):
        command.copy_input(source, target, tree=True)
    assert swapped
    assert not (target / "payload.json").exists()
