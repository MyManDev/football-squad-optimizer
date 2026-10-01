"""Read publication facts from held source bytes, without changing quoted text.

Only explicit publication fields are admitted. Transport Last-Modified, fetch time,
unlabelled dates and dateModified are not publication facts. Multiple conflicting
fields, multi-item feeds and malformed metadata remain unverified.
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


def _same_page(value: str, base: str) -> bool:
    """Admit absolute, root-relative and fragment references; never infer other relatives."""
    original = _page_identity(base)
    if original is None or not value or re.search(r"[\x00-\x20\x7f\\]", value):
        return False
    if value.startswith("#"):
        return True
    if value.startswith("/"):
        if value.startswith("//"):
            return False
        value = f"{original[0]}://{original[1]}{value}"
    return _page_identity(value) == original


class _MetadataReader(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.candidates: list[tuple[str, str]] = []
        self.invalid = False
        self._json: list[str] | None = None
        self._unbound_articles = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in ("meta", "time", "script") and len(values) != len(attrs):
            self.invalid = True
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
        if self._json is not None:
            self._json.append(data)

    def handle_endtag(self, tag: str) -> None:
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
                # Only top-level objects and @graph are page metadata. Do not read
                # dates from recommended articles nested inside an ItemList.
                graph = item.get("@graph")
                if isinstance(graph, list):
                    pending.extend(graph)


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
        candidates = reader.candidates
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
