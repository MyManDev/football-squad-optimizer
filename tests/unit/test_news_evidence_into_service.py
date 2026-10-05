"""Coded club news and its companions reach the advice service bound, or not at all.

Each test starts from captures and artifacts written under a temporary directory and reads
them the way the advice worker does, through ``load_switch_inputs``. Nothing reaches a
network and no model is called.
"""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_rotation_capture import (
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
)
from tests.unit.test_club_news_coding_versions import _document, _response
from tests.unit.test_football_bundle import add_quiet_news
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle_switches import baseline, cache_key, load
from tests.unit.test_football_minute_integration import captured_files
from tests.unit.test_football_publication import publication_case as publication_case
from tests.unit.test_news_capture_binding import case as binding_case
from tests.unit.test_news_capture_binding import load_case, publish_case

from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.application.weekly_plan import rotation_artifact
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import read_inputs
from squadopt.live.football_artifact import (
    FootballForecast,
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.platform import advice_switches as switches
from squadopt.platform.football_bundle import seal_football_bundle
from squadopt.platform.football_minute_basis import load_football_minute_basis

CLUB = "Club 1"
NEWS_COMPLETED = "2026-09-22T11:00:00Z"


def export_news(case, mode: str, *, completed: str = NEWS_COMPLETED) -> tuple[Path, dict]:
    """Code one club for the bundle fixture's decision and export where the service looks."""
    response = _response()
    raw = json.loads(response.text)
    if mode == "quiet":
        raw["claims"] = []
    else:
        for claim in raw["claims"]:
            claim.update(
                player_name="Player 1",
                team_name=CLUB,
                quote="This invented sentence is absent from the held source.",
            )
    version = ROTATION_CLAIM_CODING_CONTRACT_VERSION
    news = write_club_news_capture(
        case["snapshot_root"],
        documents=(replace(_document(), club=CLUB),),
        coded=(
            CodedClub(
                CLUB,
                replace(response, text=json.dumps(raw)),
                version,
                coding_prompt_sha256(contract_version=version),
            ),
        ),
        clubs_declared=(CLUB,),
        clubs_covered=(CLUB,),
        captured_at_utc=completed,
    )
    outputs = export_rotation_evidence(
        RotationExportRequest(
            "2026-27",
            6,
            "2026-09-23T12:00:00Z",
            case["snapshot_id"],
            case["snapshot_root"],
            None,
            case["artifact_root"] / switches.ROTATION_DIRECTORY,
            club_news_snapshot=news.snapshot_id,
        ),
        repository_commit="0" * 40,
    )
    return case["snapshot_root"] / news.snapshot_id, outputs


def edit_manifest(outputs: dict, **changes: object) -> None:
    document = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    document.update(changes)
    outputs["manifest_path"].write_text(json.dumps(document), encoding="utf-8")


def word_notes(selected: switches.AdviceSwitchInputs) -> list[str]:
    return [note for note in selected.notes if note.startswith("managers_word")]


def participation_audit(selected: switches.AdviceSwitchInputs) -> dict[str, Any]:
    assert selected.football is not None
    return selected.football.projection.diagnostics["participation_evidence"]


# --- step 32: the served handoff is the one the bundle names ------------------------


@pytest.mark.parametrize("served_as", ["forecast_fingerprint", "bundle_fingerprint"])
def test_sealed_bundle_refuses_a_projection_named_by_another_fingerprint(
    case, tmp_path: Path, served_as: str
) -> None:
    """A sealed bundle is served only beside the baseline handoff it was sealed with.

    If this fails, a projection identified by the football forecast's own fingerprint or by
    the bundle marker's digest would be accepted as the baseline, so football advice could
    be attached to a baseline nobody sealed it against.
    """
    add_quiet_news(case, tmp_path)
    ready = seal_football_bundle(**case)
    inputs, projection = baseline(case)
    forecast = read_football_forecast(
        football_artifact_path(case["artifact_root"], case["snapshot_id"]), inputs
    )
    # The forecast's own first-week projection files its fingerprint under the handoff key,
    # so handing that projection over as the baseline is the mistake this guards against.
    assert forecast.projection.diagnostics["projection_handoff_fingerprint"] == forecast.fingerprint
    wrong = {
        "forecast_fingerprint": forecast.fingerprint,
        "bundle_fingerprint": ready.fingerprint,
    }[served_as]
    assert wrong != ready.handoff_fingerprint
    # The same sealed bundle is served when the projection names the sealed handoff.
    assert load(case, inputs=inputs, projection=projection).football is not None

    changed = replace(
        projection,
        diagnostics={**projection.diagnostics, "projection_handoff_fingerprint": wrong},
    )
    saved = changed.table.copy(deep=True)
    selected = load(case, inputs=inputs, projection=changed)

    assert selected.football is None and not selected.football_components_bound
    assert selected.football_bundle_sha256 is None
    assert selected.manager_words is None and selected.rotation_table_sha256 is None
    assert any("differs from the served baseline handoff" in note for note in selected.notes)
    assert selected.decision_information(case["snapshot_id"]) is None
    with pytest.raises(switches.SwitchInputUnavailable):
        switches.switch_identity(selected, model="football")
    assert switches.switch_identity(selected, model="current") == {}
    assert_frame_equal(changed.table, saved, check_exact=True)


# --- step 33: four news states beside a served football forecast --------------------


@pytest.mark.parametrize(
    ("state", "words", "covered", "bound", "note"),
    [
        ("no_news", None, None, False, "no club-news source configured"),
        ("quiet", (), (CLUB,), True, None),
        ("all_refused", (), (), True, None),
        (
            "wrong_decision",
            None,
            None,
            False,
            "The rotation roster snapshot differs from this decision capture.",
        ),
        (
            "wrong_news_capture",
            None,
            None,
            False,
            "The rotation manifest does not bind the configured news capture time.",
        ),
    ],
)
def test_news_states_beside_a_football_forecast_are_told_apart_where_the_code_can(
    case,
    state: str,
    words: tuple[()] | None,
    covered: tuple[str, ...] | None,
    bound: bool,
    note: str | None,
) -> None:
    """Each news state leaves its own trace in the switch inputs, and none stops football.

    If this fails, a week with no news, a quiet week, a week whose every quote was refused
    and a table bound to something else would stop being distinguishable to the operator,
    or an unbound table would be reported as bound coach news.

    The wrong binding is pinned twice because the code answers it twice: a table whose roster
    is another decision's, and a table coded from another news capture.
    """
    source: Path | None = None
    digest: str | None = None
    if state != "no_news":
        source, outputs = export_news(case, "all_refused" if state == "all_refused" else "quiet")
        manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
        assert manifest["claims_coded"] == 0
        digest = manifest["table_sha256"]
        if state == "wrong_decision":
            edit_manifest(outputs, roster_snapshot_id="fpl-live-20260922T115900Z-000000000000")
        elif state == "wrong_news_capture":
            edit_manifest(outputs, club_news_snapshot_id="club-news-20260922T105900Z-000000000000")

    selected = load(case, configured=source)

    assert selected.football is not None and selected.football_components_bound
    info = selected.decision_information(case["snapshot_id"])
    assert info is not None and info["minute_components_bound"] is True
    held = selected.manager_words
    observed = (
        None if held is None else held.words,
        None if held is None else held.clubs_covered,
        selected.rotation_table_sha256,
        info["coach_news_bound"],
        word_notes(selected),
        participation_audit(selected)["statement_outcomes"],
    )
    assert observed == (
        words,
        covered,
        digest if bound else None,
        bound,
        [] if note is None else [f"managers_word: {note}"],
        [],
    )
    assert participation_audit(selected)["rotation_table_sha256"] == (digest if bound else None)
    if not bound:
        # What is published cannot tell a refused table from a week with no news at all.
        assert info == load(case).decision_information(case["snapshot_id"])


# --- step 34: why the minute companion was not used reaches the audit ---------------


def minute_statement_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], FootballForecast, Path, dict[str, Any], dict[str, Any]]:
    """One verified minute statement beside a real capture, forecast and companion.

    The served forecast reader and the table reader are replaced, as the neighbouring tests
    replace them. The companion loader, its source capture and the binding are real.
    """
    artifacts, snapshots, inputs, football, words, path = captured_files(tmp_path)
    source = tmp_path / "club_news_v1.fixture.json"
    source.write_text("{}", encoding="utf-8")
    table, manifest = rotation_artifact(
        artifacts / switches.ROTATION_DIRECTORY, inputs.season, 6, inputs.snapshot_id
    )
    table.parent.mkdir(parents=True)
    table.write_text("rows", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "table_sha256": "d" * 64,
                "season": inputs.season,
                "target_gameweek": 6,
                "roster_snapshot_id": inputs.snapshot_id,
                "source_snapshot_ids": [inputs.snapshot_id],
            }
        ),
        encoding="utf-8",
    )
    words = replace(words, source_label=source.name)
    monkeypatch.setattr(switches, "read_football_forecast", lambda *_: football)
    monkeypatch.setattr(switches, "load_manager_words", lambda *_a, **_k: words)
    arguments: dict[str, Any] = {
        "artifact_root": artifacts,
        "club_news_source": source,
        "snapshot_root": snapshots,
        "inputs": inputs,
        "projection": football.projection,
    }
    served_path = path.with_name(inputs.snapshot_id + ".json")
    served = json.loads(served_path.read_text(encoding="utf-8"))
    companion = json.loads(path.read_text(encoding="utf-8"))
    return arguments, football, path, served, companion


@pytest.mark.parametrize(
    ("damage", "reason", "digest_held"),
    [
        ("missing", "missing_components", False),
        ("unreadable", "unreadable_components", False),
        # Reached only when no snapshot root is given at all, which the service's own
        # signature does not offer. A root that lacks the capture is the next case.
        ("no_snapshot_root", "missing_source_snapshot", True),
        ("source_capture_absent", "invalid_components_or_source", True),
        ("stale", "invalid_components_or_source", True),
        ("rebound", "invalid_components_or_source", True),
    ],
)
def test_minute_companion_refusal_reason_survives_to_the_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
    reason: str,
    digest_held: bool,
) -> None:
    """The loader's reason for refusing the companion is the reason the audit records.

    If this fails, a minute statement would go unapplied with a wrong or missing reason, and
    an operator could not tell an absent companion from an unreadable, unsourced, stale or
    re-bound one. The forecast itself must stay served in every case.
    """
    arguments, football, path, served, companion = minute_statement_inputs(tmp_path, monkeypatch)
    inputs = arguments["inputs"]
    if damage == "missing":
        path.unlink()
    elif damage == "unreadable":
        # A directory under the companion's name exists and cannot be read as a file.
        path.unlink()
        path.mkdir()
    elif damage == "no_snapshot_root":
        arguments["snapshot_root"] = None
    elif damage == "source_capture_absent":
        arguments["snapshot_root"] = tmp_path / "another-snapshot-root"
        arguments["snapshot_root"].mkdir()
    elif damage == "stale":
        # The companion of an older forecast for the same capture, valid on its own terms.
        older = dict(served, training_rows=served["training_rows"] - 1)
        companion["forecast_fingerprint"] = forecast_digest(older)
        assert companion["forecast_fingerprint"] != served["fingerprint"]
        companion["fingerprint"] = forecast_digest(companion)
        path.write_text(json.dumps(companion), encoding="utf-8")
    else:
        # A real later capture of the same payloads, and a companion re-addressed to it.
        held = read_snapshot(arguments["snapshot_root"], inputs.snapshot_id)
        other = write_snapshot(
            arguments["snapshot_root"],
            source="fpl-live",
            captured_at_utc="2026-09-22T12:30:00+00:00",
            payloads=dict(held.payloads),
        )
        assert other.snapshot_id != inputs.snapshot_id
        companion.update(
            source_snapshot_id=other.snapshot_id,
            source_fingerprint=other.fingerprint,
            captured_at_utc=other.captured_at_utc,
        )
        companion["fingerprint"] = forecast_digest(companion)
        path.write_text(json.dumps(companion), encoding="utf-8")

    selected = switches.load_switch_inputs(**arguments)
    forecast = selected.football
    assert forecast is not None
    loaded = load_football_minute_basis(
        artifact_root=arguments["artifact_root"],
        snapshot_root=arguments["snapshot_root"],
        inputs=inputs,
        football=forecast,
    )

    assert loaded.basis is None and loaded.reason == reason
    audit = participation_audit(selected)
    assert audit["minute_basis"]["available"] is False
    assert audit["minute_basis"]["reason"] == loaded.reason
    (unapplied,) = audit["unapplied_statements"]
    assert unapplied["reason"] == loaded.reason
    (outcome,) = audit["statement_outcomes"]
    assert (outcome["applied"], outcome["reason"]) == (False, loaded.reason)
    assert audit["minutes_reestimated"] is False
    assert not selected.football_components_bound
    assert (selected.football_components_sha256 is not None) is digest_held
    assert selected.football_components_sha256 == loaded.components_sha256
    info = selected.decision_information(inputs.snapshot_id)
    assert info is not None and info["minute_components_bound"] is False
    assert info["coach_news_bound"] is True
    assert_frame_equal(forecast.horizon.table, football.horizon.table, check_exact=True)


def test_minute_statement_is_applied_when_the_companion_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same statement is applied when nothing is wrong with the companion.

    If this fails, the refusal cases above prove nothing: the statement would be unapplied
    for a reason of its own, and the companion's reason would only happen to be reported.
    """
    arguments, football, _, _, _ = minute_statement_inputs(tmp_path, monkeypatch)

    selected = switches.load_switch_inputs(**arguments)

    audit = participation_audit(selected)
    assert selected.football_components_bound
    assert audit["minute_basis"]["available"] is True and audit["minute_basis"]["reason"] is None
    assert audit["unapplied_statements"] == []
    (outcome,) = audit["statement_outcomes"]
    assert outcome["applied"] is True
    assert audit["minutes_reestimated"] is True
    assert selected.football is not None
    assert not selected.football.horizon.table.equals(football.horizon.table)


# --- step 35: a table for another decision of the same gameweek ---------------------


def test_rotation_table_of_another_decision_in_the_same_gameweek_is_not_selected(
    tmp_path: Path,
) -> None:
    """One news capture exported for one decision does not serve a later decision.

    If this fails, a second decision capture in the same gameweek would pick up words that
    were joined to the first capture's roster and availability, either by finding the first
    export by name or by accepting a copy of it under its own name.
    """
    state = binding_case(tmp_path, "claims")
    request, first_inputs, artifacts, source = state
    result = publish_case(state)
    root = request.snapshot_root
    later = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc="2026-09-12T15:10:00Z",
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    )
    second_inputs = read_inputs(
        read_snapshot(root, later.snapshot_id), season=SEASON, gameweek=TARGET_GAMEWEEK
    )
    assert second_inputs.snapshot_id != first_inputs.snapshot_id
    assert second_inputs.deadline.gameweek == first_inputs.deadline.gameweek == TARGET_GAMEWEEK

    def load_second() -> switches.AdviceSwitchInputs:
        return switches.load_switch_inputs(
            artifact_root=artifacts,
            club_news_source=source,
            snapshot_root=root,
            inputs=second_inputs,
            projection=object(),
        )

    # The export is real and is selected for the decision it was made for.
    first = load_case(state)
    assert first.manager_words is not None and first.manager_words.words
    assert first.rotation_table_sha256 is not None

    table, manifest = rotation_artifact(
        artifacts / switches.ROTATION_DIRECTORY,
        SEASON,
        TARGET_GAMEWEEK,
        source.name,
        decision_snapshot_id=second_inputs.snapshot_id,
    )
    assert table.name != result["table_path"].name and not table.exists()
    unexported = load_second()
    assert unexported.manager_words is None and unexported.rotation_table_sha256 is None
    assert word_notes(unexported) == [f"managers_word: no rotation table {table.name}"]

    shutil.copyfile(result["table_path"], table)
    shutil.copyfile(result["manifest_path"], manifest)
    copied = load_second()
    assert copied.manager_words is None and copied.rotation_table_sha256 is None
    assert word_notes(copied) == [
        "managers_word: The rotation roster snapshot differs from this decision capture."
    ]
    # The copy changed nothing for the decision the table belongs to.
    assert load_case(state).rotation_table_sha256 == first.rotation_table_sha256


# --- step 39: the information revision follows the bound table ----------------------


def test_information_revision_and_football_identity_follow_the_bound_rotation_table(
    case,
) -> None:
    """Equal inputs give an equal revision; another bound table gives another one.

    If this fails, either two readers of the same files would disagree about the revision
    they publish, or a football answer computed from one week's coded news could be served
    from the cache as the answer for a different table.
    """
    quiet_source, quiet = export_news(case, "quiet")
    refused_source, _ = export_news(case, "all_refused", completed="2026-09-22T11:05:00Z")
    snapshot_id = case["snapshot_id"]

    first = load(case, configured=quiet_source)
    again = load(case, configured=quiet_source)
    other = load(case, configured=refused_source)

    manifest = json.loads(quiet["manifest_path"].read_text(encoding="utf-8"))
    assert first.rotation_table_sha256 == again.rotation_table_sha256 == manifest["table_sha256"]
    assert other.rotation_table_sha256 not in (None, first.rotation_table_sha256)
    # Only the table differs: the forecast and its companion are the same bytes.
    assert first.football is not None and other.football is not None
    assert first.football.fingerprint == other.football.fingerprint
    assert first.football_components_sha256 == other.football_components_sha256

    information = first.decision_information(snapshot_id)
    assert information is not None
    assert again.decision_information(snapshot_id) == information
    assert other.decision_information(snapshot_id)["revision"] != information["revision"]
    identity = switches.switch_identity(first, model="football")
    assert switches.switch_identity(again, model="football") == identity
    other_identity = switches.switch_identity(other, model="football")
    assert other_identity != identity
    assert cache_key(case, other_identity) != cache_key(case, identity)

    # The digest alone is enough: nothing else about the first reading is changed here.
    redigested = replace(first, rotation_table_sha256=other.rotation_table_sha256)
    assert redigested.decision_information(snapshot_id)["revision"] != information["revision"]
    changed = switches.switch_identity(redigested, model="football")
    assert changed != identity
    assert changed["model"]["rotation_table_sha256"] == other.rotation_table_sha256
    assert {
        key for key in identity["model"] if identity["model"][key] != changed["model"][key]
    } == {"rotation_table_sha256"}
    assert switches.switch_identity(first, model="current") == {}
