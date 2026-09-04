"""Tests for seeding the entry registry from a captured standings page.

The seed script never fetches, so everything here builds its own standings bytes and
writes into a temporary directory.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.seed_entry_registry import (
    _printable,
    _registry_document,
    _standings_bytes,
    main,
)

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION, EntryRegistry
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.sources.fpl_live import fpl_league_standings

LEAGUE = 352490

MEMBERS: list[dict[str, Any]] = [
    {"entry": 22, "entry_name": "Second XI", "player_name": "Bea Manager", "rank": 2},
    {"entry": 11, "entry_name": "First XI", "player_name": "Ada Manager", "rank": 1},
]


def _standings(*, results: list[dict[str, Any]] | None = None, has_next: bool = False) -> bytes:
    document = {
        "league": {"id": LEAGUE, "name": "The Mini League"},
        "standings": {
            "has_next": has_next,
            "page": 1,
            "results": MEMBERS if results is None else results,
        },
    }
    return json.dumps(document).encode("utf-8")


def _document() -> dict[str, Any]:
    members = fpl_league_standings(_standings(), league_id=LEAGUE)
    return _registry_document(members, league_id=LEAGUE, now="2026-08-25T09:00:00Z")


def test_the_registry_records_every_member_ordered_by_entry_id() -> None:
    document = _document()
    assert document["contract_version"] == ENTRY_REGISTRY_CONTRACT_VERSION
    assert document["seeded_from_league"] == LEAGUE
    assert [entry["entry_id"] for entry in document["entries"]] == [11, 22]
    assert [entry["label"] for entry in document["entries"]] == ["First XI", "Second XI"]


def test_the_managers_own_name_is_never_written() -> None:
    """The page publishes it; the registry has no field for it and must not grow one."""

    serialized = json.dumps(_document())
    assert "Ada Manager" not in serialized
    assert "Bea Manager" not in serialized
    assert "player_name" not in serialized


def test_the_written_registry_is_what_the_application_loader_reads(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_document(), indent=2) + "\n", encoding="utf-8")
    registry = EntryRegistry.load(path)
    assert registry.ids() == (11, 22)
    assert [entry.label for entry in registry.entries] == ["First XI", "Second XI"]
    assert all(entry.registered_at_utc == "2026-08-25T09:00:00Z" for entry in registry.entries)


def test_a_paginated_league_stops_the_seed_rather_than_registering_half_of_it() -> None:
    with pytest.raises(DataSourceError, match="more standings pages"):
        fpl_league_standings(_standings(has_next=True), league_id=LEAGUE)


def test_a_saved_page_seeds_without_any_capture(tmp_path: Path) -> None:
    """The first seed cannot come from a capture: no capture holds standings yet."""

    saved = tmp_path / "page1.json"
    saved.write_bytes(_standings())
    payload, origin = _standings_bytes(league_id=LEAGUE, snapshot_id=None, standings_file=saved)
    assert payload == _standings()
    assert str(saved) in origin


def test_a_capture_without_the_league_payload_says_so_rather_than_seeding_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.seed_entry_registry as seed

    monkeypatch.setattr(seed, "SNAPSHOT_ROOT", tmp_path)
    with pytest.raises(DataError, match="No snapshots"):
        seed._standings_bytes(league_id=LEAGUE, snapshot_id=None, standings_file=None)


def test_a_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.seed_entry_registry as seed

    saved = tmp_path / "page1.json"
    saved.write_bytes(_standings())
    target = tmp_path / "entries" / "registry.json"
    monkeypatch.setattr(seed, "REGISTRY_PATH", target)
    monkeypatch.setattr(
        "sys.argv",
        [
            "seed_entry_registry",
            "--league",
            str(LEAGUE),
            "--standings-file",
            str(saved),
            "--dry-run",
        ],
    )
    assert main() == 0
    assert not target.exists()
    assert "nothing written" in capsys.readouterr().out


def test_the_seed_writes_a_registry_the_loader_reproduces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.seed_entry_registry as seed

    saved = tmp_path / "page1.json"
    saved.write_bytes(_standings())
    target = tmp_path / "entries" / "registry.json"
    monkeypatch.setattr(seed, "REGISTRY_PATH", target)
    monkeypatch.setattr(
        "sys.argv",
        ["seed_entry_registry", "--league", str(LEAGUE), "--standings-file", str(saved)],
    )
    assert main() == 0
    assert EntryRegistry.load(target).ids() == (11, 22)
    assert "re-read and verified" in capsys.readouterr().out


def test_a_missing_standings_file_is_reported_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "seed_entry_registry",
            "--league",
            str(LEAGUE),
            "--standings-file",
            str(tmp_path / "absent.json"),
        ],
    )
    assert main() == 1
    assert "could not be seeded" in capsys.readouterr().out


def test_the_committed_example_stays_loadable() -> None:
    """The example is the only registry shape in git; a drift here is a silent doc lie."""

    example = Path(__file__).resolve().parents[2] / "data" / "sample"
    example = example / "entry_registry_v1.example.json"
    registry = EntryRegistry.load(example)
    assert registry.contract_version == ENTRY_REGISTRY_CONTRACT_VERSION
    assert registry.ids() == (1000001, 1000002)


EMOJI_NAME = "Takim 🔥 XI"


def test_a_team_name_the_console_cannot_encode_is_degraded_only_for_display() -> None:
    """An emoji team name used to abort the seed at print time before anything was written.

    print raises UnicodeEncodeError on a Windows codepage that has no mapping for
    the character, so the echo has to be lossy rather than fatal.
    """

    import sys

    encoding = sys.stdout.encoding or "utf-8"
    rendered = _printable(EMOJI_NAME)
    rendered.encode(encoding)  # must not raise, whatever the console encoding is
    assert rendered.startswith("Takim ")
    assert rendered.endswith(" XI")


def test_the_registry_keeps_the_name_the_source_published(tmp_path: Path) -> None:
    """Only the console echo is degraded; the file is exact."""

    results = [{"entry": 11, "entry_name": EMOJI_NAME, "player_name": "Ada Manager", "rank": 1}]
    members = fpl_league_standings(_standings(results=results), league_id=LEAGUE)
    document = _registry_document(members, league_id=LEAGUE, now="2026-08-25T09:00:00Z")
    assert document["entries"][0]["label"] == EMOJI_NAME

    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    assert EntryRegistry.load(path).entries[0].label == EMOJI_NAME
