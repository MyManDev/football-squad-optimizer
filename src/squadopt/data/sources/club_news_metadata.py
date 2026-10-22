"""Read publication facts from held source bytes, without changing quoted text.

Only explicit publication fields are admitted. An article's JSON-LD may identify the
fetched page, or the page's single, same-origin canonical URL declared in its head at any
path on that host. A language prefix also needs the page's own language, a head canonical
naming the fetched page and a matching hreflang declaration. A single article's WebPage
identifier that writes the page path's slashes as hyphens counts only when the canonical
and Open Graph URLs name the fetched page, the headlines agree and at least one displayed
time, and every one, equals the instant; those declarations may be streamed directly under
the body only when the head has none. A canonical on another origin, a protocol-relative
or document-relative one, two different ones, one outside the head and an article
addressed to a third page date nothing. Transport Last-Modified, fetch time, unlabelled
dates and dateModified are not publication facts. Multiple conflicting fields, multi-item
feeds and malformed metadata remain unverified.
"""

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

PUBLICATION_METADATA_VERSION = "source_publication_metadata_v1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "ReportageNewsArticle"}
_MAX_HTML_DEPTH = 256
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
PUBLICATION_SOURCES = (
    "html_publication_meta",
    "html_publication_time",
    "jsonld_datePublished",
    "text_published",
    "feed_published",
    "consistent_publication_fields",
)


@dataclass(frozen=True, slots=True)
class PublicationMetadata:
    published_at_utc: str | None
    published_precision: str
    source: str | None
    source_sha256: str
    verified: bool
    reason: str
    contract_version: str = PUBLICATION_METADATA_VERSION


@dataclass(frozen=True, slots=True)
class _AddressedDate:
    address: str
    value: str
    headline: str
    page_identifier: bool


def _normalise(value: str, source: str) -> tuple[str, str] | None:
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat(), "day"
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            if source != "feed_published":
                return None
            instant = parsedate_to_datetime(value)
        if instant.tzinfo is None or instant.utcoffset() is None:
            return None
        return instant.astimezone(UTC).isoformat().replace("+00:00", "Z"), "instant"
    except (TypeError, ValueError, OverflowError):
        return None


def _page_identity(value: str) -> tuple[str, str, str] | None:
    """A literal HTTP page identity, without URL resolution or network-layer imports."""
    if re.search(r"[\x00-\x20\x7f\\]", value):
        return None
    match = re.fullmatch(
        r"(https?)://([a-z0-9][a-z0-9.-]*(?::[0-9]+)?)(/[^?#]*)?(\?[^#]*)?(?:#.*)?",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    path = match[3] or "/"
    if any(part in (".", "..") for part in path.split("/")):
        return None
    return match[1].lower(), match[2].lower(), path + (match[4] or "")


def _page_reference(value: str, base: str) -> tuple[str, str, str] | None:
    """Resolve only absolute, root-relative and fragment page references."""
    original = _page_identity(base)
    if original is None or not value or re.search(r"[\x00-\x20\x7f\\]", value):
        return None
    if value.startswith("#"):
        return original
    if value.startswith("/"):
        if value.startswith("//"):
            return None
        value = f"{original[0]}://{original[1]}{value}"
    return _page_identity(value)


def _same_page(value: str, base: str) -> bool:
    """Admit absolute, root-relative and fragment references; never infer other relatives."""
    original = _page_identity(base)
    return original is not None and _page_reference(value, base) == original


class _MetadataReader(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.candidates: list[tuple[str, str]] = []
        self.invalid = False
        self._json: list[str] | None = None
        self._unbound_articles = 0
        self._in_head = False
        self._canonical_urls: list[str] = []
        self._addressed_dates: list[_AddressedDate] = []
        self._language: str | None = None
        self._language_urls: list[tuple[str, str]] = []
        self._article_count = 0
        self._open_graph_urls: list[str] = []
        self._open_graph_titles: list[str] = []
        self._displayed_times: list[str] = []
        self._tag_stack: list[str] = []
        self._streamed_canonical_urls: list[str] = []
        self._streamed_open_graph_urls: list[str] = []
        self._streamed_open_graph_titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.invalid:
            return
        values = dict(attrs)
        body_root = self._tag_stack in (["body"], ["html", "body"])
        if tag not in _VOID_TAGS:
            if len(self._tag_stack) >= _MAX_HTML_DEPTH:
                self.invalid = True
                return
            self._tag_stack.append(tag)
        if tag in ("meta", "time", "script", "link") and len(values) != len(attrs):
            self.invalid = True
        if tag == "head":
            self._in_head = True
        if tag == "html":
            self._language = (values.get("lang") or "").lower()
        if tag == "meta" and self._in_head:
            if values.get("property") == "og:url":
                self._open_graph_urls.append(values.get("content") or "")
            if values.get("property") == "og:title":
                self._open_graph_titles.append(values.get("content") or "")
        if body_root:
            if tag == "link" and "canonical" in (values.get("rel") or "").lower().split():
                self._streamed_canonical_urls.append(values.get("href") or "")
            if tag == "meta" and values.get("property") == "og:url":
                self._streamed_open_graph_urls.append(values.get("content") or "")
            if tag == "meta" and values.get("property") == "og:title":
                self._streamed_open_graph_titles.append(values.get("content") or "")
        if tag == "time" and values.get("datetime") is not None:
            self._displayed_times.append(values["datetime"] or "")
        if (
            tag == "link"
            and self._in_head
            and "canonical" in (values.get("rel") or "").lower().split()
        ):
            self._canonical_urls.append(values.get("href") or "")
        if (
            tag == "link"
            and self._in_head
            and "alternate" in (values.get("rel") or "").lower().split()
        ):
            self._language_urls.append(
                ((values.get("hreflang") or "").lower(), values.get("href") or "")
            )
        if tag == "meta" and (values.get("property") or values.get("name") or "").casefold() in {
            "article:published_time",
            "datepublished",
            "pubdate",
            "publication_date",
        }:
            self.candidates.append((values.get("content") or "", "html_publication_meta"))
        if tag == "time" and (
            "datePublished" in (values.get("itemprop") or "").split() or "pubdate" in values
        ):
            self.candidates.append((values.get("datetime") or "", "html_publication_time"))
        if tag == "script" and (values.get("type") or "").casefold() == "application/ld+json":
            self._json = []

    def handle_data(self, data: str) -> None:
        if self.invalid:
            return
        if self._json is not None:
            self._json.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.invalid:
            return
        if tag in self._tag_stack:
            start = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
            del self._tag_stack[start:]
        if tag == "head":
            self._in_head = False
        if tag != "script" or self._json is None:
            return
        text, self._json = "".join(self._json), None
        try:
            pending = [json.loads(text, object_pairs_hook=_unique_object)]
        except (ValueError, RecursionError):
            self.invalid = True
            return
        visited = 0
        while pending:
            visited += 1
            if visited > 2000:
                self.invalid = True
                return
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, dict):
                kinds = item.get("@type", [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if isinstance(kinds, list) and any(
                    kind in _ARTICLE_TYPES for kind in kinds if isinstance(kind, str)
                ):
                    self._article_count += 1
                    address = item.get("url", item.get("mainEntityOfPage", item.get("@id")))
                    if isinstance(address, dict):
                        address = address.get("@id")
                    if address is None and item.get("datePublished") is not None:
                        self._unbound_articles += 1
                        if self._unbound_articles > 1:
                            self.invalid = True
                    if address is None or (
                        isinstance(address, str) and _same_page(address, self.url)
                    ):
                        value = item.get("datePublished")
                        if value is not None:
                            self.candidates.append(
                                (value if isinstance(value, str) else "", "jsonld_datePublished")
                            )
                    elif isinstance(address, str) and item.get("datePublished") is not None:
                        value = item["datePublished"]
                        page = item.get("mainEntityOfPage")
                        headline = item.get("headline")
                        self._addressed_dates.append(
                            _AddressedDate(
                                address,
                                value if isinstance(value, str) else "",
                                headline if isinstance(headline, str) else "",
                                "url" not in item
                                and isinstance(page, dict)
                                and page.get("@type") == "WebPage",
                            )
                        )
                # Only top-level objects and @graph are page metadata. Do not read
                # dates from recommended articles nested inside an ItemList.
                graph = item.get("@graph")
                if isinstance(graph, list):
                    pending.extend(graph)

    def canonical_dates(self) -> list[tuple[str, str]]:
        """Use the page's own unambiguous canonical identity, never a related article."""
        original = _page_identity(self.url)
        # Streaming renderers can emit page metadata directly under body. This is
        # only corroboration for the identifier form below, never a general body
        # canonical fallback and never an override of a head declaration.
        if (
            original is not None
            and not self._canonical_urls
            and not self._open_graph_urls
            and not self._open_graph_titles
            and {_page_reference(url, self.url) for url in self._streamed_canonical_urls}
            == {original}
        ):
            return [
                (item.value, "jsonld_datePublished")
                for item in self._addressed_dates
                if self._corroborated_page_identifier(item, original, streamed=True)
            ]
        identities = {_page_reference(url, self.url) for url in self._canonical_urls}
        if original is None or len(identities) != 1:
            return []
        canonical = identities.pop()
        if canonical is None or canonical[:2] != original[:2]:
            return []
        address = f"{canonical[0]}://{canonical[1]}{canonical[2]}"
        # Some sites omit the language prefix in their canonical and hreflang URLs
        # but include it in the article schema. Require all three source declarations
        # and the identical article path; a locale alone never aliases another page.
        language = self._language
        localized: tuple[str, str, str] | None = None
        if (
            canonical == original
            and language is not None
            and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", language)
            and any(
                lang == language and _page_reference(url, self.url) == canonical
                for lang, url in self._language_urls
            )
        ):
            localized = (canonical[0], canonical[1], f"/{language}{canonical[2]}")
        return [
            (item.value, "jsonld_datePublished")
            for item in self._addressed_dates
            if _same_page(item.address, address)
            or (localized is not None and _page_reference(item.address, self.url) == localized)
            or (canonical == original and self._corroborated_page_identifier(item, original))
        ]

    def _corroborated_page_identifier(
        self, item: _AddressedDate, original: tuple[str, str, str], *, streamed: bool = False
    ) -> bool:
        """Recognize a page's slash-to-hyphen WebPage id, never repair an article URL.

        Some publishers emit a WebPage identifier rather than a usable URL. Admit
        this exact form only for one article, with the same canonical and Open Graph
        URL, matching headlines and a displayed datetime equal to datePublished.
        The unlabelled time corroborates the explicit publication field; it never
        supplies a publication date on its own.
        """
        if not item.page_identifier or self._article_count != 1 or "?" in original[2]:
            return False
        identifier = f"{original[0]}://{original[1]}{original[2].replace('/', '-')}"
        if item.address != identifier or not item.headline.strip():
            return False
        urls = self._streamed_open_graph_urls if streamed else self._open_graph_urls
        titles = self._streamed_open_graph_titles if streamed else self._open_graph_titles
        if {_page_reference(url, self.url) for url in urls} != {original}:
            return False
        if {title.strip() for title in titles} != {item.headline.strip()}:
            return False
        publication = _normalise(item.value, "jsonld_datePublished")
        displayed = {_normalise(value, "html_publication_time") for value in self._displayed_times}
        return (
            publication is not None and publication[1] == "instant" and displayed == {publication}
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous repeated metadata key.")
        result[key] = value
    return result


def publication_metadata(content: bytes, content_type: str, source_url: str) -> PublicationMetadata:
    """Return the unique source publication value, or an explicit unavailable result."""
    digest = hashlib.sha256(content).hexdigest()

    def missing(reason: str) -> PublicationMetadata:
        return PublicationMetadata(None, "unknown", None, digest, False, reason)

    if not content or len(content) > MAX_SOURCE_BYTES:
        return missing("source_size_invalid")
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        return missing("source_encoding_invalid")
    media = content_type.split(";", 1)[0].strip().lower()
    candidates: list[tuple[str, str]] = []
    if media in ("text/html", "application/xhtml+xml"):
        reader = _MetadataReader(source_url)
        try:
            reader.feed(text)
            reader.close()
        except (ValueError, RecursionError):
            return missing("publication_metadata_invalid")
        if reader.invalid or reader._json is not None:
            return missing("publication_metadata_invalid")
        candidates = [*reader.candidates, *reader.canonical_dates()]
    elif media == "text/plain":
        candidates = [
            (match.group(1), "text_published")
            for match in re.finditer(
                r"(?im)^\s*(?:published|publication date)\s*:\s*([^\r\n]+?)\s*$", text
            )
        ]
    elif media in ("application/rss+xml", "application/atom+xml", "text/xml", "application/xml"):
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            return missing("publication_metadata_invalid")
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, ValueError):
            return missing("publication_metadata_invalid")
        entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in ("item", "entry")]
        if len(entries) != 1:
            return missing("publication_item_ambiguous")
        candidates = [
            (node.text or "", "feed_published")
            for node in entries[0]
            if node.tag.rsplit("}", 1)[-1] in ("pubDate", "published")
        ]
    if not candidates:
        return missing("publication_not_declared")
    normalised = [_normalise(value, source) for value, source in candidates]
    if any(value is None for value in normalised):
        return missing("publication_metadata_invalid")
    unique = {value for value in normalised if value is not None}
    if len(unique) != 1:
        return missing("publication_metadata_conflict")
    value, precision = unique.pop()
    sources = {source for _, source in candidates}
    source = sources.pop() if len(sources) == 1 else "consistent_publication_fields"
    return PublicationMetadata(value, precision, source, digest, True, "verified")
