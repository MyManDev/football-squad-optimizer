"""A quiet real-capture shape remains bound; late model completion cannot be backdated."""

import hashlib
import json
from dataclasses import replace

import pytest
from tests.fixtures.synthetic_rotation_capture import CAPTURED_AT, DEADLINE, SEASON, TARGET_GAMEWEEK
from tests.unit.test_rotation_export_from_capture import (
    COMMIT,
    NEWS_CAPTURED_AT,
    _decision,
    _documents,
    _response_for,
)

from squadopt.application.manager_words import SOURCE_CHECK_NOTHING_CITED
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.live import read_inputs
from squadopt.platform.advice_switches import _rotation_manifest_binding, load_switch_inputs

CLUB = "Man Utd"
BINDING_FIELDS = ("club_news_snapshot_id", "club_news_captured_at_utc")


def case(tmp_path, mode="quiet", *, completed=NEWS_CAPTURED_AT):
    root = tmp_path / "snapshots"
    decision_id = _decision(root)
    response = _response_for(CLUB)
    payload = json.loads(response.text)
    assert payload["claims"]
    if mode == "quiet":
        payload["claims"] = []
    elif mode == "all_refused":
        for claim in payload["claims"]:
            claim["quote"] = "This invented sentence is absent from the held source."
    response = replace(response, text=json.dumps(payload))
    news = write_club_news_capture(
        root,
        documents=tuple(document for document in _documents() if document.club == CLUB),
        coded=(
            CodedClub(
                club=CLUB,
                response=response,
                prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                prompt_sha256=coding_prompt_sha256(
                    contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
                ),
            ),
        ),
        clubs_declared=(CLUB,),
        clubs_covered=(CLUB,),
        captured_at_utc=completed,
    )
    inputs = read_inputs(read_snapshot(root, decision_id), season=SEASON, gameweek=TARGET_GAMEWEEK)
    artifacts = tmp_path / "artifacts"
    request = RotationExportRequest(
        SEASON,
        TARGET_GAMEWEEK,
        DEADLINE,
        decision_id,
        root,
        None,
        artifacts / "rotation",
        club_news_snapshot=news.snapshot_id,
    )
    return request, inputs, artifacts, root / news.snapshot_id


def publish_case(state):
    return export_rotation_evidence(state[0], repository_commit=COMMIT)


def load_case(state):
    request, inputs, artifacts, source = state
    return load_switch_inputs(
        artifact_root=artifacts,
        club_news_source=source,
        snapshot_root=request.snapshot_root,
        inputs=inputs,
        projection=object(),
    )


def read_manifest(result):
    path = result["manifest_path"]
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(result, document):
    result["manifest_path"].write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("mode,covered", [("quiet", (CLUB,)), ("all_refused", ())])
def test_zero_claim_capture_keeps_successful_coverage_distinct_from_refused_quotes(
    tmp_path, mode, covered
):
    state = case(tmp_path, mode)
    result = publish_case(state)
    manifest = read_manifest(result)
    assert manifest["claims_coded"] == 0
    assert manifest["source_snapshot_ids"] == [state[1].snapshot_id]
    assert manifest["club_news_snapshot_id"] == state[3].name
    assert manifest["club_news_captured_at_utc"] == NEWS_CAPTURED_AT
    table = read_rotation_evidence_artifact(result["table_path"], result["manifest_path"])
    assert not table.rotation_claim_observed.any()
    assert tuple(table.attrs["clubs_covered"]) == covered
    found = load_case(state)
    assert found.manager_words is not None
    assert found.manager_words.words == ()
    assert found.manager_words.clubs_covered == covered
    assert found.manager_words.source_check == SOURCE_CHECK_NOTHING_CITED
    assert found.rotation_table_sha256 == manifest["table_sha256"]


@pytest.mark.parametrize("completed", [CAPTURED_AT, "2026-09-12T15:01:00Z"])
def test_old_documents_coded_at_or_after_decision_are_refused_before_export(tmp_path, completed):
    state = case(tmp_path, completed=completed)
    with pytest.raises(DataError, match="must complete before"):
        publish_case(state)
    assert not state[0].output_dir.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"club_news_snapshot_id": "another-news-capture"},
        {"club_news_captured_at_utc": "2026-09-12T14:31:00Z"},
        {"club_news_captured_at_utc": "2026-09-12T14:30:00"},
        {"club_news_captured_at_utc": None},
        {"claims_coded": True},
        {"claims_coded": 1},
    ],
)
def test_quiet_manifest_cannot_change_capture_time_or_claim_count(tmp_path, changes):
    state = case(tmp_path)
    result = publish_case(state)
    manifest = read_manifest(result)
    manifest.update(changes)
    write_manifest(result, manifest)
    assert load_case(state).manager_words is None


def test_a_different_configured_capture_cannot_consume_the_quiet_binding(tmp_path):
    state = case(tmp_path)
    result = publish_case(state)
    manifest = read_manifest(result)
    with pytest.raises(ValueError, match="configured news capture"):
        _rotation_manifest_binding(
            manifest,
            state[1],
            "another-news-capture",
            news_captured_at_utc=NEWS_CAPTURED_AT,
        )


@pytest.mark.parametrize("mode", ["claims", "quiet"])
def test_v4_capture_manifest_cannot_strip_both_capture_binding_fields(tmp_path, mode):
    state = case(tmp_path, mode)
    result = publish_case(state)
    manifest = read_manifest(result)
    for field in BINDING_FIELDS:
        del manifest[field]
    write_manifest(result, manifest)
    with pytest.raises(DataError, match="capture binding"):
        read_rotation_evidence_artifact(result["table_path"], result["manifest_path"])
    assert load_case(state).manager_words is None


def test_v4_consumer_refuses_unbound_capture_even_when_origin_kind_was_stripped(tmp_path):
    state = case(tmp_path)
    result = publish_case(state)
    manifest = read_manifest(result)
    for field in (*BINDING_FIELDS, "club_news_source_kind"):
        manifest.pop(field)
    with pytest.raises(ValueError, match="must bind"):
        _rotation_manifest_binding(
            manifest, state[1], state[3].name, news_captured_at_utc=NEWS_CAPTURED_AT
        )


def test_actual_claim_rows_cannot_hide_behind_zero_claim_metadata(tmp_path):
    state = case(tmp_path, "claims")
    result = publish_case(state)
    table = read_rotation_evidence_artifact(result["table_path"], result["manifest_path"])
    assert table.rotation_claim_observed.any()
    table["source_snapshot_ids"] = state[1].snapshot_id
    raw = table.to_csv(index=False, lineterminator="\n").encode()
    result["table_path"].write_bytes(raw)
    manifest = read_manifest(result)
    manifest.update(
        claims_coded=0,
        source_snapshot_ids=[state[1].snapshot_id],
        table_sha256=hashlib.sha256(raw).hexdigest(),
    )
    write_manifest(result, manifest)
    with pytest.raises(DataError, match="claim count"):
        read_rotation_evidence_artifact(result["table_path"], result["manifest_path"])
    assert load_case(state).manager_words is None


def test_claim_manifest_missing_news_source_is_refused(tmp_path):
    state = case(tmp_path, "claims")
    result = publish_case(state)
    manifest = read_manifest(result)
    manifest["source_snapshot_ids"] = [state[1].snapshot_id]
    write_manifest(result, manifest)
    assert load_case(state).manager_words is None


def test_explicit_capture_metadata_cannot_be_consumed_as_a_fixture(tmp_path):
    state = case(tmp_path)
    result = publish_case(state)
    with pytest.raises(ValueError, match="configured news capture"):
        _rotation_manifest_binding(read_manifest(result), state[1], None)
