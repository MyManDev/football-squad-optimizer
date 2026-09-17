"""Finding a capture's switch inputs: by the weekly run's own names, through its own gates.

Nothing here is named by a client. The Top 100 export is the newest generated one of the
week that passes the handoff's gate for this capture; the rotation table is the one named
after this capture. Absent, refused or unreadable all mean the same thing to a member: the
switch is not offered. None of them stops the backend.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import squadopt.platform.advice_switches as module
from squadopt.application.manager_words import ManagerWords, ManagerWordsError
from squadopt.application.top100_weight import (
    TOP100_INPUTS_REFUSED,
    Top100Counts,
    Top100InputsRefused,
)
from squadopt.application.weekly_plan import evidence_artifact, rotation_artifact
from squadopt.platform.advice_switches import (
    AdviceSwitchInputs,
    discovery_signature,
    load_switch_inputs,
)
from squadopt.platform.backend_runtime import BackendConfig, BackendConfigError

SEASON = "2026-27"
CAPTURE = "fpl-live-20260826T083133Z-d45f1bea8b68"
INPUTS: Any = SimpleNamespace(
    season=SEASON, snapshot_id=CAPTURE, deadline=SimpleNamespace(gameweek=3)
)


def _export(root: Path, picks_hash: str, generated_at_utc: str | None) -> Path:
    table, manifest = evidence_artifact(
        root / "phase_b", SEASON, 3, f"fpl-elite-picks-{picks_hash}"
    )
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text("rows", encoding="utf-8")
    document = {} if generated_at_utc is None else {"generated_at_utc": generated_at_utc}
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return table


def _counts(table: Path) -> Top100Counts:
    return Top100Counts(
        counts={1: 100},
        table_sha256=table.name[-16:-4].ljust(64, "0"),
        cohort_snapshot_id="fpl-top100-x",
        picks_snapshot_id="fpl-elite-picks-x",
        picks_gameweek=2,
    )


def _load(root: Path | None, **overrides: Any) -> AdviceSwitchInputs:
    arguments: dict[str, Any] = {
        "artifact_root": root,
        "club_news_source": None,
        "snapshot_root": Path("snapshots"),
        "inputs": INPUTS,
        "projection": object(),
    }
    arguments.update(overrides)
    return load_switch_inputs(**arguments)


def test_without_an_artifact_root_nothing_is_looked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "load_top100_counts", lambda *_a, **_k: pytest.fail("looked"))
    assert _load(None) == AdviceSwitchInputs()
    assert (
        discovery_signature(
            artifact_root=None,
            club_news_source=None,
            season=SEASON,
            gameweek=3,
            capture_snapshot_id=CAPTURE,
        )
        == ()
    )


def test_the_newest_generated_export_that_passes_the_gate_is_the_weeks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rehearsal = _export(tmp_path, "aaaaaaaaaaaa", "2026-08-25T08:00:00Z")
    friday = _export(tmp_path, "000000000000", "2026-08-26T08:00:00Z")
    late = _export(tmp_path, "cccccccccccc", "2026-08-27T08:00:00Z")
    _export(tmp_path, "dddddddddddd", None)  # no manifest date: ranked oldest
    other_week = evidence_artifact(tmp_path / "phase_b", SEASON, 4, "fpl-elite-picks-eeeeeeeeeeee")
    other_week[0].write_text("rows", encoding="utf-8")
    tried: list[str] = []

    def gate(table: Path, **_kwargs: Any) -> Top100Counts:
        tried.append(table.name)
        if table == late:
            raise Top100InputsRefused(TOP100_INPUTS_REFUSED, "taken after the decision capture")
        return _counts(table)

    monkeypatch.setattr(module, "load_top100_counts", gate)
    found = _load(tmp_path)
    assert found.top100_counts == _counts(friday)
    assert tried == [late.name, friday.name]  # newest first, and it stops at the first pass
    assert any("taken after the decision capture" in note for note in found.notes)
    assert rehearsal.name not in tried and other_week[0].name not in tried


def test_no_export_that_passes_means_no_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _load(tmp_path).top100_counts is None  # nothing on disk at all
    _export(tmp_path, "aaaaaaaaaaaa", "2026-08-25T08:00:00Z")

    def gate(_table: Path, **_kwargs: Any) -> Top100Counts:
        raise Top100InputsRefused(TOP100_INPUTS_REFUSED, "only 97 of 100 members read")

    monkeypatch.setattr(module, "load_top100_counts", gate)
    found = _load(tmp_path)
    assert found.top100_counts is None
    assert any("97 of 100" in note for note in found.notes)


def _words(gameweek: int = 3) -> ManagerWords:
    return ManagerWords(
        season=SEASON,
        gameweek=gameweek,
        source_kind="synthetic_fixture",
        source_label="club_news_v1.fixture.json",
        evidence_table="rotation.csv",
        clubs_covered=(),
        words=(),
    )


def _rotation(root: Path, *, capture: str = CAPTURE, sha: object = "7" * 64) -> Path:
    table, manifest = rotation_artifact(root / "rotation", SEASON, 3, capture)
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text("rows", encoding="utf-8")
    manifest.write_text(json.dumps({"table_sha256": sha}), encoding="utf-8")
    return table


def test_the_word_is_the_rotation_table_named_after_this_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "club_news_v1.fixture.json"
    source.write_text("{}", encoding="utf-8")
    seen: dict[str, Any] = {}

    def loader(table: Path, **kwargs: Any) -> ManagerWords:
        seen.update(table=table, **kwargs)
        return _words()

    monkeypatch.setattr(module, "load_manager_words", loader)
    # Another capture's table is not this capture's word.
    _rotation(tmp_path, capture="fpl-live-20260825T083133Z-111111111111")
    assert _load(tmp_path, club_news_source=source).manager_words is None

    table = _rotation(tmp_path)
    found = _load(tmp_path, club_news_source=source)
    assert found.manager_words == _words()
    assert found.rotation_table_sha256 == "7" * 64
    assert seen == {
        "table": table,
        "club_news_source": source,
        "snapshot_root": Path("snapshots"),
    }
    # Without a configured source there is nothing to read the words from.
    assert _load(tmp_path).manager_words is None


@pytest.mark.parametrize("failure", ["another_week", "unreadable", "no_digest"])
def test_a_word_that_cannot_be_trusted_is_off_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    source = tmp_path / "club_news_v1.fixture.json"
    source.write_text("{}", encoding="utf-8")
    _rotation(tmp_path, sha=None if failure == "no_digest" else "7" * 64)

    def loader(_table: Path, **_kwargs: Any) -> ManagerWords:
        if failure == "unreadable":
            raise ManagerWordsError("No manifest beside the table.")
        return _words(gameweek=4 if failure == "another_week" else 3)

    monkeypatch.setattr(module, "load_manager_words", loader)
    found = _load(tmp_path, club_news_source=source)
    assert found.manager_words is None and found.rotation_table_sha256 is None
    assert any(note.startswith("managers_word") for note in found.notes)


def test_the_signature_moves_when_what_would_be_read_moves(tmp_path: Path) -> None:
    source = tmp_path / "club_news_v1.fixture.json"

    def signature() -> tuple[object, ...]:
        return discovery_signature(
            artifact_root=tmp_path,
            club_news_source=source,
            season=SEASON,
            gameweek=3,
            capture_snapshot_id=CAPTURE,
        )

    seen = {signature()}
    _export(tmp_path, "aaaaaaaaaaaa", "2026-08-25T08:00:00Z")
    seen.add(signature())
    _rotation(tmp_path)
    seen.add(signature())
    source.write_text("{}", encoding="utf-8")
    seen.add(signature())
    assert len(seen) == 4
    assert signature() == signature()


def test_the_two_roots_are_optional_configuration() -> None:
    required = {
        "SQUADOPT_BACKEND_STORE_ROOT": "/store",
        "SQUADOPT_BACKEND_SITE_DATA_ROOT": "/site",
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT": "/snapshots",
        "SQUADOPT_BACKEND_HANDOFF_ROOT": "/handoffs",
    }
    plain = BackendConfig.from_environment(required)
    assert plain.artifact_root is None and plain.club_news_source is None
    configured = BackendConfig.from_environment(
        {
            **required,
            "SQUADOPT_BACKEND_ARTIFACT_ROOT": " /repo/artifacts ",
            "SQUADOPT_BACKEND_CLUB_NEWS_SOURCE": "/repo/data/sample/club_news_v1.fixture.json",
        }
    )
    assert configured.artifact_root == Path("/repo/artifacts")
    assert configured.club_news_source == Path("/repo/data/sample/club_news_v1.fixture.json")
    with pytest.raises(BackendConfigError):
        BackendConfig.from_environment({})
