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
        # The same rule by its other names: a section in the path, or a labelled title.
        ("Scholar signs first deal", "news/academy/scholar-signs"),
        ("Cup run continues", "news/youth/cup-run"),
        ("Under-18s: late winner", "news/update"),
        ("Liverpool Ladies name squad", "news/update"),
        ("New home kit on sale", "news/shop/home-kit"),
        ("Matchday lounge packages", "news/hospitality/lounge"),
        ("International report: three called up", "news/update"),
        ("Highlights: Liverpool 2-0", "news/update"),
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


@pytest.mark.parametrize(
    "title,path",
    [
        ("Injury update ahead of the weekend", "news/injury-update"),
        ("Press conference: every word on fitness", "news/presser"),
        ("Match preview: all you need to know", "news/preview"),
        ("Squad update", "news/squad"),
        ("A message from the club", "news/first-team/message"),
    ],
)
def test_first_team_availability_and_upcoming_match_pages_are_named_as_such(title, path):
    doc = document(title, path)
    selection = select_coding_documents((doc,))
    assert selection.documents == (doc,)
    assert selection.decisions[0].reason == "availability_or_upcoming_match"


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


@pytest.mark.parametrize(
    "path,published",
    [
        ("news/fitness-update", None),
        ("news", "2026-10-02T09:59:00Z"),
    ],
)
def test_section_heading_does_not_hide_an_article(path, published):
    doc = document("News", path, published)
    selection = select_coding_documents((doc,), as_of="2026-10-02T10:00:00Z")
    assert selection.documents == (doc,)


def test_referrals_share_priority_and_request_cap_with_index_articles(monkeypatch):
    from dataclasses import replace
    from datetime import date

    from squadopt.platform import club_news_fetch as fetch

    source = fetch.ClubSource("Liverpool", "https://club.example/news", date(2026, 10, 1))
    index = document("Latest news", "news")
    markup = b'<a href="/news/a">First team news</a><a href="/news/b">Club update</a>'
    index = replace(index, content=markup, byte_length=len(markup))
    requested = []

    def read(article, **kwargs):
        requested.append(article.url)
        return document("Team news", article.url.partition("club.example/")[2])

    monkeypatch.setattr(fetch, "fetch_club_document", read)
    docs, refused = fetch._follow_articles(
        source,
        index,
        claimed={source.url},
        opener=lambda *a, **k: None,
        now=lambda: None,
        sleeper=lambda delay: None,
        check_robots=False,
        manners=fetch.HostManners(articles_per_host=1),
        additional_urls=("https://club.example/news/ordinary-referral",),
    )
    assert requested == ["https://club.example/news/a"]
    assert len(docs) == 1 and refused == []
