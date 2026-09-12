"""The text a person reads, and the four quotes that could not be found without it.

The cases below are a measurement before they are a test. A page written the way a club
writes one was handed to the locator, with five sentences a person would read off the
screen, and four of them could not be located in the served bytes: an apostrophe that is
``&rsquo;``, an ampersand that is ``&amp;``, an em dash that is ``&mdash;``, and a sentence
with a ``<strong>`` through the middle of it. Those four are here so the failure cannot come
back quietly.

One case deliberately still fails, and it is the one that shows the rule was not loosened:
a quote that *tidies* the page's curly apostrophe into a straight one is refused. The
extraction resolves an entity into the character the page actually shows; it does not make
the locator forgiving. Verbatim still means verbatim.
"""

import pytest

from squadopt.data.sources.club_news import ClubNewsError
from squadopt.data.sources.club_news_coding import locate_quote
from squadopt.data.sources.club_news_readable import (
    MARKUP_MEDIA_TYPES,
    PLAIN_MEDIA_TYPES,
    READABLE_TEXT_CONTRACT_VERSION,
    ReadableTextError,
    extract_readable_text,
)

PAGE = b"""<!DOCTYPE html>
<html lang="en"><head><title>Team news</title><style>p{color:red}</style></head>
<body>
<script>var tracker = "Havertz will be assessed";</script>
<article class="team-news">
  <p class="intro">Mikel Arteta provided an update on the squad ahead of Saturday&rsquo;s
  trip to Everton.</p>
  <p>&ldquo;Bukayo <strong>is</strong> fit and available,&rdquo; said the manager.</p>
  <p>Gabriel &amp; Saliba both trained fully on Thursday.</p>
  <p>Havertz will be assessed &mdash; he is a doubt.</p>
</article>
</body></html>
"""


def _readable() -> bytes:
    return extract_readable_text(PAGE, "text/html; charset=utf-8")


@pytest.mark.parametrize(
    ("why", "quote"),
    [
        # The curly apostrophe is the case, not a typo: it is what &rsquo; resolves to and
        # what a reader sees, so the quote has to carry it.
        ("an apostrophe the bytes spell &rsquo;", "ahead of Saturday’s trip to Everton"),  # noqa: RUF001
        ("a tag through the middle of the sentence", "Bukayo is fit and available"),
        ("an ampersand the bytes spell &amp;", "Gabriel & Saliba both trained fully on Thursday"),
        ("an em dash the bytes spell &mdash;", "Havertz will be assessed — he is a doubt"),
    ],
)
def test_a_sentence_a_person_reads_can_be_located(why: str, quote: str) -> None:
    """Each of these was refused against the served bytes. Measured, not supposed."""

    readable = _readable()

    start, end = locate_quote(readable, quote, "The claim")

    assert readable[start:end].decode("utf-8") == quote
    assert why  # named in the parameters so a failure says which hazard returned


def test_the_same_sentence_cannot_be_located_in_the_served_bytes() -> None:
    """The other half of the measurement, so the fix is not credited to nothing."""

    with pytest.raises(ClubNewsError, match="does not appear"):
        locate_quote(PAGE, "Bukayo is fit and available", "The claim")


def test_a_quote_that_tidies_the_page_is_still_refused() -> None:
    """Extraction resolves entities; it does not make the locator forgiving.

    The page shows a curly apostrophe. A model that writes a straight one has not copied the
    document, and a citation to words nobody published is exactly what the single-occurrence
    rule exists to stop.
    """

    with pytest.raises(ClubNewsError, match="does not appear"):
        locate_quote(_readable(), "ahead of Saturday's trip to Everton", "The claim")


def test_instructions_to_a_browser_are_not_words_to_a_reader() -> None:
    """A quote located inside a script would be a citation into code."""

    readable = _readable()

    assert b"tracker" not in readable
    assert b"color:red" not in readable
    assert b"Team news</title>" not in readable


def test_plain_text_passes_through_byte_for_byte() -> None:
    """Not a convenience: a transformation here would move every offset already written."""

    served = b"Saka trained fully on Thursday.\n"

    assert extract_readable_text(served, "text/plain; charset=utf-8") == served


def test_the_extraction_is_deterministic() -> None:
    """A capture replays only if this returns the same bytes every time."""

    assert _readable() == _readable()


def test_a_page_of_pure_markup_is_refused_rather_than_returned_empty() -> None:
    """A club nobody can be quoted from is uncovered, not silent."""

    with pytest.raises(ReadableTextError, match="nothing a claim could quote"):
        extract_readable_text(b"<html><body><img src='x'></body></html>", "text/html")


def test_an_empty_plain_document_is_refused() -> None:
    """An empty document is a read that did not work, not a club that published nothing."""

    with pytest.raises(ReadableTextError, match="no text"):
        extract_readable_text(b"   \n", "text/plain")


def test_a_document_type_with_no_text_to_index_is_refused() -> None:
    """A span cannot be located in bytes that are not text."""

    with pytest.raises(ReadableTextError, match="not a document type"):
        extract_readable_text(b"%PDF-1.7", "application/pdf")


def test_markup_that_is_not_utf8_is_refused_rather_than_decoded_lossily() -> None:
    """A quote taken from a replaced character would not be in the bytes it is matched to."""

    with pytest.raises(ReadableTextError, match="not UTF-8"):
        extract_readable_text("<p>Kant\xe9 is fit.</p>".encode("latin-1"), "text/html")


def test_block_elements_separate_sentences_that_were_never_adjacent() -> None:
    """Without a break the last word of one paragraph joins the first of the next."""

    readable = extract_readable_text(b"<p>He is fit</p><p>Saka is out</p>", "text/html")

    assert readable == b"He is fit\nSaka is out\n"
    with pytest.raises(ClubNewsError, match="does not appear"):
        locate_quote(readable, "He is fit Saka is out", "The claim")


def test_the_extraction_declares_a_version() -> None:
    """Offsets written under one extractor do not mean the same thing under another."""

    assert READABLE_TEXT_CONTRACT_VERSION == "readable_text_v1"
    assert "text/html" in MARKUP_MEDIA_TYPES
    assert "text/plain" in PLAIN_MEDIA_TYPES
