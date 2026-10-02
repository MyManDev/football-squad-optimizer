"""Selection is distinct from claim validation and keeps unknown source text honest."""

import json

import pytest
from tests.unit.test_club_news_provider import CONFIG, ROSTER, _Recorder

from squadopt.data.sources.club_news import RawDocument
from squadopt.data.sources.club_news_selection import select_coding_documents
from squadopt.platform.club_news_provider import code_week_by_club, coding_input_fingerprint


def document(title, path="news/update", published=None):
    meta = (
        ""
        if published is None
        else f'<meta property="article:published_time" content="{published}">'
    )
    raw = (
        f"<html><head>{meta}</head><body><h1>{title}</h1><p>Player update.</p></body></html>"
    ).encode()
    url = "https://club.example/" + path
    return RawDocument(
        "Liverpool",
        url,
        url,
        200,
        "text/html",
        len(raw),
        "2026-10-02T10:00:00Z",
        raw,
        title.encode(),
    )


@pytest.mark.parametrize(
    "title,path",
    [
        ("Liverpool FC Women beat Arsenal", "news/women-result"),
        ("U21s: team news", "news/update"),
        ("Internationals: roundup", "news/update"),
        ("Match report: Liverpool win", "news/update"),
        ("Latest news", "news"),
        ("Tickets available", "news/tickets/update"),
    ],
)
def test_explicit_irrelevant_pages_are_not_sent_to_a_provider(title, path):
    doc = document(title, path)
    selection = select_coding_documents((doc,))
    assert selection.documents == () and not selection.decisions[0].selected
    recorder = _Recorder()
    coded, refused = code_week_by_club(recorder, CONFIG, (doc,), ROSTER)
    assert recorder.calls == [] and coded == () and len(refused) == 1


def test_mentioning_academy_or_international_players_does_not_drop_first_team_news():
    doc = document("Team news: academy graduate available after international duty")
    selection = select_coding_documents((doc,))
    assert selection.documents == (doc,)
    assert selection.decisions[0].reason == "availability_or_upcoming_match"


@pytest.mark.parametrize(
    "date,reason",
    [
        ("2026-09-01T10:00:00Z", "publication_outside_current_window"),
        ("2026-10-03T10:00:00Z", "publication_after_observation"),
    ],
)
def test_verified_source_date_is_used_without_substituting_fetch_time(date, reason):
    doc = document("Team news", published=date)
    selection = select_coding_documents((doc,), as_of="2026-10-02T10:00:00Z")
    assert selection.documents == () and selection.decisions[0].reason == reason


def test_unknown_date_or_scope_is_not_declared_upcoming_or_absent():
    doc = document("A message from the club")
    selection = select_coding_documents((doc,), as_of="2026-10-02T10:00:00Z")
    assert selection.documents == (doc,)
    assert selection.decisions[0].reason == "eligible_unclassified"


def test_index_bytes_remain_in_selection_audit_but_only_article_goes_to_coding():
    index, article = document("Updates", "news"), document("Fitness update", "news/fitness")
    selection = select_coding_documents((index, article))
    assert selection.documents == (article,)
    assert selection.decisions[0].reason == "discovery_index_with_selected_articles"
    assert len(selection.decisions) == 2


def test_selection_policy_versions_invalidate_reuse(monkeypatch):
    import squadopt.platform.club_news_provider as provider

    doc = document("Fitness update")
    before = coding_input_fingerprint(CONFIG, (doc,), ROSTER)
    monkeypatch.setattr(provider, "SELECTION_POLICY_VERSION", "different_selection_policy")
    assert coding_input_fingerprint(CONFIG, (doc,), ROSTER) != before


def test_empty_model_response_stays_successful_zero_claims():
    doc = document("Fitness update")
    coded, refused = code_week_by_club(_Recorder(), CONFIG, (doc,), ROSTER)
    assert refused == () and len(coded) == 1
    assert json.loads(coded[0].response.text)["claims"] == []
