"""The bytes a person reads, taken from the bytes a host served.

The lane's central rule is that a claim cites an exact byte range and that the model never
counts bytes: it is asked for a sentence, verbatim, and :func:`locate_quote` finds it. That
rule held for as long as documents were plain text. It does not survive HTML.

Measured on a page written the way a club writes one, five sentences a person would read off
the screen and four of them could not be located in the source: the apostrophe in
``Saturday's`` is ``&rsquo;`` in the bytes, ``&`` is ``&amp;``, an em dash is ``&mdash;``, and
``Bukayo is fit`` has a ``<strong>`` in the middle of it. A model shown HTML either quotes the
markup — and then a member is shown ``Bukayo <strong>is</strong> fit`` as the club's own words
— or quotes what it read and the citation cannot be found. Neither is a citation.

So the document gets a second payload. This module turns served bytes into the text a person
reads, deterministically and with no dependency outside the standard library, and **that** is
what the model is shown and what the offsets index. The served bytes are kept beside it: they
are what the host actually sent, they are what makes the extraction auditable, and throwing
them away to save a payload would trade the only evidence that this step is faithful.

The invariant is one sentence, and every other choice here follows from it:

    the bytes handed to the model are the bytes the locator searches.

Which is why the extraction is versioned. A capture written under one extractor and read back
under another would resolve its stored offsets into different words — the same failure the
digest check exists to prevent — so the version travels with the capture and a mismatch is
refused rather than re-extracted.

Plain text passes through unchanged. Not a special case for convenience: there is nothing to
extract from text that is already the text, and a transformation that touched it would move
every offset in every capture this repository has written so far.
"""

import html.parser
from typing import Final

from squadopt.data.errors import DataSourceError


class ReadableTextError(DataSourceError):
    """A served document has no readable text, or none this module can take.

    Its own class, and deliberately not ``ClubNewsError``: this module is imported *by*
    ``club_news`` to build a document, so depending on that module's exception would be a
    cycle. It sits under ``DataSourceError`` like ``ClubNewsError`` does, so every caller
    that already refuses a bad source refuses this too -- and the fetch adapter translates
    it into its own error, because one unreadable page must cost one club and not the week.
    """


#: The extraction, versioned like the prompt. Bumped whenever a rule below changes, because
#: offsets written under one version do not mean the same thing under another.
READABLE_TEXT_CONTRACT_VERSION: Final = "readable_text_v3"

#: Served bytes that are already what a person reads.
PLAIN_MEDIA_TYPES: Final[tuple[str, ...]] = ("text/plain",)

#: Served bytes that carry markup this module removes.
MARKUP_MEDIA_TYPES: Final[tuple[str, ...]] = ("text/html", "application/xhtml+xml")

#: A syndication feed, read through the same parser and the same rules. A club that serves a
#: news page a person reads but a reader cannot is not a club this lane can cover, and a feed
#: is often the same words without the application shell around them. It is not a second
#: extractor: the only thing a feed needs that a page does not is ``CDATA``, which is where a
#: feed keeps the markup of its own item bodies.
FEED_MEDIA_TYPES: Final[tuple[str, ...]] = ("application/rss+xml", "application/atom+xml")

#: Types a feed is also served as. Measured rather than assumed: the one club this lane added
#: feed reading for serves its feed as ``text/xml``, so the two names above admit every feed
#: except the one they were added for. These are generic though, and an arbitrary XML document
#: is not a document a claim can be quoted from, so they are read only when the bytes say what
#: they are. That check is on the served bytes rather than on the header for the same reason
#: the whole lane prefers them: the header is what a server claims, the bytes are what it sent.
GENERIC_XML_MEDIA_TYPES: Final[tuple[str, ...]] = ("text/xml", "application/xml")

#: How far into a document the declaration is looked for. A feed names itself in its root
#: element, which follows the XML declaration and nothing else.
_FEED_DECLARATION_BYTES: Final = 2048

#: What a feed's root element is called, in the two vocabularies this lane meets.
_FEED_ROOTS: Final[tuple[str, ...]] = ("<rss", "<feed")

#: Elements whose content is instructions to a browser rather than words to a reader. Their
#: text is dropped entirely: a quote located inside a script would be a citation into code.
SILENT_ELEMENTS: Final[frozenset[str]] = frozenset(
    {"script", "style", "template", "noscript", "head", "svg"}
)

#: A feed's silent elements: a page's, plus ``link``. In a feed ``<link>`` holds the item's URL
#: as text, and a bare URL run into the next item's sentence is noise a quote could land in. It
#: is silent only in a feed, because in HTML ``<link>`` is a void element with no end tag: the
#: parser never reports one closing, so counted as silent there it opened a region nothing
#: closed and every word after it on the page was dropped.
FEED_SILENT_ELEMENTS: Final[frozenset[str]] = SILENT_ELEMENTS | {
    # A feed's own vocabulary for addresses and identifiers. None of these holds prose
    # and none is an HTML element carrying text, so silencing them costs a page nothing
    # and spares a coder a quarter of a real feed in bare URLs: measured on one club's
    # feed, 202 of 805 extracted lines were a link, a guid, an image url or a docs url.
    "link",
    "guid",
    "url",
    "docs",
}

#: Elements that end a line. A club's page separates its sentences with markup rather than
#: newlines, so without this every paragraph would run into the next and a quote spanning the
#: join would match text that was never adjacent on the page.
BREAKING_ELEMENTS: Final[frozenset[str]] = frozenset(
    # A feed's structure, so one item's words do not run into the next one's. ``title`` is the
    # only one of these HTML also has, and there it lives inside the silent ``head``.
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "description",
        "entry",
        "item",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "title",
        "tr",
        "ul",
    }
)


class _Reader(html.parser.HTMLParser):
    """Collect the text a browser would show, and nothing else.

    ``convert_charrefs`` is left on, which is the whole reason a quote with an apostrophe can
    be found at all: the parser hands over ``Saturday's`` where the bytes said
    ``Saturday&rsquo;s``. Inline elements are deliberately *not* breaks — a ``<strong>`` in the
    middle of a sentence must leave the sentence whole, because that is the case this module
    exists for.
    """

    def __init__(
        self,
        silent_elements: frozenset[str] = SILENT_ELEMENTS,
        *,
        unwrap_cdata: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._silent_elements = silent_elements
        self._unwrap_cdata = unwrap_cdata
        self._lines: list[str] = []
        self._current: list[str] = []
        self._silent = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._silent_elements:
            self._silent += 1
            return
        if tag in BREAKING_ELEMENTS:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._silent_elements:
            self._silent = max(0, self._silent - 1)
            return
        if tag in BREAKING_ELEMENTS:
            self._break()

    def handle_data(self, data: str) -> None:
        if self._silent:
            return
        if self._unwrap_cdata:
            stripped = data.strip()
            if stripped.startswith("<![CDATA[") and stripped.endswith("]]>"):
                # ``title`` is RCDATA in HTML, so the parser reads its content as text and
                # never calls ``unknown_decl`` for a section inside it. In a feed that is
                # exactly where an item's headline lives, so without this every headline
                # arrives wearing its own markers. Only a value that is entirely one section
                # is unwrapped, so prose that merely contains those characters is left alone.
                self._read_section(stripped[len("<![CDATA[") : -len("]]>")])
                return
        self._current.append(data)

    def unknown_decl(self, data: str) -> None:
        """Read a ``CDATA`` section, which is where a feed keeps an item's own markup.

        Dropped, the sentence a claim would quote disappears: a feed item's body is almost
        always ``<![CDATA[<p>...</p>]]>``, and the words inside it are the club's. It is run
        through a second reader rather than fed back into this one, because a parser being
        driven from inside its own callback is a different kind of bug.
        """

        if self._silent or not data.startswith("CDATA["):
            return
        self._read_section(data[len("CDATA[") :].removesuffix("]"))

    def _read_section(self, inner_markup: str) -> None:
        """Read one section's content and append it, under a page's rules.

        An item body is HTML, so it is read as a page and not as a feed, which is why the
        nested reader takes the defaults. It is a second reader rather than this one fed
        again because a parser driven from inside its own callback is a different bug.
        """

        nested = _Reader()
        nested.feed(inner_markup)
        nested.close()
        inner = nested.text()
        if inner:
            self._break()
            self._lines.extend(inner.split("\n"))

    def _break(self) -> None:
        line = " ".join("".join(self._current).split())
        if line:
            self._lines.append(line)
        self._current = []

    def text(self) -> str:
        self._break()
        return "\n".join(self._lines)


def _declares_a_feed(content: bytes) -> bool:
    """Whether the served bytes name a feed as their root element.

    Only the opening of the document is read, because that is where a root element is and
    because a match further down would be an element name inside somebody's prose.
    """

    opening = content[:_FEED_DECLARATION_BYTES].lstrip().lower()
    return any(root.encode("ascii") in opening for root in _FEED_ROOTS)


def extract_readable_text(content: bytes, content_type: str) -> bytes:
    """Return the readable text of one served document, as UTF-8 bytes.

    Pure and deterministic: the same bytes and the same content type give the same output on
    every run and every platform, which is what lets a capture replay.

    A document that yields no readable text is refused rather than returned empty. A page of
    pure markup is a page nobody can be quoted from, and recording it as a document the model
    read would make "the club said nothing about him" indistinguishable from "there was
    nothing to read" — the distinction this lane is built to keep.
    """

    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type in PLAIN_MEDIA_TYPES:
        if not content.strip():
            raise ReadableTextError(
                f"A {media_type!r} document carries no text. An empty document is not a club "
                "that published nothing; it is a read that did not work."
            )
        return content
    if media_type in GENERIC_XML_MEDIA_TYPES and not _declares_a_feed(content):
        raise ReadableTextError(
            f"A {media_type!r} document does not declare itself a feed, so it is refused "
            "rather than read as one. That type carries any XML at all, and a document whose "
            "root element this lane does not know is not a document a claim could be quoted "
            f"from; the roots read are {list(_FEED_ROOTS)!r}."
        )
    if (
        media_type not in MARKUP_MEDIA_TYPES
        and media_type not in FEED_MEDIA_TYPES
        and media_type not in GENERIC_XML_MEDIA_TYPES
    ):
        raise ReadableTextError(
            f"{media_type!r} is not a document type this project reads. Readable text is "
            f"extracted from "
            f"{list(MARKUP_MEDIA_TYPES + FEED_MEDIA_TYPES + GENERIC_XML_MEDIA_TYPES)!r} and "
            f"passed through for {list(PLAIN_MEDIA_TYPES)!r}; anything else has no text a "
            "span could index."
        )

    try:
        markup = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReadableTextError(
            f"A {media_type!r} document is not UTF-8 ({error}). It is refused rather than "
            "decoded lossily, because a quote taken from a replaced character would not be "
            "found in the bytes it has to be matched against."
        ) from error

    # A feed is a feed whichever type carried it. Deciding this once is what keeps a feed
    # served as ``text/xml`` from being read under the page rules, which is how it would
    # otherwise keep its item links and lose its headlines.
    as_feed = media_type in FEED_MEDIA_TYPES or media_type in GENERIC_XML_MEDIA_TYPES
    reader = _Reader(FEED_SILENT_ELEMENTS if as_feed else SILENT_ELEMENTS, unwrap_cdata=as_feed)
    reader.feed(markup)
    reader.close()
    text = reader.text()
    if not text:
        raise ReadableTextError(
            "The document carries markup and no readable text, so there is nothing a claim "
            "could quote. A page nobody can be quoted from is a club that was not covered, "
            "not a club that said nothing."
        )
    return (text + "\n").encode("utf-8")


__all__ = [
    "FEED_MEDIA_TYPES",
    "GENERIC_XML_MEDIA_TYPES",
    "MARKUP_MEDIA_TYPES",
    "PLAIN_MEDIA_TYPES",
    "READABLE_TEXT_CONTRACT_VERSION",
    "ReadableTextError",
    "extract_readable_text",
]
