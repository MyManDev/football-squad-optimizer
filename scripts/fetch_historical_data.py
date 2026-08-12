"""Download the pinned historical archive into a git-ignored local directory.

    python -m scripts.fetch_historical_data            # download and verify
    python -m scripts.fetch_historical_data --verify   # verify what is already here
    python -m scripts.fetch_historical_data --write-manifest

Why a pinned commit and a checksum manifest rather than committed data:

The archive's data is not ours to redistribute — its own licence covers only its
code, and the upstream terms restrict republication. So the data stays out of the
repository and only the metadata needed to reproduce an identical download is
committed.

That metadata is not a formality. The archive is still updated, so two people
fetching a week apart would otherwise hold different data and their benchmark
numbers would not be comparable. The experiment contract requires compared
configurations to share identical data snapshots; a checksum makes that a verified
fact rather than an assumption.
"""

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    GAMEWEEK_FILE,
    ROSTER_FILE,
    SUPPORTED_SEASONS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"

# The upcoming season has no completed gameweeks, so only its roster is fetched.
# That roster is the opening player pool and its prices.
UPCOMING_SEASON = "2026-27"
READ_CHUNK = 1 << 20


def relative_paths() -> list[str]:
    """Return every archive path this project reads, relative to the data directory."""

    paths = [
        f"data/{season}/{name}"
        for season in SUPPORTED_SEASONS
        for name in (GAMEWEEK_FILE, ROSTER_FILE)
    ]
    paths.append(f"data/{UPCOMING_SEASON}/{ROSTER_FILE}")
    return paths


def source_url(relative: str) -> str:
    return f"https://raw.githubusercontent.com/{ARCHIVE_REPOSITORY}/{ARCHIVE_COMMIT}/{relative}"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download(relative: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = source_url(relative)
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Failed to download {url}: HTTP {error.code}") from error
    except OSError as error:
        raise SystemExit(f"Failed to download {url}: {error}") from error
    destination.write_bytes(payload)


def load_manifest() -> dict[str, object]:
    if not MANIFEST_PATH.is_file():
        return {}
    return dict(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def write_manifest(checksums: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "repository": ARCHIVE_REPOSITORY,
        "commit": ARCHIVE_COMMIT,
        "note": (
            "Checksums of third-party files this project reads. The data itself is not "
            "redistributed here; run scripts/fetch_historical_data.py to obtain it."
        ),
        "files": dict(sorted(checksums.items())),
    }
    MANIFEST_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def verify(expected: dict[str, str]) -> int:
    """Compare local files against the manifest. Returns the number of problems."""

    problems = 0
    for relative in relative_paths():
        local = RAW_DIR / relative
        if not local.is_file():
            print(f"  MISSING  {relative}")
            problems += 1
            continue
        recorded = expected.get(relative)
        actual = checksum(local)
        if recorded is None:
            print(f"  UNPINNED {relative}  ({actual[:12]}…)")
            problems += 1
        elif recorded != actual:
            print(f"  MISMATCH {relative}")
            print(f"           expected {recorded}")
            print(f"           actual   {actual}")
            problems += 1
        else:
            print(f"  ok       {relative}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="only verify existing files")
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="record checksums of the downloaded files (maintainer use, after a deliberate re-pin)",
    )
    arguments = parser.parse_args()

    manifest = load_manifest()
    pinned_commit = manifest.get("commit")
    if pinned_commit and pinned_commit != ARCHIVE_COMMIT and not arguments.write_manifest:
        print(
            f"Manifest is pinned to {pinned_commit} but the code expects {ARCHIVE_COMMIT}.\n"
            "Re-pinning changes the data every benchmark was measured on, so it is a "
            "deliberate act: re-run with --write-manifest once that is intended."
        )
        return 1

    expected = dict(manifest.get("files", {}))  # type: ignore[arg-type]

    if not arguments.verify:
        print(f"Downloading {ARCHIVE_REPOSITORY} @ {ARCHIVE_COMMIT[:12]}… into {RAW_DIR}")
        for relative in relative_paths():
            download(relative, RAW_DIR / relative)
            print(f"  fetched  {relative}")
        print()

    if arguments.write_manifest:
        recorded = {
            relative: checksum(RAW_DIR / relative)
            for relative in relative_paths()
            if (RAW_DIR / relative).is_file()
        }
        write_manifest(recorded)
        print(f"Wrote {len(recorded)} checksums to {MANIFEST_PATH.relative_to(REPOSITORY_ROOT)}")
        return 0

    if not expected:
        print(
            "No manifest found. A maintainer records one once with --write-manifest; "
            "without it, identical data across machines cannot be verified."
        )
        return 1

    print("Verifying against the committed manifest:")
    problems = verify(expected)
    if problems:
        print(f"\n{problems} problem(s). The local data does not match the pinned snapshot.")
        return 1
    print("\nAll files match the pinned snapshot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
