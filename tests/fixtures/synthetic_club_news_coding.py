"""Build the synthetic coding fixture by deriving it from the located one.

A6 asks a model for a ``quote`` and locates it itself, so it needs a fixture in the
*pre-location* format -- the same claims, each carrying the sentence instead of two byte
offsets. Writing that by hand would mean typing thirteen quotes and hoping each one is a
byte-exact span of a document in the other fixture; the first typo would look like a broken
locator.

So it is derived. Every quote here is cut out of the located fixture's own document bytes at
the offsets that fixture already declares, which makes the round trip a real check: locate
this response against those documents and you get back the claims the other file carries.
Neither half was fitted to the other by hand, and a change to either that breaks the
agreement fails a test rather than passing quietly.

The refusals are the exception and are written out, because each one is a specific hazard a
model actually produces and none of them can be derived from a correct answer.
"""

import json
from typing import Any

from squadopt.data.sources.club_news import ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION
from squadopt.data.sources.club_news_coding import (
    CODING_FIXTURE_CONTRACT_VERSION,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
)
from tests.fixtures.synthetic_club_news import make_club_news_fixture

#: The file the quotes below are cut from, named in the data so a coding fixture pointed at
#: the wrong document set fails as a mismatch rather than as a mystery.
DOCUMENTS_FIXTURE = "club_news_v1.fixture.json"

MODEL_IDENTIFIER = "synthetic-stub"
MODEL_VERSION = "fixture-1"


def _document_bytes(fixture: dict[str, Any]) -> dict[str, bytes]:
    """Index the located fixture's documents by both of their URLs, as the locator does."""

    indexed: dict[str, bytes] = {}
    for entry in fixture["documents"]:
        content = entry["content"].encode("utf-8")
        indexed[entry["requested_url"]] = content
        indexed[entry["final_url"]] = content
    return indexed


def _coding_text(
    claims: list[dict[str, Any]], documents: list[dict[str, Any]], version: str
) -> str:
    """Serialise one coding response the way a model would have returned it.

    Indented and key-sorted so the committed fixture is readable in a diff and identical
    across two runs. The locator re-serialises its own output canonically, so nothing
    downstream depends on this layout -- which is the point of checking the *parsed* claims
    rather than the text.
    """

    return (
        json.dumps(
            {"contract_version": version, "documents": documents, "claims": claims},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def coded_claims(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the located fixture's claims back into the format a model is asked for."""

    indexed = _document_bytes(fixture)
    located = json.loads(fixture["response"]["text"])
    if located["contract_version"] != ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION:
        raise AssertionError(
            "The located fixture no longer declares the response contract this builder "
            "reads; the coding fixture cannot be derived from it."
        )
    claims: list[dict[str, Any]] = []
    for claim in located["claims"]:
        content = indexed[claim["source_url"]]
        claims.append(
            {
                "player_name": claim["player_name"],
                "team_name": claim["team_name"],
                "disposition": claim["disposition"],
                "speaker": claim["speaker"],
                "source_url": claim["source_url"],
                "quote": content[claim["span_start"] : claim["span_end"]].decode("utf-8"),
                "paraphrase": claim["paraphrase"],
            }
        )
    return claims


def _refusals(claim: dict[str, Any], documents: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The five responses the locator must refuse, each with the reason it must.

    Ordered by how often a real model produces them. The first is the one this whole design
    exists for: a model that tidies a quote has written a sentence the document does not
    contain, and a citation to it would point at words nobody said.
    """

    def variant(**over: Any) -> list[dict[str, Any]]:
        edited = dict(claim)
        edited.update(over)
        return [edited]

    return [
        {
            "why": (
                "the quote was normalised -- the per-cent sign written out in words -- so it "
                "is not in the bytes it claims to come from"
            ),
            "text": _coding_text(
                variant(
                    player_name="Odegaard",
                    disposition="ambiguous",
                    speaker="manager",
                    quote="Odegaard is at 80 percent and we will see.",
                    paraphrase="The manager gave a figure rather than a decision.",
                ),
                documents,
                ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            ),
        },
        {
            "why": (
                "the quote is a fragment that appears twice in the document, so the span "
                "would be a choice between two places in the page"
            ),
            "text": _coding_text(
                variant(
                    player_name="Martinelli",
                    disposition="no_statement",
                    speaker="unattributed",
                    quote="has trained",
                    paraphrase="A fragment rather than a sentence.",
                ),
                documents,
                ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            ),
        },
        {
            "why": (
                "the claim cites a document that was never fetched, so there are no bytes to "
                "locate its quote in"
            ),
            "text": _coding_text(
                variant(source_url="https://club.example/arsenal/some-other-page"),
                documents,
                ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            ),
        },
        {
            "why": "the response declares a coding contract version this locator does not read",
            "text": _coding_text([claim], documents, "rotation_claim_coding_v2"),
        },
        {
            "why": "a coded claim omits the quote entirely",
            "text": _coding_text(
                [{key: value for key, value in claim.items() if key != "quote"}],
                documents,
                ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            ),
        },
    ]


def make_club_news_coding_fixture() -> dict[str, Any]:
    """Return the whole coding fixture document, ready to be written."""

    located_fixture = make_club_news_fixture()
    located = json.loads(located_fixture["response"]["text"])
    claims = coded_claims(located_fixture)
    return {
        "contract_version": CODING_FIXTURE_CONTRACT_VERSION,
        "coding_contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "synthetic": True,
        "documents_fixture": DOCUMENTS_FIXTURE,
        "response": {
            "text": _coding_text(
                claims, located["documents"], ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
            "model_identifier": MODEL_IDENTIFIER,
            "model_version": MODEL_VERSION,
        },
        "unlocatable_responses": _refusals(claims[0], located["documents"]),
    }
