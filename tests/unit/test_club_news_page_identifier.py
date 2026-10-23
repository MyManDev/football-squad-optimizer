"""A publisher's malformed WebPage id needs independent same-page corroboration."""

import hashlib
import json

import pytest

from squadopt.data.sources.club_news_metadata import publication_metadata

URL = "https://club.example/news/first-team/team-news/"
IDENTIFIER = "https://club.example-news-first-team-team-news-"
INSTANT = "2026-10-21T17:02:41.251Z"


def _source(**changes: str) -> bytes:
    fields = {
        "canonical": URL,
        "graph_url": URL,
        "graph_title": "Team news",
        "headline": "Team news",
        "identifier": IDENTIFIER,
        "page_type": "WebPage",
        "published": INSTANT,
        "displayed": INSTANT,
        "extra_head": "",
        "extra_body": "",
    } | changes
    article = {
        "@type": "NewsArticle",
        "headline": fields["headline"],
        "mainEntityOfPage": {"@type": fields["page_type"], "@id": fields["identifier"]},
        "datePublished": fields["published"],
    }
    if "article_url" in changes:
        article["url"] = changes["article_url"]
    return (
        f'<head><link rel="canonical" href="{fields["canonical"]}">'
        f'<meta property="og:url" content="{fields["graph_url"]}">'
        f'<meta property="og:title" content="{fields["graph_title"]}">'
        f"{fields['extra_head']}</head><body><main>"
        f'<time datetime="{fields["displayed"]}">hours ago</time>'
        f'<script type="application/ld+json">{json.dumps(article)}</script>'
        f"{fields['extra_body']}</main></body>"
    ).encode()


def _streamed(**changes: str) -> bytes:
    metadata, body = _source(**changes).split(b"</head><body>", 1)
    return b"<html><head></head><body>" + metadata.removeprefix(b"<head>") + body + b"</html>"


def test_one_page_identifier_is_bound_by_its_canonical_title_and_displayed_instant():
    raw = _source()
    result = publication_metadata(raw, "text/html", URL)
    assert result.verified
    assert result.published_at_utc == "2026-10-21T17:02:41.251000Z"
    assert result.published_precision == "instant"
    assert result.source == "jsonld_datePublished"
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("source", [_source, _streamed])
@pytest.mark.parametrize(
    "changes",
    [
        {"canonical": ""},
        {"canonical": "https://other.example/news/first-team/team-news/"},
        {"canonical": "/news/first-team/other/"},
        {"graph_url": ""},
        {"graph_url": "https://other.example/news/first-team/team-news/"},
        {"graph_url": "/news/first-team/other/"},
        {"graph_title": "Another article"},
        {"headline": ""},
        {"identifier": "https://club.example-news-first-team-other-"},
        {"identifier": "https://other.example-news-first-team-team-news-"},
        {"identifier": "https://club.example/news/first-team/other/"},
        {"page_type": "Thing"},
        {"article_url": IDENTIFIER},
        {"displayed": ""},
        {"displayed": "2026-10-22T17:02:41.251Z"},
        {"published": "2026-10-21T17:02:41.251"},
        {"published": "2026-10-21", "displayed": "2026-10-21"},
        {"extra_head": '<meta property="og:url" content="/other">'},
        {"extra_head": '<meta property="og:title" content="Another article">'},
        {"extra_body": '<time datetime="2026-10-22T17:02:41.251Z"></time>'},
        {
            "extra_body": '<script type="application/ld+json">'
            '{"@type":"NewsArticle","url":"https://club.example/related",'
            '"datePublished":"2026-10-21T17:02:41.251Z"}</script>'
        },
    ],
)
def test_missing_conflicting_or_unrelated_identity_evidence_is_refused(changes, source):
    assert not publication_metadata(source(**changes), "text/html", URL).verified


def test_a_displayed_time_is_not_a_publication_field_without_date_published():
    raw = _source().replace(b'"datePublished"', b'"dateModified"')
    assert not publication_metadata(raw, "text/html", URL).verified


def test_a_query_string_is_not_erased_to_make_the_page_identifier_match():
    assert not publication_metadata(_source(), "text/html", URL + "?article=other").verified


def test_nested_article_content_cannot_supply_the_page_identity():
    raw = _source().replace(b"<head>", b"<body><article>").replace(b"</head>", b"</article>")
    assert not publication_metadata(raw, "text/html", URL).verified


def test_streamed_metadata_at_body_root_needs_the_same_corroboration():
    raw = _streamed()
    result = publication_metadata(raw, "text/html", URL)
    assert result.verified
    assert result.published_at_utc == "2026-10-21T17:02:41.251000Z"
    assert result.source == "jsonld_datePublished"


def test_streamed_metadata_never_overrides_a_head_identity():
    raw = _streamed().replace(
        b"<head></head>", b'<head><link rel="canonical" href="/different"></head>'
    )
    assert not publication_metadata(raw, "text/html", URL).verified


def test_another_explicit_publication_field_still_causes_a_conflict():
    raw = _source(
        extra_head='<meta property="article:published_time" content="2026-10-22T17:02:41.251Z">'
    )
    result = publication_metadata(raw, "text/html", URL)
    assert not result.verified
    assert result.reason == "publication_metadata_conflict"


def test_excessively_nested_html_is_refused_before_page_identity_is_used():
    raw = _source(extra_body="<div>" * 10_000 + "</div>" * 10_000)
    result = publication_metadata(raw, "text/html", URL)
    assert not result.verified
    assert result.reason == "publication_metadata_invalid"
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
