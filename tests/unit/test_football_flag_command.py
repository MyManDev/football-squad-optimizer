"""Retained capture selection refuses forbidden clocks before outcome IO or fitting."""

import json
from types import SimpleNamespace

import pytest
from scripts import build_football_forecast as command


def target():
    return SimpleNamespace(
        metadata=SimpleNamespace(captured_at_utc="2026-10-15T13:00:00Z"),
        payloads={
            "bootstrap-static.json": json.dumps(
                {"events": [{"deadline_time": "2026-08-14T17:30:00Z"}]}
            ).encode()
        },
    )


@pytest.mark.parametrize(
    "captured", ["2025-10-01T10:00:00Z", "2026-10-15T13:00:00Z", "2026-10-16T10:00:00Z"]
)
def test_other_season_and_target_time_cannot_open_even_one_outcome(tmp_path, monkeypatch, captured):
    for identifier, clock in (("before", "2026-09-01T12:00:00Z"), ("settled", captured)):
        directory = tmp_path / identifier
        directory.mkdir()
        (directory / "metadata.json").write_text(json.dumps({"captured_at_utc": clock}))
    monkeypatch.setattr(command, "read_snapshot", lambda *a: pytest.fail("No payload IO allowed"))
    with pytest.raises(ValueError, match="no outcome payload"):
        command._flag_pairs(tmp_path, target(), [["before", "settled"]])


def test_capture_paths_cannot_escape_the_given_root(tmp_path, monkeypatch):
    monkeypatch.setattr(command, "read_snapshot", lambda *a: pytest.fail("No payload IO allowed"))
    with pytest.raises(ValueError, match="direct child"):
        command._flag_pairs(tmp_path, target(), [["../other", "settled"]])


def test_complete_clock_preflight_precedes_all_verified_capture_reads(tmp_path, monkeypatch):
    clocks = {"before": "2026-09-01T12:00:00Z", "settled": "2026-09-05T12:00:00Z"}
    for identifier, clock in clocks.items():
        directory = tmp_path / identifier
        directory.mkdir()
        (directory / "metadata.json").write_text(json.dumps({"captured_at_utc": clock}))
    calls = []

    def verified(root, identifier):
        calls.append(identifier)
        return identifier

    monkeypatch.setattr(command, "read_snapshot", verified)
    assert command._flag_pairs(tmp_path, target(), [["before", "settled"]]) == (
        ("before", "settled"),
    )
    assert calls == ["before", "settled"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--flag-decision-at", "2026-10-15T14:00:00Z"],
        ["--flag-training-capture", "before", "settled"],
        [
            "--flag-training-capture",
            "before",
            "settled",
            "--flag-decision-at",
            "2026-10-15T14:00:00Z",
        ],
    ],
)
def test_incomplete_flag_selection_cannot_read_a_capture(monkeypatch, extra):
    monkeypatch.setattr(command, "read_snapshot", lambda *a: pytest.fail("No capture IO allowed"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_football_forecast",
            "--snapshot-root",
            "unused",
            "--snapshot-id",
            "unused",
            "--archive-root",
            "unused",
            "--artifact-root",
            "unused",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        command.main()
    assert error.value.code == 2


@pytest.mark.parametrize("retained", [False, True])
def test_explicit_2025_26_native_history_is_admitted_only_to_retained_experimental_roles(
    monkeypatch, retained
):
    from squadopt.application import football_live

    class ArchiveReadReached(Exception):
        pass

    requested = []

    def archive(root, *, seasons):
        requested.append(seasons)
        raise ArchiveReadReached

    monkeypatch.setattr(football_live, "archive_history", archive)
    monkeypatch.setattr(football_live, "infer_season", lambda snapshot: "2026-27")
    monkeypatch.setattr(
        football_live,
        "read_inputs",
        lambda *a, **kw: SimpleNamespace(
            captured_at_utc="2026-10-15T13:00:00Z", deadline=SimpleNamespace(gameweek=7)
        ),
    )
    expected = ArchiveReadReached if retained else ValueError
    with pytest.raises(expected):
        football_live.produce_football_components(
            object(),
            object(),
            role_minutes=True,
            retained_role_history=retained,
            training_seasons=("2022-23", "2023-24", "2024-25", "2025-26", "2026-27"),
        )
    assert (
        requested == [("2022-23", "2023-24", "2024-25", "2025-26")] if retained else not requested
    )
