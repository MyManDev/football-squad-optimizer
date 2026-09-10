"""Tests for the settled-outcome accumulator: the reader, the join, and the refusals.

Every capture here is written by the test from hand-built payloads. Nothing reaches a
network, which is also the only way this can run in CI: `data/snapshots/` is gitignored, so
the artifacts this exports are produced on the machine that holds the captures, never here.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts.export_settled_outcomes import (
    _captures,
    _multiplier,
    pair_captures,
    table_name,
    write_artifact,
)

from squadopt.data.errors import DataSourceError, DataValidationError, DuplicateRecordsError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    live_event_outcomes,
    live_payload,
)
from squadopt.features.settled_outcomes import (
    SETTLED_OUTCOME_COLUMNS,
    build_settled_outcomes,
    read_settled_outcomes_artifact,
)
from squadopt.preflight.validator import compute_table_sha256

SEASON = "2026-27"
GAMEWEEK = 4
DEADLINE = "2026-09-12T17:30:00Z"
PRE_DEADLINE_CAPTURE = "2026-09-12T15:00:00Z"
SETTLED_CAPTURE = "2026-09-14T09:00:00Z"
COMMIT = "b" * 40

TEAMS: list[dict[str, Any]] = [{"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"}]


@pytest.mark.parametrize("anchor", ["pre", "settled"])
def test_weekly_export_respects_capture_cutoff_and_never_exports_target_week(
    root: Path, tmp_path: Path, anchor: str
) -> None:
    from squadopt.application.settled_outcomes import (
        SettledOutcomesRequest,
        export_settled_outcomes,
    )
    from squadopt.data.snapshots import list_snapshot_ids

    identifiers = list_snapshot_ids(root, source=FPL_LIVE_SOURCE)
    selected = identifiers[0 if anchor == "pre" else -1]
    # A future capture is held too, but its unusable domain payload must not enter this run.
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc="2026-10-01T12:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: b"{}"},
    )
    request = SettledOutcomesRequest(
        SEASON,
        root,
        tmp_path / "exports",
        tmp_path / "summary.json",
        tmp_path / "summary.md",
        COMMIT,
        selected,
        before_gameweek=GAMEWEEK,
    )
    same_week = export_settled_outcomes(request)
    assert same_week.gameweeks_exported == ()
    assert same_week.skipped and not (tmp_path / "exports").exists()
    from dataclasses import replace

    next_week = export_settled_outcomes(replace(request, before_gameweek=GAMEWEEK + 1))
    assert next_week.gameweeks_exported == (() if anchor == "pre" else (GAMEWEEK,))
    assert all(path.is_file() for path in next_week.output_paths)


def _element(code: int, *, element_id: int | None = None, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": code,
        "id": code if element_id is None else element_id,
        "first_name": "Given",
        "second_name": "Name",
        "team": 1,
        "element_type": 3,
        "now_cost": 55,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "news": "",
        "news_added": None,
    }
    record.update(overrides)
    return record


def _bootstrap(
    elements: list[dict[str, Any]],
    *,
    settled: bool = False,
    deadline: str = DEADLINE,
    gameweek: int = GAMEWEEK,
) -> bytes:
    document = {
        "teams": TEAMS,
        "elements": elements,
        "events": [
            {
                "id": gameweek - 1,
                "deadline_time": "2026-09-05T17:30:00Z",
                "finished": True,
                "data_checked": True,
            },
            {
                "id": gameweek,
                "deadline_time": deadline,
                "finished": settled,
                "data_checked": settled,
            },
            {
                "id": gameweek + 1,
                "deadline_time": "2026-09-18T17:30:00Z",
                "finished": False,
                "data_checked": False,
            },
        ],
    }
    return json.dumps(document).encode("utf-8")


def _live(stats_by_element: dict[int, dict[str, Any]]) -> bytes:
    document = {
        "elements": [
            {"id": element, "stats": stats} for element, stats in sorted(stats_by_element.items())
        ]
    }
    return json.dumps(document).encode("utf-8")


def _stats(minutes: int, starts: int, points: int, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"minutes": minutes, "starts": starts, "total_points": points}
    record.update(overrides)
    return record


# The three players every test below leans on: a starter, a substitute who came on, and one
# who was priced fully available and did not play at all.
ROSTER = [_element(101), _element(102), _element(103)]
OUTCOMES = {
    101: _stats(90, 1, 8),
    102: _stats(20, 0, 2),
    103: _stats(0, 0, 0),
}


@pytest.fixture(name="root")
def _root(tmp_path: Path) -> Path:
    root = tmp_path / "snapshots"
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=PRE_DEADLINE_CAPTURE,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER)},
    )
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=SETTLED_CAPTURE,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER, settled=True),
            live_payload(GAMEWEEK): _live(OUTCOMES),
        },
    )
    return root


# --- reading the settled live document --------------------------------------


def test_the_outcome_keys_on_the_persistent_code_not_the_element_id() -> None:
    """A row recorded this week is read again next season, when element ids have moved."""

    frame = live_event_outcomes(
        _live({7: _stats(90, 1, 8)}),
        _bootstrap([_element(118748, element_id=7)], settled=True),
        gameweek=GAMEWEEK,
    )

    assert frame["player_id"].tolist() == [118748]


def test_starting_is_read_and_appearing_is_derived() -> None:
    """Minutes cannot answer a rotation question: a substitute who played sixty is not a start."""

    frame = live_event_outcomes(
        _live({101: _stats(90, 1, 8), 102: _stats(60, 0, 5), 103: _stats(0, 0, 0)}),
        _bootstrap(ROSTER, settled=True),
        gameweek=GAMEWEEK,
    )

    assert frame["start"].tolist() == [True, False, False]
    assert frame["appearance"].tolist() == [True, True, False]


def test_a_live_payload_without_starts_stops_the_run_and_names_the_field() -> None:
    """A settled table whose start column is empty is the one table nobody can measure on."""

    document = {"elements": [{"id": 101, "stats": {"minutes": 90, "total_points": 8}}]}

    with pytest.raises(DataSourceError, match="starts"):
        live_event_outcomes(
            json.dumps(document).encode("utf-8"),
            _bootstrap(ROSTER, settled=True),
            gameweek=GAMEWEEK,
        )


def test_an_element_the_bootstrap_does_not_name_is_refused() -> None:
    """The two documents would be describing different squads."""

    with pytest.raises(DataSourceError, match="names no element 999"):
        live_event_outcomes(
            _live({999: _stats(90, 1, 8)}),
            _bootstrap(ROSTER, settled=True),
            gameweek=GAMEWEEK,
        )


def test_two_elements_sharing_one_code_are_refused() -> None:
    """Refused by the translation table, before the outcome join is ever reached.

    Which is why this reader carries no duplicate guard of its own: ``player_codes``
    refuses a repeated id *and* a repeated code, so no two elements can arrive at one
    player.
    """

    with pytest.raises(DuplicateRecordsError, match="one code is one player"):
        live_event_outcomes(
            _live({7: _stats(90, 1, 8), 8: _stats(45, 0, 2)}),
            _bootstrap([_element(500, element_id=7), _element(500, element_id=8)], settled=True),
            gameweek=GAMEWEEK,
        )


def test_a_stats_section_that_is_not_an_object_is_refused() -> None:
    document = {"elements": [{"id": 101, "stats": []}]}

    with pytest.raises(DataSourceError, match="'stats' section"):
        live_event_outcomes(
            json.dumps(document).encode("utf-8"),
            _bootstrap(ROSTER, settled=True),
            gameweek=GAMEWEEK,
        )


# --- the join ---------------------------------------------------------------


def _built(root: Path) -> pd.DataFrame:
    (pair,) = pair_captures(_captures(root))[0]
    availability = availability_snapshot(pair.pre_deadline.bootstrap)
    outcomes = live_event_outcomes(
        pair.settled.payloads[live_payload(pair.gameweek)],
        pair.settled.bootstrap,
        gameweek=pair.gameweek,
    )
    return build_settled_outcomes(
        outcomes, availability, _multiplier(availability), season=SEASON, gameweek=pair.gameweek
    )


def test_the_table_carries_its_declared_columns_in_order(root: Path) -> None:
    assert tuple(_built(root).columns) == SETTLED_OUTCOME_COLUMNS


def test_both_halves_of_a_row_are_present(root: Path) -> None:
    """What he did, beside what the week's own capture said he could do."""

    table = _built(root).set_index("player_id")

    assert table.loc[101, "start"]
    assert table.loc[101, "pre_deadline_status"] == "a"
    assert table.loc[101, "pre_deadline_availability_multiplier"] == 1.0
    assert not table.loc[103, "appearance"]
    assert table.loc[103, "pre_deadline_availability_multiplier"] == 1.0


def test_the_multiplier_is_the_rules_own_answer(tmp_path: Path) -> None:
    """Read from `apply_availability`, never reimplemented, so there is one of it."""

    availability = availability_snapshot(
        _bootstrap(
            [
                _element(101, status="a", chance_of_playing_next_round=100),
                _element(102, status="i", chance_of_playing_next_round=0),
                _element(103, status="d", chance_of_playing_next_round=75),
            ]
        )
    )

    multiplier = _multiplier(availability)

    assert multiplier[101] == 1.0
    assert multiplier[102] == 0.0
    assert multiplier[103] == pytest.approx(0.75)


def test_a_player_the_pre_deadline_capture_never_listed_has_no_availability() -> None:
    """Absent, not zero: he was not in the squad that week, so nothing was said about him."""

    availability = availability_snapshot(_bootstrap([_element(101)]))
    outcomes = live_event_outcomes(
        _live({101: _stats(90, 1, 8), 102: _stats(45, 0, 3)}),
        _bootstrap([_element(101), _element(102)], settled=True),
        gameweek=GAMEWEEK,
    )

    table = build_settled_outcomes(
        outcomes, availability, _multiplier(availability), season=SEASON, gameweek=GAMEWEEK
    ).set_index("player_id")

    assert pd.isna(table.loc[102, "pre_deadline_status"])
    assert pd.isna(table.loc[102, "pre_deadline_chance_of_playing"])
    assert pd.isna(table.loc[102, "pre_deadline_availability_multiplier"])
    # And his outcome is still recorded in full: the absence is on the availability half only.
    assert table.loc[102, "minutes"] == 45


def test_a_listed_player_the_rule_priced_nothing_for_is_refused() -> None:
    """A gap in the rule's own output is not an absent record, and must not read as one."""

    availability = availability_snapshot(_bootstrap([_element(101)]))
    outcomes = live_event_outcomes(
        _live({101: _stats(90, 1, 8)}), _bootstrap([_element(101)], settled=True), gameweek=GAMEWEEK
    )

    with pytest.raises(DataValidationError, match="priced no multiplier"):
        build_settled_outcomes(outcomes, availability, {}, season=SEASON, gameweek=GAMEWEEK)


def test_an_empty_outcome_is_refused_rather_than_written_as_zero_rows() -> None:
    availability = availability_snapshot(_bootstrap([_element(101)]))
    empty = pd.DataFrame(columns=["player_id", "appearance", "start", "minutes", "total_points"])

    with pytest.raises(DataValidationError, match="no players"):
        build_settled_outcomes(
            empty, availability, _multiplier(availability), season=SEASON, gameweek=GAMEWEEK
        )


# --- pairing the two captures -----------------------------------------------


def test_a_settled_gameweek_pairs_with_the_last_capture_before_its_deadline(root: Path) -> None:
    pairs, skipped = pair_captures(_captures(root))

    # The previous gameweek is settled too -- a real bootstrap says so -- and is skipped
    # because no capture here carries its live document. Named, never silent.
    assert [reason.split(":")[0] for reason in skipped] == ["gw03"]
    (pair,) = pairs
    assert pair.gameweek == GAMEWEEK
    assert pair.pre_deadline.captured_at_utc == PRE_DEADLINE_CAPTURE
    assert pair.settled.captured_at_utc == SETTLED_CAPTURE


def test_an_unsettled_gameweek_is_not_exported(tmp_path: Path) -> None:
    """`finished` and `data_checked` together decide, and bonus lands between them."""

    root = tmp_path / "snapshots"
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=PRE_DEADLINE_CAPTURE,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER)},
    )
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=SETTLED_CAPTURE,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER),
            live_payload(GAMEWEEK): _live(OUTCOMES),
        },
    )

    pairs, skipped = pair_captures(_captures(root))

    # Gameweek 4 is finished-but-unchecked here, which is where bonus has not landed yet, so
    # it is not among the pairs at all -- not even as a skip, because it is not settled.
    assert [pair.gameweek for pair in pairs] == []
    assert not any(reason.startswith("gw04") for reason in skipped)


def test_a_settled_week_with_no_live_document_is_skipped_with_its_reason(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=PRE_DEADLINE_CAPTURE,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER)},
    )
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=SETTLED_CAPTURE,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER, settled=True)},
    )

    pairs, skipped = pair_captures(_captures(root))

    assert pairs == ()
    assert any("event-gw04-live.json" in reason for reason in skipped)


def test_a_settled_week_captured_only_after_its_deadline_is_skipped(tmp_path: Path) -> None:
    """Without the capture the week was decided from, the availability that applied is gone."""

    root = tmp_path / "snapshots"
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=SETTLED_CAPTURE,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(ROSTER, settled=True),
            live_payload(GAMEWEEK): _live(OUTCOMES),
        },
    )

    pairs, skipped = pair_captures(_captures(root))

    assert pairs == ()
    assert any("before its deadline" in reason for reason in skipped)


def test_a_capture_with_no_bootstrap_is_skipped_not_fatal(root: Path) -> None:
    write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc="2026-09-14T10:00:00Z",
        payloads={"fixtures.json": b"{}"},
    )

    assert len(_captures(root)) == 2


# --- the artifact -----------------------------------------------------------


def _write(root: Path, output: Path) -> tuple[Path, Path, dict[str, object]]:
    (pair,) = pair_captures(_captures(root))[0]
    table = _built(root)
    name = table_name(SEASON, pair)
    manifest = write_artifact(
        table, output, name, pair=pair, season=SEASON, repository_commit=COMMIT
    )
    return output / f"{name}.csv", output / f"{name}.manifest.json", manifest


def test_the_artifact_reads_back_through_its_own_contract(root: Path, tmp_path: Path) -> None:
    table_path, manifest_path, manifest = _write(root, tmp_path / "out")

    restored = read_settled_outcomes_artifact(table_path, manifest_path)

    assert tuple(restored.columns) == SETTLED_OUTCOME_COLUMNS
    assert len(restored) == manifest["row_count"] == 3
    assert restored.attrs["repository_commit"] == COMMIT


def test_the_manifest_carries_the_counts_the_record_is_checked_by(
    root: Path, tmp_path: Path
) -> None:
    _, _, manifest = _write(root, tmp_path / "out")

    assert manifest["appearances"] == 2
    assert manifest["starts"] == 1
    assert manifest["players_without_pre_deadline_availability"] == 0
    assert manifest["source_snapshot_ids"] == [
        manifest["pre_deadline_snapshot_id"],
        manifest["settled_snapshot_id"],
    ]


def test_re_running_is_a_no_op_that_returns_the_same_digest(root: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    _, _, first = _write(root, output)
    _, _, second = _write(root, output)

    assert first["table_sha256"] == second["table_sha256"]
    assert first["generated_at_utc"] == second["generated_at_utc"]


def test_a_different_table_under_the_same_name_is_refused(root: Path, tmp_path: Path) -> None:
    """Create-once: an artifact is never overwritten in place, and the refusal names the
    two digests so the reader can tell which bytes are on disk and which were refused."""

    output = tmp_path / "out"
    table_path, _, manifest = _write(root, output)
    table_path.write_text(table_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="never") as refusal:
        _write(root, output)
    assert compute_table_sha256(table_path) in str(refusal.value)
    assert str(manifest["table_sha256"]) in str(refusal.value)


def test_a_replay_at_another_commit_is_accepted_and_the_first_manifest_stands(
    root: Path, tmp_path: Path
) -> None:
    """Friday's run writes the pair at one commit; every later run of the week is at another.

    The commit is provenance, not identity: the same two captures joined by the same code
    contract give the same table bytes whatever revision ran the join, so the second run is
    a replay and the first manifest stands, exactly as the advice record treats its clock.
    """

    output = tmp_path / "out"
    table_path, manifest_path, first = _write(root, output)
    before = table_path.read_bytes()
    (pair,) = pair_captures(_captures(root))[0]

    second = write_artifact(
        _built(root),
        output,
        table_name(SEASON, pair),
        pair=pair,
        season=SEASON,
        repository_commit="c" * 40,
        generated_at_utc="2026-09-15T00:00:00Z",
    )

    assert second == first
    assert second["repository_commit"] == COMMIT
    assert table_path.read_bytes() == before
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == first


def test_a_manifest_naming_another_capture_is_refused_with_the_field_named(
    root: Path, tmp_path: Path
) -> None:
    """Identity fields still refuse: a manifest built from another capture is a different
    artifact even when its table bytes happen to agree, and the message says which field."""

    output = tmp_path / "out"
    _, manifest_path, manifest = _write(root, output)
    altered = {**manifest, "pre_deadline_snapshot_id": "fpl-live-20260101T000000Z-000000000000"}
    manifest_path.write_text(json.dumps(altered), encoding="utf-8")

    with pytest.raises(RuntimeError, match="pre_deadline_snapshot_id"):
        _write(root, output)


def test_a_tampered_table_fails_its_checksum(root: Path, tmp_path: Path) -> None:
    table_path, manifest_path, _ = _write(root, tmp_path / "out")
    rows = table_path.read_text(encoding="utf-8").replace(",90,", ",89,")
    table_path.write_text(rows, encoding="utf-8")

    with pytest.raises(DataValidationError, match="checksum"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_a_manifest_whose_counts_disagree_with_the_table_is_refused(
    root: Path, tmp_path: Path
) -> None:
    table_path, manifest_path, manifest = _write(root, tmp_path / "out")
    document = dict(manifest)
    document["starts"] = 2
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataValidationError, match="starts"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_a_manifest_missing_a_required_field_is_refused(root: Path, tmp_path: Path) -> None:
    table_path, manifest_path, manifest = _write(root, tmp_path / "out")
    document = {key: value for key, value in manifest.items() if key != "settled_snapshot_id"}
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataValidationError, match="missing required fields"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_a_pre_deadline_capture_that_is_not_before_the_deadline_is_refused(
    root: Path, tmp_path: Path
) -> None:
    """The whole point of the availability half: it has to have been knowable."""

    table_path, manifest_path, manifest = _write(root, tmp_path / "out")
    document = dict(manifest)
    document["pre_deadline_captured_at_utc"] = "2026-09-13T09:00:00Z"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataValidationError, match="not earlier than the deadline"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_a_settled_capture_before_the_deadline_is_refused(root: Path, tmp_path: Path) -> None:
    table_path, manifest_path, manifest = _write(root, tmp_path / "out")
    document = dict(manifest)
    document["settled_captured_at_utc"] = "2026-09-12T16:00:00Z"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataValidationError, match="not later than the deadline"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_a_rearranged_table_is_refused(root: Path, tmp_path: Path) -> None:
    table_path, manifest_path, _ = _write(root, tmp_path / "out")
    table = pd.read_csv(table_path)
    reversed_columns = list(reversed(list(table.columns)))
    table.loc[:, reversed_columns].to_csv(table_path, index=False, lineterminator="\n")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    import hashlib

    manifest["table_sha256"] = hashlib.sha256(table_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DataValidationError, match="declared order"):
        read_settled_outcomes_artifact(table_path, manifest_path)


def test_the_artifact_name_carries_the_settled_capture_it_was_built_from(root: Path) -> None:
    """A week re-read from a later capture is a different artifact, not an overwrite."""

    (pair,) = pair_captures(_captures(root))[0]

    name = table_name(SEASON, pair)

    assert name.startswith(f"settled_outcomes_v1_{SEASON}_gw04_")
    assert name.endswith(pair.settled.snapshot_id[-12:])
