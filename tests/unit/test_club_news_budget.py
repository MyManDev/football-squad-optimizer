"""Bounded model calls and reuse of unchanged evidence, without paid providers."""

from dataclasses import replace

import pytest
from tests.unit.test_club_news_provider import CONFIG, ROSTER, _document, _Recorder

from squadopt.data.sources.club_news_capture import capture_payloads
from squadopt.platform.club_news_provider import code_week_by_club

TARGET = {
    "season": "2026-27",
    "gameweek": 6,
    "deadline": "2026-10-10T10:00:00Z",
    "as_of": "2026-10-02T00:00:00Z",
}


def test_zero_budget_does_not_contact_model():
    recorder = _Recorder()
    coded, refused = code_week_by_club(
        recorder, CONFIG, [_document("Arsenal", "a")], ROSTER, max_calls=0
    )
    assert not recorder.calls and not coded
    assert "budget" in refused[0][1]


def test_failed_calls_spend_budget_and_never_silently_retry():
    recorder = _Recorder(fails_for="Arsenal")
    coded, refused = code_week_by_club(
        recorder,
        CONFIG,
        [_document("Arsenal", "a"), _document("Everton", "e")],
        ROSTER,
        max_calls=1,
    )
    assert len(recorder.calls) == 1
    assert not coded and len(refused) == 2


def test_unchanged_predeadline_target_reuses_original_response():
    recorder = _Recorder()
    config = replace(CONFIG, model_identifier="m", target_context=TARGET)
    documents = [_document("Arsenal", "a")]
    first, refused = code_week_by_club(recorder, config, documents, ROSTER)
    assert not refused and len(recorder.calls) == 1
    # A check clock moving within the same target does not manufacture new content.
    later = replace(config, target_context={**TARGET, "as_of": "2026-10-02T01:00:00Z"})
    second, refused = code_week_by_club(
        recorder, later, documents, ROSTER, previous=first, max_calls=0
    )
    assert second == first and not refused and len(recorder.calls) == 1
    payloads = capture_payloads(
        documents, second, clubs_declared=["Arsenal"], clubs_covered=["Arsenal"]
    )
    assert b"request_fingerprint" in payloads["index.json"]


@pytest.mark.parametrize(
    "different", ["target", "source", "model", "provider", "format", "mime", "roster"]
)
def test_reuse_cannot_cross_changed_inputs(different):
    recorder = _Recorder()
    config = replace(CONFIG, model_identifier="m", target_context=TARGET)
    docs = [_document("Arsenal", "a")]
    roster = ROSTER
    first, _ = code_week_by_club(recorder, config, docs, roster)
    if different == "target":
        config = replace(config, target_context={**TARGET, "gameweek": 7})
    elif different == "source":
        docs = [_document("Arsenal", "changed")]
    elif different == "model":
        config = replace(config, model_identifier="other")
    elif different == "provider":
        config = replace(config, provider="other")
    elif different == "format":
        config = replace(config, response_format="json_object")
    elif different == "mime":
        docs = [replace(docs[0], content_type="text/plain")]
    else:
        roster = (replace(ROSTER[0], player_id=99), *ROSTER[1:])
    second, refused = code_week_by_club(recorder, config, docs, roster, previous=first, max_calls=0)
    assert not second and len(refused) == 1 and len(recorder.calls) == 1


def test_no_target_context_means_no_reuse_even_for_same_bytes():
    recorder = _Recorder()
    config = replace(CONFIG, model_identifier="m")
    docs = [_document("Arsenal", "a")]
    first, _ = code_week_by_club(recorder, config, docs, ROSTER)
    second, refused = code_week_by_club(recorder, config, docs, ROSTER, previous=first, max_calls=0)
    assert not second and refused


def test_mime_normalization_and_roster_order_do_not_spend_another_call():
    recorder = _Recorder()
    config = replace(CONFIG, model_identifier="m", target_context=TARGET)
    doc = _document("Arsenal", "a")
    first, _ = code_week_by_club(recorder, config, (doc,), ROSTER)
    equivalent = replace(doc, content_type=" TEXT/HTML ; charset=UTF-8")
    second, refused = code_week_by_club(
        recorder, config, (equivalent,), tuple(reversed(ROSTER)), previous=first, max_calls=0
    )
    assert second == first and not refused and len(recorder.calls) == 1


@pytest.mark.parametrize("as_of", [TARGET["deadline"], "2026-10-11T00:00:00Z"])
def test_expired_target_cannot_reuse_or_spend_a_call(as_of):
    recorder = _Recorder()
    config = replace(CONFIG, model_identifier="m", target_context=TARGET)
    docs = (_document("Arsenal", "a"),)
    first, _ = code_week_by_club(recorder, config, docs, ROSTER)
    expired = replace(config, target_context={**TARGET, "as_of": as_of})
    coded, refused = code_week_by_club(recorder, expired, docs, ROSTER, previous=first, max_calls=1)
    assert not coded and len(recorder.calls) == 1
    assert len(refused) == 1 and "precede" in refused[0][1]


def test_invalid_club_input_does_not_cost_other_clubs_or_a_model_call():
    recorder = _Recorder()
    invalid = replace(_document("Arsenal", "a"), readable=b"\xff")
    coded, refused = code_week_by_club(
        recorder, CONFIG, (invalid, _document("Everton", "e")), ROSTER, max_calls=1
    )
    assert recorder.calls == [("Everton",)]
    assert [entry.club for entry in coded] == ["Everton"]
    assert len(refused) == 1 and refused[0][0] == "Arsenal" and "UTF-8" in refused[0][1]
