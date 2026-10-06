"""Source facts authorize only explicit current-league evidence, never model confidence."""

import hashlib
import json
from dataclasses import replace

import pandas as pd
import pytest
from tests.unit.test_club_news_coding_versions import _document, _response

from squadopt.data.sources.club_news import ClaimResponse, ClubNewsError, RosterPlayer
from squadopt.data.sources.club_news_claims import parse_claim_response, resolve_span
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    build_user_content,
    locate_claim_response,
)
from squadopt.data.sources.club_news_metadata import publication_metadata
from squadopt.data.sources.club_news_scope import verified_fixture_scope
from squadopt.features.rotation_evidence import claim_targets_next_fixture

URL = "https://club.example/arsenal/news"


@pytest.mark.parametrize(
    "address,verified",
    [
        (URL, True),
        ("https://CLUB.EXAMPLE/arsenal/news#article", True),
        ("/arsenal/news#article", True),
        ("#article", True),
        ("../arsenal/news", False),
        ("news", False),
        ("/arsenal/../arsenal/news", False),
        ("//club.example/arsenal/news", False),
        ("https://other.example/arsenal/news", False),
        ("https://club.example/arsenal/news?different-page=1", False),
        ("https://user@club.example/arsenal/news", False),
    ],
)
def test_jsonld_page_identity_uses_only_explicit_same_page_references(address, verified):
    metadata = json.dumps(
        {
            "@type": "NewsArticle",
            "url": address,
            "datePublished": "2026-09-12T13:00:00Z",
        }
    )
    raw = f'<script type="application/ld+json">{metadata}</script>'.encode()
    assert publication_metadata(raw, "text/html", URL).verified is verified


@pytest.mark.parametrize(
    "content,media,expected,precision",
    [
        (
            '<meta property="article:published_time" content="2026-09-12T14:00:00+01:00">',
            "text/html",
            "2026-09-12T13:00:00Z",
            "instant",
        ),
        (
            '<time itemprop="datePublished" datetime="2026-09-12"></time>',
            "text/html",
            "2026-09-12",
            "day",
        ),
        (
            '<script type="application/ld+json">{"@type":"NewsArticle",'
            '"datePublished":"2026-09-12T13:00:00Z"}</script>',
            "text/html",
            "2026-09-12T13:00:00Z",
            "instant",
        ),
        ("Published: 2026-09-12\nThe manager spoke.", "text/plain", "2026-09-12", "day"),
        (
            "<rss><channel><item><pubDate>Sat, 12 Sep 2026 13:00:00 GMT</pubDate>"
            "</item></channel></rss>",
            "application/rss+xml",
            "2026-09-12T13:00:00Z",
            "instant",
        ),
    ],
)
def test_only_explicit_publication_fields_preserve_actual_precision(
    content, media, expected, precision
):
    raw = content.encode()
    result = publication_metadata(raw, media, URL)
    assert result.verified
    assert (result.published_at_utc, result.published_precision) == (expected, precision)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "content,media",
    [
        ("The manager spoke on 2026-09-12.", "text/plain"),
        ('<meta property="article:modified_time" content="2026-09-12T13:00:00Z">', "text/html"),
        ('<time datetime="2026-09-12T13:00:00Z">today</time>', "text/html"),
        ('<meta property="article:published_time" content="2026-09-12T13:00:00">', "text/html"),
        ('<meta property="article:published_time" content="invented">', "text/html"),
        (
            '<meta property="article:published_time" content="2026-09-12">'
            '<time itemprop="datePublished" datetime="2026-09-13"></time>',
            "text/html",
        ),
        (
            '<script type="application/ld+json">{"@type":"NewsArticle",'
            '"url":"https://elsewhere.example/story","datePublished":"2026-09-12"}</script>',
            "text/html",
        ),
        ('<script type="application/ld+json">{bad}</script>', "text/html"),
        (
            '<script type="application/ld+json">{"@type":"NewsArticle",'
            '"datePublished":"2026-09-12","datePublished":"2026-09-13"}</script>',
            "text/html",
        ),
        (
            '<script type="application/ld+json">[{"@type":"NewsArticle",'
            '"datePublished":"2026-09-12"},{"@type":"NewsArticle",'
            '"datePublished":"2026-09-12"}]</script>',
            "text/html",
        ),
        (
            '<meta property="article:published_time" content="2026-09-12" content="2026-09-13">',
            "text/html",
        ),
        (
            "<rss><channel><item><pubDate>2026-09-12</pubDate></item>"
            "<item><pubDate>2026-09-12</pubDate></item></channel></rss>",
            "application/rss+xml",
        ),
        ('<!DOCTYPE rss [<!ENTITY x "2026-09-12">]><rss/>', "application/rss+xml"),
    ],
)
def test_missing_invalid_ambiguous_or_updated_metadata_cannot_invent_a_dateline(content, media):
    result = publication_metadata(content.encode(), media, URL)
    assert not result.verified
    assert (result.published_at_utc, result.published_precision) == (None, "unknown")


@pytest.mark.parametrize(
    "quote",
    [
        "Saka will miss the cup match.",
        "Saka will not play for the national team.",
        "Saka missed the previous league match.",
        "Saka will not travel.",
        "Saka might miss the next league match.",
        "If he is injured, Saka will miss the next league match.",
        "Saka is not ruled out for the next league match.",
        "Saka will miss the cup match but play in the next league match.",
        "Saka will start in the next league match.",
        "Saka cannot play the full upcoming league match.",
        "Saka is out of contention to start in the next league match.",
        "Saka might miss the next Premier League fixture.",
        "Saka is not available for the next Premier League match if he fails a late test.",
        "Saka misses the next Premier League match after the cup match.",
        "Timber is sidelined for the next Premier League match.",
        "Saka is not sidelined for the next Premier League match.",
        # The new wordings negated, and said by another player about another player.
        "Saka is available for the next Premier League match.",
        "Saka will play a part in the next Premier League match.",
        "Saka won't miss the next Premier League match.",
        "Saka will not be sidelined for the next Premier League match.",
        "Saka says Timber misses the next Premier League match.",
        "Saka says Timber is sidelined for the next Premier League match.",
        "Saka says Timber will play no part in the next Premier League match.",
        "Saka says Timber is not available for the next Premier League match.",
        "Saka says Timber isn't available for the next Premier League match.",
    ],
)
def test_absence_scope_refuses_other_competitions_past_and_ambiguous_words(quote):
    assert not verified_fixture_scope(quote.encode(), "stated_expected_absent", player_name="Saka")[
        1
    ]
    document = _document(quote)
    claim = parse_claim_response(
        locate_claim_response(_response(quote=quote, label="stated_expected_absent"), (document,)),
        (document,),
    )[0]
    assert not claim.scope_verified


def test_current_absence_and_source_publication_survive_without_moving_quote_offsets():
    quote = "Saka will miss the next Premier League match."
    document = _document(quote)
    claim = parse_claim_response(
        locate_claim_response(_response(quote=quote, label="stated_expected_absent"), (document,)),
        (document,),
    )[0]
    assert claim.scope_verified and claim.publication_verified
    assert claim.fixture_scope == "upcoming_premier_league"
    assert resolve_span(document.readable, claim) == quote.encode()
    assert claim.span_start == document.readable.index(quote.encode())
    assert claim.publication_source_sha256 == hashlib.sha256(document.content).hexdigest()


def test_model_dateline_cannot_replace_missing_or_disagreeing_source_metadata():
    quote = "Saka will miss the next league match."
    for prefix, expected in [
        ("", None),
        ("Published: 2026-09-11T13:00:00Z\n", "2026-09-11T13:00:00Z"),
    ]:
        raw = (prefix + quote).encode()
        document = replace(_document(quote), content=raw, readable=raw, byte_length=len(raw))
        claim = parse_claim_response(
            locate_claim_response(
                _response(quote=quote, label="stated_expected_absent"), (document,)
            ),
            (document,),
        )[0]
        assert not claim.publication_verified
        assert claim.published_at_utc == expected


def test_a_model_cannot_attest_source_scope_it_did_not_declare():
    document = _document()
    value = json.loads(_response().text)
    value["claims"][0]["fixture_scope"] = "unspecified"
    response = ClaimResponse(json.dumps(value), "synthetic", "1")
    claim = parse_claim_response(locate_claim_response(response, (document,)), (document,))[0]
    assert not claim.scope_verified


@pytest.mark.parametrize("version", ["rotation_claim_coding_v1", "rotation_claim_coding_v2"])
def test_legacy_captures_remain_readable_without_silent_new_attestation(version):
    document = _document("Saka will miss the next league match.")
    response = _response(
        version=version,
        quote="Saka will miss the next league match.",
        label="stated_expected_absent",
    )
    claim = parse_claim_response(locate_claim_response(response, (document,)), (document,))[0]
    assert claim.published_at_utc == "2026-09-12T13:00:00Z"
    assert not claim.publication_verified and not claim.scope_verified
    assert claim.fixture_scope == "unspecified"


def test_explicit_target_context_and_source_publication_are_separate_from_quotable_text():
    roster = (RosterPlayer(1, "Saka", "Arsenal"),)
    document = _document()
    context = {
        "season": "2026-27",
        "gameweek": 5,
        "deadline": "2026-09-13T10:00:00Z",
        "as_of": "2026-09-12T14:00:00Z",
    }
    content = build_user_content((document,), roster, target_context=context)
    assert "# Decision context (not source evidence)" in content
    assert json.dumps(context, sort_keys=True) in content
    assert '"published_at_utc": "2026-09-12T13:00:00Z"' in content
    assert document.readable.decode() in content
    assert content == build_user_content(
        (document,), roster, target_context=dict(reversed(list(context.items())))
    )
    with pytest.raises(ClubNewsError, match="precede"):
        build_user_content(
            (document,), roster, target_context={**context, "as_of": context["deadline"]}
        )


def test_current_contract_requires_source_scope_field():
    response = _response()
    value = json.loads(response.text)
    assert value["contract_version"] == ROTATION_CLAIM_CODING_CONTRACT_VERSION
    del value["claims"][0]["fixture_scope"]
    with pytest.raises(ClubNewsError, match="fixture_scope"):
        locate_claim_response(replace(response, text=json.dumps(value)), (_document(),))


@pytest.mark.parametrize(
    "past,extra,precision,expected",
    [
        ("2026-09-10T14:00:00Z", None, "instant", True),
        ("2026-09-12T09:00:00Z", None, "instant", False),
        (None, None, "instant", False),
        ("2026-09-10T14:00:00Z", "2026-09-14T14:00:00Z", "instant", False),
        ("2026-09-10T14:00:00Z", None, "day", False),
    ],
)
def test_next_match_cannot_skip_an_intervening_or_undated_fixture(past, extra, precision, expected):
    rows = [
        {"team_id": 3, "gameweek": 3, "fixture_id": 10, "kickoff_time_utc": past},
        {"team_id": 3, "gameweek": 4, "fixture_id": 11, "kickoff_time_utc": "2026-09-13T14:00:00Z"},
    ]
    if extra:
        rows.append({"team_id": 3, "gameweek": 4, "fixture_id": 12, "kickoff_time_utc": extra})
    assert (
        claim_targets_next_fixture(
            pd.DataFrame(rows),
            team_code=3,
            target_gameweek=4,
            captured_at_utc="2026-09-12T15:00:00Z",
            published_at_utc="2026-09-11T13:00:00Z",
            published_precision=precision,
        )
        is expected
    )


@pytest.mark.parametrize("published", ["not-a-date", "2026-09-11T13:00:00", "2026-99-99"])
def test_malformed_or_timezone_missing_publication_cannot_bind_to_a_fixture(published):
    fixtures = pd.DataFrame(
        [
            {
                "team_id": 3,
                "gameweek": 4,
                "fixture_id": 11,
                "kickoff_time_utc": "2026-09-13T14:00:00Z",
            }
        ]
    )
    assert not claim_targets_next_fixture(
        fixtures,
        team_code=3,
        target_gameweek=4,
        captured_at_utc="2026-09-12T15:00:00Z",
        published_at_utc=published,
        published_precision="instant",
    )


@pytest.mark.parametrize(
    "quote,disposition,expected",
    [
        (
            "Saka cannot complete the full next Premier League match.",
            "stated_full_match_unavailable",
            True,
        ),
        (
            "Saka cannot play ninety minutes in the next league match.",
            "stated_full_match_unavailable",
            True,
        ),
        (
            "Saka can complete the full next Premier League match.",
            "stated_full_match_unavailable",
            False,
        ),
        (
            "Saka will play sixty minutes in the next league match.",
            "stated_full_match_unavailable",
            False,
        ),
        (
            "Saka might not complete the full next Premier League match.",
            "stated_full_match_unavailable",
            False,
        ),
        (
            "Saka cannot complete the full next Premier League fixture.",
            "stated_full_match_unavailable",
            True,
        ),
        (
            "Saka cannot play ninety minutes in the next league fixture.",
            "stated_full_match_unavailable",
            True,
        ),
        (
            "In the next league fixture, Saka cannot play 90 minutes.",
            "stated_full_match_unavailable",
            True,
        ),
        (
            "Saka might not complete the full next Premier League fixture.",
            "stated_full_match_unavailable",
            False,
        ),
        (
            "Saka will miss the next Premier League fixture.",
            "stated_full_match_unavailable",
            False,
        ),
        ("Saka misses the next Premier League match.", "stated_full_match_unavailable", False),
        ("Saka is sidelined for the next Premier League match.", "stated_rotation_risk", False),
        ("Saka will play no part in the next Premier League match.", "stated_rotation_risk", False),
        ("Saka cannot complete the full next Premier League match.", "invented_label", False),
        (
            "Saka will miss the next league match in the Nations League.",
            "stated_expected_absent",
            False,
        ),
        (
            "Saka will miss the friendly before the next league match.",
            "stated_expected_absent",
            False,
        ),
        (
            "Saka will miss the international qualifiers before the next league match.",
            "stated_expected_absent",
            False,
        ),
        (
            "Saka will miss training before the next Premier League match.",
            "stated_expected_absent",
            False,
        ),
        (
            "Saka cannot play 90 minutes in training before the next Premier League match.",
            "stated_full_match_unavailable",
            False,
        ),
        (
            "Saka will miss the bus before the next Premier League match.",
            "stated_expected_absent",
            False,
        ),
        (
            "Saka cannot play 90 minutes at a charity event before the next Premier League match.",
            "stated_full_match_unavailable",
            False,
        ),
    ],
)
def test_scope_rechecks_disposition_meaning_and_international_competitions(
    quote,
    disposition,
    expected,
):
    assert verified_fixture_scope(quote.encode(), disposition, player_name="Saka")[1] is expected


@pytest.mark.parametrize("disposition", ["stated_expected_absent", "stated_full_match_unavailable"])
@pytest.mark.parametrize(
    "subject,other,expected",
    [
        ("Saka", "", True),
        ("SAKA", "", True),
        ("Saka", "Timber is available. ", False),
        ("Timber", "Saka is available. ", False),
        ("Timber", "", False),
        ("Saka and Timber", "", False),
        ("Saka says Timber", "", False),
        ("He", "", False),
        ("Sakamoto", "", False),
        ("Bukayo Saka", "", False),
    ],
)
def test_numeric_scope_binds_the_entire_predicate_to_the_exact_named_player(
    disposition, subject, other, expected
):
    predicate = (
        "will miss the next Premier League match"
        if disposition == "stated_expected_absent"
        else "cannot complete the full next Premier League match"
    )
    quote = f"{other}{subject} {predicate}."
    assert verified_fixture_scope(quote.encode(), disposition, player_name="Saka")[1] is expected
    document = _document(quote)
    claim = parse_claim_response(
        locate_claim_response(_response(quote=quote, label=disposition), (document,)), (document,)
    )[0]
    assert claim.scope_verified is expected
    assert resolve_span(document.readable, claim) == quote.encode()


@pytest.mark.parametrize(
    "quote,name,expected",
    [
        ("In the next league match, Saka cannot play 90 minutes.", "Saka", True),
        ("In the next league match, Timber cannot play 90 minutes.", "Saka", False),
        ("Saka cannot play 90 minutes in the next league match, but Timber can.", "Saka", False),
        ("B.Fernandes cannot play 90 minutes in the next league match.", "B.Fernandes", True),
        ("A.Fernandes cannot play 90 minutes in the next league match.", "B.Fernandes", False),
        ("Fernandes cannot play 90 minutes in the next league match.", "B.Fernandes", False),
        ("Saka cannot play 90 minutes in the next league match.", None, False),
    ],
)
def test_numeric_subject_binding_does_not_infer_aliases_or_transfer_clauses(quote, name, expected):
    assert (
        verified_fixture_scope(quote.encode(), "stated_full_match_unavailable", player_name=name)[1]
        is expected
    )


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("Saka is a rotation risk for the next Premier League match.", True),
        ("Saka will be rested for the next league match.", True),
        ("Saka will be rotated in the upcoming league game.", True),
        ("Saka will be rested for the next league fixture.", True),
        ("Saka is a rotation risk for the next league fixture.", True),
        ("Saka is fit for the next league match. Timber is a rotation risk.", False),
        ("Timber is a rotation risk for the next league match.", False),
        ("Saka is fit for the next league match.", False),
        ("Saka and Timber are rotation risks for the next league match.", False),
        ("Saka is not a rotation risk for the next league match.", False),
        ("Saka will not be rested for the next league match.", False),
        ("Saka may be rested for the next league match.", False),
        ("Saka may be rested for the next league fixture.", False),
        ("Saka will be rested for the cup match.", False),
        ("Saka was rested for the previous league match.", False),
        ("He will be rested for the next league match.", False),
    ],
)
def test_rotation_captain_restriction_needs_the_named_players_explicit_predicate(quote, expected):
    disposition = "stated_rotation_risk"
    assert verified_fixture_scope(quote.encode(), disposition, player_name="Saka")[1] is expected
    assert not verified_fixture_scope(quote.encode(), disposition)[1]
    document = _document(quote)
    claim = parse_claim_response(
        locate_claim_response(_response(quote=quote, label=disposition), (document,)), (document,)
    )[0]
    assert claim.scope_verified is expected
    assert resolve_span(document.readable, claim) == quote.encode()
