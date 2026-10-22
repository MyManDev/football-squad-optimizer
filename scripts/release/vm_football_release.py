"""Move one gameweek's backend inputs to the VM as an immutable release, then switch to it.

The backend VM does not read the folders ``scripts/vm_push.sh`` writes. Since GW7 its two
Compose services mount one prepared release directory under ``~/squadopt/releases/<name>``:
the four data roots (artifacts, handoffs, captures, site data) and the club-news source. A
plain ``vm_push.sh`` rebuilds the image and restarts on the previous release's mounts, so the
backend keeps serving last week's capture while the command reports success. This script is
the release path for that layout, in five steps:

  pack       (PC)  copy the week's inputs into a package directory with a sha256 manifest
  push       (PC)  stream the package and this file to the VM, unpack, verify every byte
  prepare    (VM)  build the image for the release tag, then, when the package carries a
                   football forecast, re-render it on Linux and seal the bundle there
  candidate  (VM)  start a second Compose project on other ports with the new mounts and a
                   scratch store, check readiness, capabilities and real advice jobs, stop it
  activate   (VM)  keep the live configuration as the rollback, point the live project at
                   the new release, restart, check the same things, roll back on failure

``rollback`` restores the configuration ``activate`` kept. ``status`` prints what the live
project mounts and serves. The PC runs the VM steps through ``remote``:

  python scripts/release/vm_football_release.py remote prepare --release <name>

Why the football forecast is re-rendered on the VM: the composite basis reproduces its served
result when it loads (``squadopt.live.football_composite_basis``), and a forecast rendered on
Windows differs from the Linux rendering in the last bits of some floats, so the Linux
backend refuses it ("Composite retained recipe does not reproduce every served row and
receipt"). The fitted models live inside the retained recipe, so no model is fitted again:
the production builder renders the documents from the recipe inside the release image, the
difference from the Windows documents is bounded and limited to derived values, and the
production publisher and sealer write the bundle. This is the GW7 procedure made general.

A package without a football forecast is valid: the backend then serves the current model,
the Top 100 settings and, with a club-news capture and its rotation table, the manager's
word. Nothing here prints the environment file's values or any secret.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

PACKAGE_VERSION = "vm_football_release_package_v1"
ROOTS = ("artifact_root", "handoff_root", "snapshot_root", "site_data_root")
VM_HOST = os.environ.get("SQUADOPT_VM_HOST", "squadopt@74.248.153.181")
VM_KEY = os.environ.get("SQUADOPT_VM_KEY", str(Path.home() / ".ssh" / "squadopt_azure"))
VM_SCRIPT = "vm_football_release.py"
LEAGUE_ID = 352490
PROBE_ENTRY = 313686
CANDIDATE_API_PORT = 8001
CANDIDATE_METRICS_PORT = 9191
HEX = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,80}")

# Only derived numerical results may differ between the Windows and the Linux rendering;
# every source identity stays exact. The paths are the ones the GW7 Linux rebuild measured.
MAX_ABSOLUTE_DRIFT = 1e-12
DERIVED_HASH_PATHS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:forecast|components)/fingerprint",
        r"components/forecast_fingerprint",
        r"(?:forecast|components)/composite_metadata/fixture_receipts_sha256",
        r"(?:forecast|components)/composite_metadata/weekly_laws/[0-9]+/sha256",
        r"components/rows/[0-9]+/composite_final_week_law_sha256",
        r"components/fixture_receipts/[0-9]+/(?:input_sha256|final_rows_sha256)",
        r"components/fixture_receipts/[0-9]+/final_week_laws/[0-9]+/1",
        r"components/fixture_receipts/[0-9]+/stages/[0-9]+/(?:input_sha256|result_sha256)",
        r"components/weekly_result/receipts/[0-9]+/"
        r"(?:before_evidence_sha256|final_sha256|load_result_sha256)",
        r"components/weekly_result/laws/[0-9]+/lineage/[0-9]+/parents/1",
    )
)
DERIVED_ROW_FIELDS = (
    r"appearance_probability|expected_minutes|expected_minutes_if_appearance|expected_points|"
    r"goals|assists|goals_share|assists_share|clean_sheet_probability|defcon_probability|"
    r"team_goal_rate|opponent_goal_rate|raw_expected_points|p60|zero_probability|"
    r"start_probability|cameo_probability|score_survival_[0-6]|"
    r"(?:start|cameo)_minute_probability_[1-3]|minute_probability_[0-3]|minute_value_[0-3]"
)
DERIVED_FLOAT_PATHS = tuple(
    re.compile(pattern)
    for pattern in (
        r"forecast/rows/[0-9]+/(?:expected_points|appearance_probability)",
        r"(?:forecast|components)/composite_metadata/weekly_laws/[0-9]+/appearance_probability",
        r"components/rows/[0-9]+/(?:" + DERIVED_ROW_FIELDS + r")",
        r"components/weekly_result/laws/[0-9]+/probabilities/[0-9]+",
        r"components/weekly_result/laws/[0-9]+/fixtures/[0-9]+/probabilities/[0-6]",
    )
)


class ReleaseError(RuntimeError):
    """A step refused; the message says why and nothing was switched."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(*command: str, timeout: float = 600, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        list(command), capture_output=capture, text=True, timeout=timeout, check=False
    )
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-3:] if capture else []
        raise ReleaseError(
            f"{command[0]} {command[1] if len(command) > 1 else ''} failed "
            f"({result.returncode}): {' | '.join(detail)}"
        )
    return result.stdout if capture else ""


# --------------------------------------------------------------------------------------
# PC side: pack and push.
# --------------------------------------------------------------------------------------


def _copy_file(source: Path, target: Path) -> None:
    require(source.is_file() and not source.is_symlink(), f"Not a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _copy_tree(source: Path, target: Path) -> None:
    require(source.is_dir() and not source.is_symlink(), f"Not a directory: {source}")
    for path in sorted(source.rglob("*")):
        require(not path.is_symlink(), f"Symlink in input: {path}")
        if path.is_file():
            _copy_file(path, target / path.relative_to(source))


def _paired_manifest(manifest: Path) -> tuple[Path, dict[str, Any]]:
    """A table manifest names its CSV; the pair travels together or not at all."""
    document = read_json(manifest)
    table = manifest.with_name(document["table_file"])
    require(table.is_file(), f"{manifest.name} names a missing table {table.name}")
    require(
        sha256_file(table) == document["table_sha256"], f"{table.name} differs from its manifest"
    )
    return table, document


def _site_from_tag(repo: Path, tag: str, target: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", tag, "web/public/data"],
        capture_output=True,
        check=False,
    )
    require(archive.returncode == 0, f"git archive {tag} web/public/data failed")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            relative = PurePosixPath(member.name).relative_to("web/public/data")
            extracted = bundle.extractfile(member)
            require(extracted is not None, f"Unreadable archive member {member.name}")
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(extracted.read())


def _inventory(package: Path) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted((package / "payload").rglob("*")):
        require(not path.is_symlink(), f"Symlink in package: {path}")
        if path.is_file():
            relative = path.relative_to(package).as_posix()
            files[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    require(len({name.casefold() for name in files}) == len(files), "Case-colliding members")
    return files


def command_pack(args: argparse.Namespace) -> None:
    repo = Path(args.repo).resolve()
    capture = args.capture
    gameweek = args.gameweek
    tag_commit = run("git", "-C", str(repo), "rev-parse", f"{args.tag}^{{commit}}").strip()
    name = args.name or "gw{:02d}-{}-{}-{}".format(
        gameweek,
        args.tag.rsplit("-", 1)[-1],
        capture.rsplit("-", 1)[-1],
        datetime.now(UTC).strftime("%Y%m%dT%H%MZ").lower(),
    )
    require(NAME.fullmatch(name), f"Release name {name!r} is not a safe directory name")
    out = Path(args.out).resolve()
    final = out / name
    tarball = out / f"{name}.tar.gz"
    require(
        not final.exists() and not tarball.exists(), f"{final} exists; packages are never rewritten"
    )
    # Built aside and renamed at the end, so a refusal never leaves a package-shaped directory.
    package = out / f".{name}.partial"
    if package.exists():
        shutil.rmtree(package)
    payload = package / "payload"
    for root in ROOTS:
        (payload / root).mkdir(parents=True)

    snapshots = Path(args.snapshot_root).resolve()
    top100_table, top100 = _paired_manifest(Path(args.top100_manifest).resolve())
    require(
        str(top100.get("target_gameweek")) == str(gameweek),
        "The Top 100 table is for another gameweek",
    )
    captures = {capture, *top100["source_snapshot_ids"]}
    news = args.news_capture
    rotation_name = None
    if args.rotation_manifest:
        rotation_table, rotation = _paired_manifest(Path(args.rotation_manifest).resolve())
        require(
            str(rotation.get("target_gameweek")) == str(gameweek),
            "The rotation table is for another gameweek",
        )
        require(news is not None, "A rotation table needs the club-news capture it was coded from")
        require(
            rotation.get("club_news_snapshot_id") == news,
            "The rotation table was not coded from the named club-news capture",
        )
        require(
            rotation.get("roster_snapshot_id") == capture,
            "The rotation table was coded against another decision capture",
        )
        _copy_file(rotation_table, payload / "artifact_root" / "rotation" / rotation_table.name)
        _copy_file(
            Path(args.rotation_manifest),
            payload / "artifact_root" / "rotation" / Path(args.rotation_manifest).name,
        )
        rotation_name = rotation_table.name
    if news:
        captures.add(news)
    for snapshot_id in sorted(captures):
        _copy_tree(snapshots / snapshot_id, payload / "snapshot_root" / snapshot_id)

    _copy_file(top100_table, payload / "artifact_root" / "phase_b" / top100_table.name)
    _copy_file(
        Path(args.top100_manifest),
        payload / "artifact_root" / "phase_b" / Path(args.top100_manifest).name,
    )

    handoff = Path(args.handoff).resolve()
    require(
        handoff.name == f"{args.season}-gw{gameweek:02d}.json",
        f"Handoff {handoff.name} is not {args.season}-gw{gameweek:02d}.json",
    )
    _copy_file(handoff, payload / "handoff_root" / handoff.name)

    if args.site_data:
        _copy_tree(Path(args.site_data).resolve(), payload / "site_data_root")
    else:
        _site_from_tag(repo, args.tag, payload / "site_data_root")
    require(
        (payload / "site_data_root" / "leagues.json").is_file()
        or (payload / "site_data_root" / "index.json").is_file(),
        "Site data tree is empty",
    )

    football = False
    if args.windows_forecast_dir:
        source = Path(args.windows_forecast_dir).resolve()
        for suffix in (".json", ".components.json"):
            _copy_file(
                source / f"{capture}{suffix}", payload / "windows_forecast" / f"{capture}{suffix}"
            )
        football = True
    if not news:
        # The release's own fixture, not the working tree's: the backend serves the tag.
        fixture = subprocess.run(
            ["git", "-C", str(repo), "show", f"{tag_commit}:data/sample/club_news_v1.fixture.json"],
            capture_output=True,
            check=False,
        )
        require(fixture.returncode == 0, "The release tag holds no club-news fixture")
        (payload / "club_news_fixture.json").write_bytes(fixture.stdout)

    manifest = {
        "version": PACKAGE_VERSION,
        "name": name,
        "created_at": now(),
        "season": args.season,
        "gameweek": gameweek,
        "league_id": args.league,
        "capture": capture,
        "captures": sorted(captures),
        "tag": args.tag,
        "tag_commit": tag_commit,
        "handoff": handoff.name,
        "top100_table": top100_table.name,
        "rotation_table": rotation_name,
        "news_capture": news,
        "football": football,
        "files": _inventory(package),
    }
    write_json_new(package / "package.json", manifest)
    package.rename(final)

    def normalise(member: tarfile.TarInfo) -> tarfile.TarInfo:
        member.uid = member.gid = 0
        member.uname = member.gname = ""
        member.mode = 0o755 if member.isdir() else 0o644
        return member

    with tarfile.open(tarball, "w:gz", compresslevel=6) as bundle:
        bundle.add(final, arcname=name, filter=normalise)
    print(
        json.dumps(
            {
                "stage": "packed",
                "name": name,
                "files": len(manifest["files"]),
                "football": football,
                "news_capture": news,
                "rotation_table": rotation_name,
                "tarball": str(tarball),
                "tarball_bytes": tarball.stat().st_size,
                "tarball_sha256": sha256_file(tarball),
            },
            indent=2,
        )
    )


def _ssh(*remote: str, timeout: float = 3600) -> None:
    command = [
        "ssh",
        "-i",
        VM_KEY,
        "-o",
        "BatchMode=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=8",
        VM_HOST,
        *remote,
    ]
    result = subprocess.run(command, timeout=timeout, check=False)
    require(result.returncode == 0, f"Remote step failed ({result.returncode}): {' '.join(remote)}")


def _scp(source: Path, target: str) -> None:
    result = subprocess.run(
        ["scp", "-q", "-i", VM_KEY, "-o", "BatchMode=yes", str(source), f"{VM_HOST}:{target}"],
        timeout=3600,
        check=False,
    )
    require(result.returncode == 0, f"Copy to the VM failed: {source.name}")


def command_push(args: argparse.Namespace) -> None:
    tarball = Path(args.tarball).resolve()
    require(tarball.name.endswith(".tar.gz"), "Push takes the .tar.gz that pack wrote")
    _scp(Path(__file__).resolve(), VM_SCRIPT)
    _ssh("mkdir", "-p", "squadopt/incoming")
    _scp(tarball, f"squadopt/incoming/{tarball.name}")
    _ssh(
        "python3",
        VM_SCRIPT,
        "stage",
        "--tarball",
        f"squadopt/incoming/{tarball.name}",
        "--sha256",
        sha256_file(tarball),
    )


def command_remote(args: argparse.Namespace) -> None:
    _scp(Path(__file__).resolve(), VM_SCRIPT)
    _ssh("python3", VM_SCRIPT, *args.rest)


# --------------------------------------------------------------------------------------
# VM side.
# --------------------------------------------------------------------------------------

BASE = Path.home() / "squadopt"
RELEASES = BASE / "releases"
LIVE_ENV = BASE / ".env"
LIVE_OVERRIDE = BASE / "compose.artifacts.yaml"
REPO = BASE / "repo"


def _release(name: str) -> tuple[Path, dict[str, Any]]:
    require(NAME.fullmatch(name), "Unsafe release name")
    release = RELEASES / name
    require(release.is_dir() and not release.is_symlink(), f"No release {name}")
    return release, read_json(release / "package.json")


def _verify(release: Path, package: dict[str, Any]) -> None:
    require(package.get("version") == PACKAGE_VERSION, "Unknown package version")
    listed = package["files"]
    for relative, record in listed.items():
        path = release / PurePosixPath(relative)
        require(path.is_file() and not path.is_symlink(), f"Missing member {relative}")
        require(
            path.stat().st_size == record["bytes"] and sha256_file(path) == record["sha256"],
            f"Member differs from the manifest: {relative}",
        )
    # The Linux rebuild adds artifact_root/football; nothing else may appear.
    for path in (release / "payload").rglob("*"):
        if path.is_file():
            relative = path.relative_to(release).as_posix()
            require(
                relative in listed or relative.startswith("payload/artifact_root/football/"),
                f"Unlisted member {relative}",
            )


def command_stage(args: argparse.Namespace) -> None:
    tarball = Path(args.tarball).expanduser().resolve()
    require(sha256_file(tarball) == args.sha256, "The uploaded package differs from the PC's")
    with tarfile.open(tarball, "r:gz") as bundle:
        names = {PurePosixPath(member.name).parts[0] for member in bundle.getmembers()}
        require(len(names) == 1, "A package holds exactly one release directory")
        (name,) = names
        require(NAME.fullmatch(name), "Unsafe release name in the package")
        require(not (RELEASES / name).exists(), f"Release {name} exists; never unpack over it")
        RELEASES.mkdir(parents=True, exist_ok=True)
        bundle.extractall(RELEASES, filter="data")
    release, package = _release(name)
    _verify(release, package)
    tarball.unlink()
    print(
        json.dumps(
            {
                "stage": "staged",
                "release": name,
                "files": len(package["files"]),
                "football": package["football"],
                "news_capture": package["news_capture"],
            }
        )
    )


def _image_for(release: Path, package: dict[str, Any]) -> str:
    record = read_json(release / "image.json")
    require(
        record["tag"] == package["tag"] and record["commit"] == package["tag_commit"],
        "The prepared image is for another tag",
    )
    actual = run("docker", "image", "inspect", "--format", "{{.Id}}", record["image"]).strip()
    require(actual == record["image_id"], "The prepared image tag now names another image")
    return record["image_id"]


def _build_image(release: Path, package: dict[str, Any]) -> None:
    tag, commit = package["tag"], package["tag_commit"]
    run("git", "-C", str(REPO), "fetch", "-q", "--tags", "origin", timeout=300)
    require(
        run("git", "-C", str(REPO), "rev-parse", f"{tag}^{{commit}}").strip() == commit,
        "The VM's tag names another commit than the PC's",
    )
    build = BASE / "build" / tag
    if not build.exists():
        run("git", "-C", str(REPO), "worktree", "add", "--detach", str(build), commit)
    require(
        run("git", "-C", str(build), "rev-parse", "HEAD").strip() == commit,
        "Build checkout is not at the tag",
    )
    require(
        run("git", "-C", str(build), "status", "--porcelain").strip() == "",
        "Build checkout is dirty",
    )
    # One image tag per release, so preparing a release never moves a tag the live project
    # names; two releases of one commit share the layers, not the name.
    image = f"squadopt-backend:{release.name}"
    run(
        "docker",
        "build",
        "-q",
        "--build-arg",
        f"SQUADOPT_REPOSITORY_COMMIT={commit}",
        "-t",
        image,
        str(build),
        timeout=1800,
    )
    image_id = run("docker", "image", "inspect", "--format", "{{.Id}}", image).strip()
    write_json(
        release / "image.json",
        {
            "tag": tag,
            "commit": commit,
            "image": image,
            "image_id": image_id,
            "build_dir": str(build),
            "built_at": now(),
        },
    )
    print(json.dumps({"stage": "image_built", "image": image, "image_id": image_id}))


def command_prepare(args: argparse.Namespace) -> None:
    release, package = _release(args.release)
    _verify(release, package)
    _build_image(release, package)
    image_id = _image_for(release, package)
    if not package["football"]:
        print(json.dumps({"stage": "prepared", "football": False}))
        return
    marker = (
        release / "payload" / "artifact_root" / "football" / f"{package['capture']}.bundle.json"
    )
    if marker.exists():
        receipt = read_json(release / "rebuild-receipt.json")
        require(receipt["image_id"] == image_id, "Sealed with another image; stage a new release")
        print(json.dumps({"stage": "prepared", "football": True, "replay": True}))
        return
    require(
        not (release / "payload" / "artifact_root" / "football").exists(),
        "A partial football rebuild exists; stage a new release instead of retrying over it",
    )
    uid, gid = os.getuid(), os.getgid()  # type: ignore[attr-defined]
    started = time.monotonic()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            f"football-rebuild-{package['name']}"[:63],
            "--user",
            f"{uid}:{gid}",
            "--network",
            "none",
            "--memory",
            "3g",
            "--cpus",
            "2",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{release}:/pkg",
            "-v",
            f"{Path(__file__).resolve()}:/op/tool.py:ro",
            "--entrypoint",
            "python",
            image_id,
            "/op/tool.py",
            "rebuild-inside",
            "--pkg",
            "/pkg",
            "--image-id",
            image_id,
        ],
        timeout=3600,
        check=False,
    )
    require(result.returncode == 0, f"The Linux football rebuild failed ({result.returncode})")
    _verify(release, package)
    print(
        json.dumps(
            {"stage": "prepared", "football": True, "seconds": round(time.monotonic() - started, 1)}
        )
    )


# ---- inside the release image ---------------------------------------------------------


def _bounded_difference(held: tuple[Any, Any], rebuilt: tuple[Any, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    maximum = 0.0

    def visit(a: Any, b: Any, path: str) -> None:
        nonlocal maximum
        require(type(a) is type(b), "Structural type drift at " + path)
        if isinstance(a, dict):
            require(a.keys() == b.keys(), "Structural key drift at " + path)
            for key in sorted(a):
                visit(a[key], b[key], path + "/" + key)
        elif isinstance(a, list):
            require(len(a) == len(b), "Structural length drift at " + path)
            for index, (left, right) in enumerate(zip(a, b, strict=True)):
                visit(left, right, f"{path}/{index}")
        elif a != b:
            if type(a) is float:
                require(math.isfinite(a) and math.isfinite(b), "Nonfinite drift at " + path)
                require(
                    any(pattern.fullmatch(path) for pattern in DERIVED_FLOAT_PATHS),
                    "Numeric source drift at " + path,
                )
                difference = abs(a - b)
                require(difference <= MAX_ABSOLUTE_DRIFT, "Numeric drift too large at " + path)
                maximum = max(maximum, difference)
                counts["float"] += 1
            else:
                require(
                    type(a) is str
                    and HEX.fullmatch(a)
                    and HEX.fullmatch(b)
                    and any(pattern.fullmatch(path) for pattern in DERIVED_HASH_PATHS),
                    "Source identity drift at " + path,
                )
                counts["hash"] += 1

    for label, left, right in zip(("forecast", "components"), held, rebuilt, strict=True):
        visit(left, right, label)
    require(canonical(held[1]["recipe"]) == canonical(rebuilt[1]["recipe"]), "Recipe changed")
    for left, right in zip(held, rebuilt, strict=True):
        for field in ("model_artifacts", "basis_sha256"):
            require(
                canonical(left["composite_metadata"][field])
                == canonical(right["composite_metadata"][field]),
                f"Source changed: {field}",
            )
    return {
        "counts": dict(counts),
        "maximum_absolute_float_difference": maximum,
        "absolute_limit": MAX_ABSOLUTE_DRIFT,
    }


def _composite_arguments(recipe: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    import pandas as pd

    from squadopt.live import football_composite_basis as basis
    from squadopt.live.football_composite_codec import read_composite_source

    def source(record: dict[str, Any], kind: type) -> Any:
        return read_composite_source(
            record["payload_json"].encode(), expected_sha256=record["sha256"], source_type=kind
        )

    inventory = source(recipe["inventory"], basis.CompositeWeekInventory)
    bootstrap = json.loads(snapshot.payloads["bootstrap-static.json"])
    raw_calendar = snapshot.payloads["fixtures.json"]
    clubs = {team["id"]: team["code"] for team in bootstrap["teams"]}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    calendar = pd.DataFrame(
        [
            {
                "fixture": row["id"],
                "GW": row["event"],
                "kickoff": pd.Timestamp(row["kickoff_time"]),
                "club": clubs[row["team_h" if home else "team_a"]],
                "opponent": clubs[row["team_a" if home else "team_h"]],
                "home": int(home),
            }
            for row in json.loads(raw_calendar)
            if row["event"] in inventory.gameweeks
            for home in (True, False)
        ]
    )
    arguments: dict[str, Any] = {
        key: basis._unpack_document(recipe[key])
        for key in (
            "native_forecast",
            "native_components",
            "flag_forecast",
            "flag_components",
            "native_basis_document",
        )
    }
    arguments.update(
        model_assets=tuple(basis.CompositeModelAsset(**record) for record in recipe["models"]),
        inventory=inventory,
        weeks=tuple(source(record, basis.CompositeWeekInput) for record in recipe["weeks"]),
        fixtures=tuple(
            source(record, basis.CompositeFixtureInput) for record in recipe["fixtures"]
        ),
        fixture_calendar=calendar,
        roster_clubs={player["code"]: clubs[player["team"]] for player in bootstrap["elements"]},
        roster_positions={
            player["code"]: positions[player["element_type"]] for player in bootstrap["elements"]
        },
        deadline_by_gameweek={event["id"]: event["deadline_time"] for event in bootstrap["events"]},
        captured_calendar_sha256=sha256_bytes(raw_calendar),
        generated_at=recipe["generated_at"],
        decision_at=recipe["decision_at"],
    )
    return arguments


def command_rebuild_inside(args: argparse.Namespace) -> None:
    import platform

    from squadopt.data.snapshots import read_snapshot
    from squadopt.live import football_composite_basis as basis
    from squadopt.live.football_artifact import forecast_digest
    from squadopt.live.recommendation import read_inputs, read_projection_handoff
    from squadopt.platform.football_bundle import seal_football_bundle
    from squadopt.platform.football_publication import publish_football_artifacts

    require(platform.system() == "Linux", "The rebuild runs inside the Linux release image")
    started = now()
    pkg = Path(args.pkg)
    package = read_json(pkg / "package.json")
    payload = pkg / "payload"
    capture = package["capture"]
    held = tuple(
        read_json(payload / "windows_forecast" / f"{capture}{suffix}")
        for suffix in (".json", ".components.json")
    )
    snapshot = read_snapshot(payload / "snapshot_root", capture)
    inputs = read_inputs(snapshot, season=package["season"], gameweek=package["gameweek"])
    handoff_path = payload / "handoff_root" / package["handoff"]
    handoff = read_projection_handoff(handoff_path)
    recipe = held[1]["recipe"]
    built = basis.build_composite_documents(**_composite_arguments(recipe, snapshot))
    rebuilt = tuple(json.loads(canonical(document)) for document in built)
    drift = _bounded_difference(held, rebuilt)  # type: ignore[arg-type]
    for document in built:
        require(document["fingerprint"] == forecast_digest(document), "Builder fingerprint invalid")
    print(json.dumps({"stage": "rendered_on_linux", "drift": drift}), flush=True)
    published, companion = publish_football_artifacts(
        artifact_root=payload / "artifact_root",
        snapshot=snapshot,
        inputs=inputs,
        document=built[0],
        companion=built[1],
    )
    require(companion is not None, "The composite companion was not published")
    rotation = package.get("rotation_table")
    sealed = seal_football_bundle(
        artifact_root=payload / "artifact_root",
        snapshot_root=payload / "snapshot_root",
        snapshot_id=capture,
        handoff_path=handoff_path,
        site_data_root=payload / "site_data_root",
        news_capture_id=package.get("news_capture"),
        rotation_table_path=(payload / "artifact_root" / "rotation" / rotation)
        if rotation
        else None,
        league_id=package["league_id"],
    )
    write_json_new(
        pkg / "rebuild-receipt.json",
        {
            "version": "vm_football_linux_rebuild_v1",
            "started_at": started,
            "completed_at": now(),
            "image_id": args.image_id,
            "commit": os.environ.get("SQUADOPT_REPOSITORY_COMMIT"),
            "python": platform.python_version(),
            "capture": capture,
            "handoff_fingerprint": handoff.fingerprint,
            "drift": drift,
            "windows_forecast_fingerprint": held[0]["fingerprint"],
            "forecast_fingerprint": built[0]["fingerprint"],
            "forecast_sha256": sha256_file(published),
            "components_sha256": sha256_file(companion),
            "bundle_fingerprint": sealed.fingerprint,
            "news_capture": package.get("news_capture"),
            "rotation_table": rotation,
        },
    )
    print(
        json.dumps(
            {
                "stage": "sealed_on_linux",
                "bundle_fingerprint": sealed.fingerprint,
                "forecast_sha256": sha256_file(published),
            }
        ),
        flush=True,
    )


# ---- configuration --------------------------------------------------------------------


def _env_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def render_env(lines: list[str], values: dict[str, str]) -> str:
    """Replace the named keys and keep every other line as it was, in order."""
    seen: set[str] = set()
    rendered = []
    for line in lines:
        key = (
            line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#")
            else None
        )
        if key in values:
            rendered.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            rendered.append(line)
    rendered.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    return "\n".join(rendered) + "\n"


def render_override(artifact_root: PurePath, club_news: tuple[str, PurePath | None]) -> str:
    """The Compose override for the artifact root and the club-news source of one release.

    ``club_news`` is the container path the backend reads and, for a retained fixture file,
    the host file mounted there. A club-news capture is read inside the snapshot root.
    """
    container_path, host_file = club_news
    lines = [
        "# Generated by scripts/release/vm_football_release.py for one release; do not edit.",
        "services:",
    ]
    for service in ("api", "worker"):
        lines += [
            f"  {service}:",
            "    environment:",
            "      SQUADOPT_BACKEND_ARTIFACT_ROOT: /mnt/artifacts",
            f"      SQUADOPT_BACKEND_CLUB_NEWS_SOURCE: {container_path}",
            "    volumes:",
            "      - type: bind",
            f"        source: {artifact_root}",
            "        target: /mnt/artifacts",
            "        read_only: true",
            "        bind:",
            "          create_host_path: false",
        ]
        if host_file is not None:
            lines += [
                "      - type: bind",
                f"        source: {host_file}",
                f"        target: {container_path}",
                "        read_only: true",
                "        bind:",
                "          create_host_path: false",
            ]
    return "\n".join(lines) + "\n"


def _release_configuration(
    release: Path,
    package: dict[str, Any],
    image: str,
    base_env: list[str],
    ports: tuple[int, int] | None,
    store: Path | None,
) -> tuple[str, str]:
    payload = release / "payload"
    values = {
        "SQUADOPT_BACKEND_IMAGE": image,
        "SQUADOPT_SITE_PATH": str(payload / "site_data_root"),
        "SQUADOPT_SNAPSHOT_PATH": str(payload / "snapshot_root"),
        "SQUADOPT_HANDOFF_PATH": str(payload / "handoff_root"),
    }
    if store is not None:
        values["SQUADOPT_STORE_PATH"] = str(store)
    if ports is not None:
        values["SQUADOPT_API_PORT"], values["SQUADOPT_WORKER_METRICS_PORT"] = map(str, ports)
    news = package.get("news_capture")
    club_news = (
        (f"/mnt/snapshots/{news}", None)
        if news
        else ("/mnt/club_news_v1.fixture.json", release / "payload" / "club_news_fixture.json")
    )
    return render_env(base_env, values), render_override(payload / "artifact_root", club_news)


# ---- checks shared by the candidate and the activation --------------------------------


def _http(
    port: int, path: str, body: object | None = None, timeout: float = 30
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={} if body is None else {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def _wait_ready(port: int, seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    last: tuple[int, bytes] = (0, b"")
    while time.monotonic() < deadline:
        last = _http(port, "/ready", timeout=10)
        if last[0] == 200:
            return json.loads(last[1])
        time.sleep(5)
    raise ReleaseError(f"Not ready after {seconds:.0f} s (last status {last[0]})")


def _advice_job(port: int, selection: dict[str, Any]) -> dict[str, Any]:
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{PROBE_ENTRY}/advice"
    started = time.monotonic()
    code, raw = _http(port, route + "?" + urllib.parse.urlencode(selection))
    if code == 200:
        return {"selection": selection, "status": "cached", "sha256": sha256_bytes(raw)}
    require(code == 404, f"Unexpected status {code} for an uncached request {selection}")
    code, raw = _http(port, route, selection)
    require(code in (200, 202), f"Advice request refused ({code}): {raw[:200]!r}")
    if code == 202:
        job = json.loads(raw)["job_id"]
        require(re.fullmatch(r"[A-Za-z0-9_-]+", job), "Unsafe job id")
        while True:
            require(time.monotonic() - started < 900, f"Job {job} did not finish in 900 s")
            time.sleep(3)
            code, raw = _http(port, f"/api/v1/advice-jobs/{job}")
            require(code == 200, f"Job status refused ({code})")
            status = json.loads(raw)["status"]
            if status == "completed":
                break
            require(status in ("queued", "running"), f"Job {job} ended {status}")
        code, raw = _http(port, route + "?" + urllib.parse.urlencode(selection))
        require(code == 200, f"Completed advice not served ({code})")
    answer = json.loads(raw)
    return {
        "selection": selection,
        "status": "computed",
        "seconds": round(time.monotonic() - started, 1),
        "sha256": sha256_bytes(raw),
        "prediction_model": (answer.get("prediction_model") or {}).get("version"),
    }


def _expectations(package: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    models = (
        args.expect_models.split(",")
        if args.expect_models
        else (["current", "football"] if package["football"] else ["current"])
    )
    word = (
        args.expect_managers_word == "yes"
        if args.expect_managers_word
        else bool(package.get("news_capture") and package.get("rotation_table"))
    )
    return {"capture": package["capture"], "models": sorted(models), "managers_word": word}


def _check_serving(port: int, expected: dict[str, Any], jobs: bool, result: dict[str, Any]) -> None:
    """Fill ``result`` as each check passes, so a refusal still records what was served."""
    result["ready"] = ready = _wait_ready(port, 600)
    require(all(ready.get("checks", {}).values()), f"A readiness check is false: {ready}")
    code, raw = _http(port, f"/api/v1/leagues/{LEAGUE_ID}/capabilities", timeout=900)
    require(code == 200, f"Capabilities refused ({code})")
    capabilities = json.loads(raw)
    result["observed"] = observed = {
        "capture": capabilities["capture_snapshot_id"],
        "models": sorted(capabilities.get("models") or ["current"]),
        "managers_word": bool(capabilities["managers_word"]["available"]),
    }
    result["decision_information"] = capabilities.get("decision_information")
    result["top100"] = capabilities.get("top100", {}).get("available")
    require(observed == expected, f"Serving {observed}, expected {expected}")
    if jobs:
        result["jobs"] = []
        for selection in [{"strategy": "saf-puan", "window": 1}] + (
            [{"strategy": "saf-puan", "window": 1, "model": "football"}]
            if "football" in expected["models"]
            else []
        ):
            result["jobs"].append(_advice_job(port, selection))


def _compose(project: str, env: Path, override: Path, compose_file: Path, *verb: str) -> None:
    run(
        "docker",
        "compose",
        "-p",
        project,
        "--env-file",
        str(env),
        "-f",
        str(compose_file),
        "-f",
        str(override),
        *verb,
        timeout=900,
    )


def command_candidate(args: argparse.Namespace) -> None:
    release, package = _release(args.release)
    _verify(release, package)
    image_id = _image_for(release, package)
    image = read_json(release / "image.json")["image"]
    compose_file = Path(read_json(release / "image.json")["build_dir"]) / "deploy" / "compose.yaml"
    # Each attempt keeps its own directory and scratch store; it never touches the live
    # project, so trying again is harmless, and activation reads the newest attempt.
    candidate = release / "candidate" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    store = candidate / "store"
    store.mkdir(parents=True)
    run(
        "docker",
        "run",
        "--rm",
        "--user",
        "0",
        "--network",
        "none",
        "-v",
        f"{store}:/s",
        "--entrypoint",
        "chown",
        image_id,
        "10001:10001",
        "/s",
    )
    env_text, override_text = _release_configuration(
        release,
        package,
        image,
        _env_lines(LIVE_ENV),
        (CANDIDATE_API_PORT, CANDIDATE_METRICS_PORT),
        store,
    )
    (candidate / "candidate.env").write_text(env_text, encoding="utf-8")
    os.chmod(candidate / "candidate.env", 0o600)
    (candidate / "candidate.compose.yaml").write_text(override_text, encoding="utf-8")
    project = "squadopt-candidate"
    expected = _expectations(package, args)
    receipt: dict[str, Any] = {
        "version": "vm_football_candidate_v1",
        "started_at": now(),
        "image_id": image_id,
        "expected": expected,
        "passed": False,
    }
    try:
        _compose(
            project,
            candidate / "candidate.env",
            candidate / "candidate.compose.yaml",
            compose_file,
            "up",
            "-d",
        )
        receipt["serving"] = {}
        receipt["jobs_skipped"] = bool(args.no_jobs)
        _check_serving(CANDIDATE_API_PORT, expected, not args.no_jobs, receipt["serving"])
        receipt["passed"] = True
    except Exception as error:  # every failure is recorded, then the project stops
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        logs = subprocess.run(
            ["docker", "compose", "-p", project, "logs", "--no-color", "--tail", "200"],
            capture_output=True,
            text=True,
            check=False,
        )
        (candidate / "candidate.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        _compose(
            project,
            candidate / "candidate.env",
            candidate / "candidate.compose.yaml",
            compose_file,
            "down",
        )
        receipt["completed_at"] = now()
        write_json_new(candidate / "receipt.json", receipt)
    print(
        json.dumps(
            {k: receipt[k] for k in ("passed", "expected") if k in receipt}
            | {
                "observed": receipt.get("serving", {}).get("observed"),
                "jobs": receipt.get("serving", {}).get("jobs"),
                "decision_information": receipt.get("serving", {}).get("decision_information"),
                "error": receipt.get("error"),
            },
            indent=2,
        )
    )
    require(receipt["passed"], "The candidate did not pass; nothing live was touched")


def _live_compose_file() -> Path:
    return REPO / "deploy" / "compose.yaml"


def _restart_live() -> None:
    _compose("squadopt", LIVE_ENV, LIVE_OVERRIDE, _live_compose_file(), "up", "-d")


def command_activate(args: argparse.Namespace) -> None:
    release, package = _release(args.release)
    _verify(release, package)
    image_id = _image_for(release, package)
    image = read_json(release / "image.json")["image"]
    attempts = sorted(
        path for path in (release / "candidate").glob("*/receipt.json") if path.is_file()
    )
    require(attempts, "No candidate ran for this release")
    candidate = read_json(attempts[-1])
    require(
        candidate["passed"] and candidate["image_id"] == image_id,
        "Activate only a release whose newest candidate passed with this image",
    )
    require(
        args.no_jobs or not candidate.get("jobs_skipped"),
        "The newest candidate skipped the advice jobs; run one with jobs before activating",
    )
    require(
        run("git", "-C", str(REPO), "status", "--porcelain").strip() == "", "Live repo is dirty"
    )
    rollback = release / "rollback"
    require(not rollback.exists(), "This release was activated before; use a new release")
    rollback.mkdir()
    shutil.copy2(LIVE_ENV, rollback / "env")
    shutil.copy2(LIVE_OVERRIDE, rollback / "compose.artifacts.yaml")
    previous_commit = run("git", "-C", str(REPO), "rev-parse", "HEAD").strip()
    (rollback / "repo_commit").write_text(previous_commit + "\n", encoding="utf-8")
    env_text, override_text = _release_configuration(
        release, package, image, _env_lines(LIVE_ENV), None, None
    )
    expected = _expectations(package, args)
    record: dict[str, Any] = {
        "version": "vm_football_activation_v1",
        "started_at": now(),
        "release": package["name"],
        "image_id": image_id,
        "previous_commit": previous_commit,
        "expected": expected,
    }
    try:
        run("git", "-C", str(REPO), "checkout", "-q", "--detach", package["tag_commit"])
        _atomic_text(LIVE_ENV, env_text, 0o600)
        _atomic_text(LIVE_OVERRIDE, override_text, 0o664)
        _restart_live()
        record["serving"] = {}
        _check_serving(8000, expected, not args.no_jobs, record["serving"])
        record["stage"] = "active"
    except Exception as error:  # any failure after the switch restores the kept release
        record["error"] = f"{type(error).__name__}: {error}"
        record["stage"] = "rolled_back"
        _restore(release)
        record["after_rollback_ready"] = _wait_ready(8000, 600)
    finally:
        record["completed_at"] = now()
        write_json_new(release / "activation.json", record)
    print(
        json.dumps(
            {k: record.get(k) for k in ("stage", "expected", "error")}
            | {"observed": record.get("serving", {}).get("observed")},
            indent=2,
        )
    )
    require(record["stage"] == "active", "Activation failed and the previous release is back")


def _atomic_text(path: Path, text: str, mode: int) -> None:
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _restore(release: Path) -> None:
    rollback = release / "rollback"
    _atomic_text(LIVE_ENV, (rollback / "env").read_text(encoding="utf-8"), 0o600)
    _atomic_text(
        LIVE_OVERRIDE, (rollback / "compose.artifacts.yaml").read_text(encoding="utf-8"), 0o664
    )
    run(
        "git",
        "-C",
        str(REPO),
        "checkout",
        "-q",
        "--detach",
        (rollback / "repo_commit").read_text(encoding="utf-8").strip(),
    )
    _restart_live()


def command_rollback(args: argparse.Namespace) -> None:
    release, _ = _release(args.release)
    require((release / "rollback" / "env").is_file(), "This release kept no rollback")
    _restore(release)
    ready = _wait_ready(8000, 600)
    code, raw = _http(8000, f"/api/v1/leagues/{LEAGUE_ID}/capabilities", timeout=900)
    capture = json.loads(raw)["capture_snapshot_id"] if code == 200 else None
    print(json.dumps({"stage": "rolled_back", "ready": ready, "capture": capture}, indent=2))


def command_status(args: argparse.Namespace) -> None:
    containers = json.loads(run("docker", "inspect", "squadopt-api-1", "squadopt-worker-1"))
    code, raw = _http(8000, f"/api/v1/leagues/{LEAGUE_ID}/capabilities", timeout=60)
    capabilities = json.loads(raw) if code == 200 else {}
    print(
        json.dumps(
            {
                "repo_commit": run("git", "-C", str(REPO), "rev-parse", "HEAD").strip(),
                "containers": [
                    {
                        "name": c["Name"],
                        "image": c["Image"],
                        "started": c["State"]["StartedAt"],
                        "mounts": sorted(m["Source"] for m in c["Mounts"]),
                    }
                    for c in containers
                ],
                "capture": capabilities.get("capture_snapshot_id"),
                "models": capabilities.get("models"),
                "managers_word": (capabilities.get("managers_word") or {}).get("available"),
                "releases": sorted(path.name for path in RELEASES.iterdir() if path.is_dir()),
            },
            indent=2,
        )
    )


# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack", help="PC: build the package directory and tarball")
    pack.add_argument("--repo", default=".")
    pack.add_argument("--season", default="2026-27")
    pack.add_argument("--gameweek", type=int, required=True)
    pack.add_argument("--league", type=int, default=LEAGUE_ID)
    pack.add_argument("--capture", required=True, help="the decision fpl-live capture id")
    pack.add_argument("--tag", required=True, help="the release tag the VM image is built from")
    pack.add_argument("--snapshot-root", default="data/snapshots")
    pack.add_argument("--handoff", required=True)
    pack.add_argument("--top100-manifest", required=True)
    pack.add_argument("--rotation-manifest")
    pack.add_argument("--news-capture")
    pack.add_argument("--site-data", help="a site data tree; default: web/public/data at --tag")
    pack.add_argument(
        "--windows-forecast-dir",
        help="the directory holding <capture>.json and <capture>.components.json",
    )
    pack.add_argument("--name")
    pack.add_argument("--out", required=True, help="a short directory (Windows path limit)")
    pack.set_defaults(handler=command_pack)

    push = commands.add_parser("push", help="PC: upload, unpack and verify on the VM")
    push.add_argument("tarball")
    push.set_defaults(handler=command_push)

    remote = commands.add_parser("remote", help="PC: run a VM step over SSH")
    remote.add_argument("rest", nargs=argparse.REMAINDER)
    remote.set_defaults(handler=command_remote)

    stage = commands.add_parser("stage", help="VM: unpack an uploaded package")
    stage.add_argument("--tarball", required=True)
    stage.add_argument("--sha256", required=True)
    stage.set_defaults(handler=command_stage)

    for name, handler in (
        ("prepare", command_prepare),
        ("candidate", command_candidate),
        ("activate", command_activate),
        ("rollback", command_rollback),
    ):
        step = commands.add_parser(name)
        step.add_argument("--release", required=True)
        if name in ("candidate", "activate"):
            step.add_argument("--expect-models", help="comma-separated; default from the package")
            step.add_argument("--expect-managers-word", choices=("yes", "no"))
            step.add_argument("--no-jobs", action="store_true", help="skip the advice jobs")
        step.set_defaults(handler=handler)

    inside = commands.add_parser("rebuild-inside", help="inside the release image only")
    inside.add_argument("--pkg", required=True)
    inside.add_argument("--image-id", required=True)
    inside.set_defaults(handler=command_rebuild_inside)

    status = commands.add_parser("status", help="VM: what the live project serves")
    status.set_defaults(handler=command_status)

    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except ReleaseError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
