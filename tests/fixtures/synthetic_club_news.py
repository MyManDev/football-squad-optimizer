"""Build the committed synthetic club-news fixture, deterministically.

No random seed and no third-party bytes: every document here was written for this file,
and the offsets are computed from the text as it is assembled rather than counted by hand,
so a span always points at the sentence it claims to.

The fixture is the specification of the hard cases, not a smoke test. Each case below is
a state something downstream must keep apart from a neighbouring one, and the comment on
it says which. A live club page cannot be relied on to contain any of them.

`scripts/generate_club_news_fixture.py` writes it and
`tests/unit/test_club_news_fixture.py` asserts the committed file still matches, so the
two cannot drift apart.
"""

import json
from typing import Any, Final

from squadopt.data.sources.club_news import (
    CLUB_NEWS_FIXTURE_CONTRACT_VERSION,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
)

ARSENAL_URL: Final = "https://club.example/arsenal/team-news-gw4"
UNITED_URL: Final = "https://club.example/united/press-conference-gw4"
UNITED_UPDATE_URL: Final = "https://club.example/united/squad-update"

FETCHED_AT: Final = "2026-09-12T14:05:00Z"

MODEL_IDENTIFIER: Final = "synthetic-stub"
MODEL_VERSION: Final = "fixture-1"

#: Ids are in a private range that no real platform code occupies, so a fixture row can
#: never be mistaken for a captured one.
ROSTER: Final[tuple[tuple[int, str, str], ...]] = (
    (900001, "Saka", "Arsenal"),
    (900002, "Timber", "Arsenal"),
    (900003, "Havertz", "Arsenal"),
    (900004, "Jesus", "Arsenal"),
    (900005, "Odegaard", "Arsenal"),
    (900006, "Martinelli", "Arsenal"),
    (900007, "White", "Arsenal"),
    # Case: the model says nothing at all about him. Absent from the claims below, which
    # is a different state from being mentioned and dismissed.
    (900008, "Rice", "Arsenal"),
    (900009, "Mount", "Man Utd"),
    (900010, "Dalot", "Man Utd"),
    (900011, "Zirkzee", "Man Utd"),
    # Case: two players whose surnames collide inside one club. Their web names differ --
    # that pair does not collide on the real roster either -- so the ambiguity is in what
    # a claim calls them, which is exactly where a join has to refuse.
    (900012, "B.Fernandes", "Man Utd"),
    (900013, "A.Fernandes", "Man Utd"),
    # Case: his club published nothing we read. Never asked is not asked-and-silent.
    (900014, "Branthwaite", "Everton"),
    # Case: a short name carrying a diacritic. A club page and a payload can spell the same
    # player differently -- one composed, one decomposed, one stripped of the accent -- so
    # the join has to fold before it compares, and this row makes that testable rather than
    # assumed. Nothing else in the fixture folds to the same key.
    (900015, "Mart\u00ednez", "Arsenal"),
)


def _document(header: str, spans: tuple[tuple[str, str], ...]) -> tuple[str, dict[str, int]]:
    """Assemble one document's text and return the byte offsets of its named spans."""

    text = header
    offsets: dict[str, int] = {}
    for name, sentence in spans:
        if text and not text.endswith("\n"):
            text += "\n"
        start = len(text.encode("utf-8"))
        text += sentence
        offsets[f"{name}_start"] = start
        offsets[f"{name}_end"] = len(text.encode("utf-8"))
    return text + "\n", offsets


ARSENAL_TEXT, ARSENAL_SPANS = _document(
    "Team news, published 11 September 2026 at 14:00 UTC.",
    (
        ("saka", "Saka trained fully on Thursday and is available for selection."),
        ("timber", "The manager was not asked about Timber."),
        ("havertz", "Havertz will not travel."),
        ("jesus", "Jesus returned to training this week after his knee injury."),
        # Case: a literal per-cent sign inside the quotable span. The published-surface
        # guard on that character is absolute, so the span selector must refuse this span
        # rather than strip it -- a rewritten quote is not a quote -- and the card then
        # shows the link, the dateline, the role and the disposition, and no words.
        ("odegaard", 'Asked about the captain, he said: "Odegaard is at 80% and we will see."'),
        ("martinelli", "Martinelli has trained twice since the international break."),
        ("white", "White is in contention after a light knock."),
        # Spelled without the accent, as an English-language page often writes it.
        ("martinez", "Martinez has trained all week and will start."),
        ("ghost", "One name on the sheet does not match any registered player."),
    ),
)

UNITED_TEXT, UNITED_SPANS = _document(
    "Press conference notes. Published 11 September 2026.",
    (
        ("mount", "Mount may be rested with three games in eight days."),
        ("zirkzee", "On Zirkzee the manager gave no clear answer either way."),
        ("fernandes", "Fernandes has been managing a dead leg."),
    ),
)

UNITED_UPDATE_TEXT, UNITED_UPDATE_SPANS = _document(
    "Squad update.",
    (("dalot", "Dalot is expected to play a limited part."),),
)


def _claim(
    player_name: str,
    team_name: str,
    disposition: str,
    speaker: str,
    source_url: str,
    span: tuple[int, int],
    paraphrase: str,
) -> dict[str, Any]:
    return {
        "player_name": player_name,
        "team_name": team_name,
        "disposition": disposition,
        "speaker": speaker,
        "source_url": source_url,
        "span_start": span[0],
        "span_end": span[1],
        "paraphrase": paraphrase,
    }


def _span(offsets: dict[str, int], name: str) -> tuple[int, int]:
    return offsets[f"{name}_start"], offsets[f"{name}_end"]


#: The claims, in the order the response declares them. Every value of the closed
#: disposition vocabulary except ``not_addressed`` appears here; ``not_addressed`` is
#: expressed by a roster player being absent, which is the whole point of it.
CLAIMS: Final[tuple[dict[str, Any], ...]] = (
    _claim(
        "Saka",
        "Arsenal",
        "stated_expected_to_start",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "saka"),
        "He trained fully on Thursday and is available for selection.",
    ),
    # Case: the source covers his club and says nothing about him. A third state, distinct
    # both from never being asked and from the model producing no disposition.
    _claim(
        "Timber",
        "Arsenal",
        "no_statement",
        "unattributed",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "timber"),
        "The manager was not asked about him.",
    ),
    _claim(
        "Havertz",
        "Arsenal",
        "stated_expected_absent",
        "club_statement",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "havertz"),
        "He will not travel.",
    ),
    _claim(
        "Jesus",
        "Arsenal",
        "stated_returning_from_injury",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "jesus"),
        "He returned to training this week after a knee injury.",
    ),
    _claim(
        "Odegaard",
        "Arsenal",
        "stated_rotation_risk",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "odegaard"),
        "The manager was asked about him and did not commit either way.",
    ),
    # Case: the paraphrase itself carries a per-cent sign. Refused, not cleaned up: a
    # paraphrase is our sentence, so repairing one would put words we chose next to a
    # manager's name.
    _claim(
        "Martinelli",
        "Arsenal",
        "stated_rotation_risk",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "martinelli"),
        "He has trained twice, so he is roughly 50% of the way back.",
    ),
    # Case: the paraphrase carries a likelihood word. Same refusal, different trigger --
    # this one is forbidden wording rather than a forbidden character, and a member-facing
    # surface may carry neither.
    _claim(
        "White",
        "Arsenal",
        "stated_rotation_risk",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "white"),
        "He is likely to start after a light knock.",
    ),
    # Case: the claim drops a diacritic the roster carries. Folding is what makes this
    # resolve; without it a real capture would silently lose the player.
    _claim(
        "Martinez",
        "Arsenal",
        "stated_expected_to_start",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "martinez"),
        "He has trained all week and will start.",
    ),
    # Case: a name that matches no registered player at all.
    _claim(
        "Ghost Player",
        "Arsenal",
        "stated_expected_to_start",
        "manager",
        ARSENAL_URL,
        _span(ARSENAL_SPANS, "ghost"),
        "He is named on the sheet.",
    ),
    _claim(
        "Mount",
        "Man Utd",
        "stated_rotation_risk",
        "manager",
        UNITED_URL,
        _span(UNITED_SPANS, "mount"),
        "He may be rested with three games in eight days.",
    ),
    _claim(
        "Zirkzee",
        "Man Utd",
        "ambiguous",
        "manager",
        UNITED_URL,
        _span(UNITED_SPANS, "zirkzee"),
        "The manager gave no clear answer either way.",
    ),
    # Case: a bare surname two players in this club share. The join refuses rather than
    # picking the more famous one.
    _claim(
        "Fernandes",
        "Man Utd",
        "stated_rotation_risk",
        "manager",
        UNITED_URL,
        _span(UNITED_SPANS, "fernandes"),
        "He has been managing a dead leg.",
    ),
    _claim(
        "Dalot",
        "Man Utd",
        "stated_minutes_limited",
        "club_official",
        UNITED_UPDATE_URL,
        _span(UNITED_UPDATE_SPANS, "dalot"),
        "He is expected to play a limited part.",
    ),
)

#: What the model claims about each document's own dateline, which is a claim about the
#: bytes and auditable against them. Digests are deliberately not here: a model cannot
#: compute one, so the parser takes them from the stored payloads instead.
RESPONSE_DOCUMENTS: Final[tuple[dict[str, Any], ...]] = (
    # A full instant, to the second.
    {
        "url": ARSENAL_URL,
        "published_at_utc": "2026-09-11T14:00:00Z",
        "published_precision": "instant",
    },
    # A day and no more. Recorded as a day; rounding it up to an instant would invent a
    # time of knowledge nobody published.
    {"url": UNITED_URL, "published_at_utc": "2026-09-11", "published_precision": "day"},
    # No dateline at all. Absent, and never filled in with the instant we fetched it.
    {"url": UNITED_UPDATE_URL, "published_at_utc": None, "published_precision": "unknown"},
)


def make_response_text() -> str:
    """The canned response, in the shape the prompt asks for and the parser reads."""

    return json.dumps(
        {
            "contract_version": ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
            "documents": list(RESPONSE_DOCUMENTS),
            "claims": list(CLAIMS),
        },
        indent=2,
        sort_keys=True,
    )


def _one_claim_response(*, source_url: str, span_start: int, span_end: int) -> str:
    """One well-formed response carrying a single claim, for the citation-breaking cases.

    Built with ``json.dumps`` rather than by string concatenation because these two cases
    vary a *number*, and a hand-quoted integer inside a hand-quoted object is how a fixture
    meant to violate one rule ends up violating a different one by accident.
    """

    return json.dumps(
        {
            "contract_version": ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
            "documents": [dict(document) for document in RESPONSE_DOCUMENTS],
            "claims": [
                {
                    "player_name": "Saka",
                    "team_name": "Arsenal",
                    "disposition": "stated_expected_to_start",
                    "speaker": "manager",
                    "source_url": source_url,
                    "span_start": span_start,
                    "span_end": span_end,
                    "paraphrase": "He is available.",
                }
            ],
        },
        indent=2,
        sort_keys=True,
    )


#: Responses a parser must refuse rather than coerce. Each breaks the format in one way,
#: because a parser that guesses at one of these would guess at a real malformed answer.
UNPARSEABLE_RESPONSES: Final[tuple[tuple[str, str], ...]] = (
    ("not_json", "The manager said Saka is fine."),
    ("wrong_contract", '{"contract_version": "rotation_claim_response_v0", "claims": []}'),
    (
        "unknown_disposition",
        '{"contract_version": "' + ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION + '", '
        '"documents": [], "claims": [{"player_name": "Saka", "team_name": "Arsenal", '
        '"disposition": "probably_starting", "speaker": "manager", "source_url": "'
        + ARSENAL_URL
        + '", "span_start": 0, "span_end": 1, "paraphrase": "x"}]}',
    ),
    (
        "claims_not_an_array",
        '{"contract_version": "' + ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION + '", '
        '"documents": [], "claims": "Saka is fine"}',
    ),
    # The two below break the *citation* rather than the syntax, and they are the ones that
    # matter most: a claim whose span cannot be resolved against captured bytes is
    # indistinguishable from an invented one, however well-formed the JSON around it is.
    (
        "uncited_source",
        _one_claim_response(
            source_url="https://club.example/arsenal/never-read",
            span_start=0,
            span_end=10,
        ),
    ),
    (
        "span_past_the_end",
        _one_claim_response(
            source_url=ARSENAL_URL,
            span_start=0,
            span_end=len(ARSENAL_TEXT.encode("utf-8")) + 1,
        ),
    ),
)


def make_club_news_fixture() -> dict[str, Any]:
    """Return the whole fixture document, ready to be written."""

    return {
        "contract_version": CLUB_NEWS_FIXTURE_CONTRACT_VERSION,
        "response_contract_version": ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
        "synthetic": True,
        "documents": [
            {
                "requested_url": ARSENAL_URL,
                "final_url": ARSENAL_URL,
                "http_status": 200,
                "content_type": "text/plain; charset=utf-8",
                "fetched_at_utc": FETCHED_AT,
                "club": "Arsenal",
                "content": ARSENAL_TEXT,
            },
            {
                "requested_url": UNITED_URL,
                # A redirect: the page we asked for is not the page we read, and a citation
                # has to name the one we read.
                "final_url": UNITED_URL + "/full",
                "http_status": 200,
                "content_type": "text/plain; charset=utf-8",
                "fetched_at_utc": FETCHED_AT,
                "club": "Man Utd",
                "content": UNITED_TEXT,
            },
            {
                "requested_url": UNITED_UPDATE_URL,
                "final_url": UNITED_UPDATE_URL,
                "http_status": 200,
                "content_type": "text/plain; charset=utf-8",
                "fetched_at_utc": FETCHED_AT,
                "club": "Man Utd",
                "content": UNITED_UPDATE_TEXT,
            },
        ],
        # Every club named by a document above, and one that is not: Everton is declared so
        # a roster player can belong to a club nothing was read for.
        "clubs_declared": ["Arsenal", "Everton", "Man Utd"],
        "clubs_covered": ["Arsenal", "Man Utd"],
        "roster": [
            {"player_id": player_id, "web_name": web_name, "team_name": team_name}
            for player_id, web_name, team_name in ROSTER
        ],
        "response": {
            "text": make_response_text(),
            "model_identifier": MODEL_IDENTIFIER,
            "model_version": MODEL_VERSION,
        },
        "unparseable_responses": [
            {
                "case": case,
                "text": text,
                "model_identifier": MODEL_IDENTIFIER,
                "model_version": MODEL_VERSION,
            }
            for case, text in UNPARSEABLE_RESPONSES
        ],
    }
