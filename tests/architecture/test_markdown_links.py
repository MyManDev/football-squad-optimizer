"""A relative link in a tracked Markdown file leads to a file or folder the repository holds.

The documentation is navigated by its links. When this test was written the 357 tracked
Markdown files held 471 relative links, and every one of them resolved. A link that leads
nowhere is found by a reader, not by a check, and usually long after the move or rename that
broke it. This test is the check, so a pull request that moves a document has to repoint
every link to it in the same change.

What counts as a link is what a Markdown renderer follows: an inline link or image,
`[text](target)` with an optional title, and a reference definition, `[label]: target`.
What does not count is skipped before matching:

- fenced code blocks and inline code spans, because a link written as an example is text;
- a target with a scheme (`https:`, `mailto:`) or one starting with `//`, because it leaves
  the repository and a test that needs the network is not a fitness function;
- a target that is only an in-page anchor (`#section`). An anchor after a path is dropped
  and the path is checked.

A target resolves when, read from the document's own folder (or from the repository root
when it starts with `/`), it names a file git lists or a folder holding one. The listing is
`git ls-files --cached --others --exclude-standard`, so a file written but not yet added
counts while a pull request is being prepared, and a path the repository ignores
(`artifacts/`, the runtime folders under `data/`) does not, even when it exists on the
machine running the test: it would not exist for anyone reading the link on GitHub. The
comparison is exact, so a link whose case differs from the file's fails on Windows too, as it
would on GitHub and in CI.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: An inline link or image. The text may hold one level of brackets; the target is either
#: wrapped in angle brackets or a run without spaces that may hold balanced parentheses; an
#: optional title follows.
INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]"
    r"\(\s*(<[^<>\n]*>|(?:[^()\s]|\([^()\s]*\))+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)

#: A reference definition, `[label]: target`, indented by at most three spaces.
REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[[^\[\]]+\]:\s*(<[^<>\n]*>|\S+)")

#: An inline code span: a run of backticks closed by a run of the same length.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")

#: The line that opens or closes a fenced code block. Indentation is allowed, because a fence
#: inside a list item is indented with it.
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")

#: A target that leaves the repository: a scheme such as `https:` or `mailto:`, or `//host`.
EXTERNAL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")


def _listed_paths() -> list[str]:
    """Every path git tracks, plus the untracked ones it does not ignore, from the root."""

    listing = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(REPOSITORY_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return sorted({path for path in listing.split("\0") if path})


def _tracked_markdown() -> list[str]:
    listing = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(REPOSITORY_ROOT), "ls-files", "-z", "*.md"],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return sorted(path for path in listing.split("\0") if path)


def _resolvable(listed: list[str]) -> frozenset[str]:
    """The listed files and every folder above one, the repository root as `.`."""

    found = {"."}
    for path in listed:
        found.add(path)
        parent = posixpath.dirname(path)
        while parent and parent not in found:
            found.add(parent)
            parent = posixpath.dirname(parent)
    return frozenset(found)


def _link_targets(text: str) -> list[tuple[int, str]]:
    """The raw target of every link outside code, with its line number."""

    targets: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = FENCE.match(line)
        if fence is None:
            if marker:
                fence = marker.group(1)
                continue
        else:
            closes = (
                marker is not None
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and not marker.group(2).strip()
            )
            if closes:
                fence = None
            continue
        prose = CODE_SPAN.sub("", line)
        targets.extend((number, target) for target in INLINE_LINK.findall(prose))
        definition = REFERENCE_DEFINITION.match(prose)
        if definition:
            targets.append((number, definition.group(1)))
    return targets


def _repository_path(document: str, raw: str) -> str | None:
    """The repository-relative path a target names, or None when there is nothing to check.

    A path that climbs above the repository root comes back starting with `..`, which no
    listed path does, so it is reported rather than skipped.
    """

    target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
    if not target or target.startswith("#") or EXTERNAL.match(target):
        return None
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    if path.startswith("/"):
        return posixpath.normpath(path.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(document), path))


def _relative_links() -> list[tuple[str, int, str, str]]:
    links: list[tuple[str, int, str, str]] = []
    for document in _tracked_markdown():
        source = REPOSITORY_ROOT / document
        if not source.is_file():
            continue
        for number, raw in _link_targets(source.read_text(encoding="utf-8")):
            resolved = _repository_path(document, raw)
            if resolved is not None:
                links.append((document, number, raw, resolved))
    return links


def test_every_relative_link_in_a_tracked_markdown_file_resolves() -> None:
    links = _relative_links()
    # If this ever falls near zero the patterns have stopped matching and the test is asleep.
    assert len(links) >= 400, f"expected the documents to hold relative links; found {len(links)}"

    resolvable = _resolvable(_listed_paths())
    broken = [
        f"{document}:{number} links to {raw}"
        for document, number, raw, resolved in links
        if resolved not in resolvable
    ]
    assert not broken, "\n".join(
        [
            "A relative link leads to no file or folder the repository holds. Repoint it to",
            "where the target lives now, or add the target to git if it is new:",
            *broken,
        ]
    )


def test_code_and_external_targets_are_not_links() -> None:
    """The skips are exercised on a synthetic document, so a loosened pattern is seen here."""

    document = "\n".join(
        [
            "See [the map](../README.md) and ![a picture](images/a%20b.png 'title').",
            "Inline `[not a link](missing.md)` and ``[nor this](missing.md)`` are code.",
            "```text",
            "[inside a fence](missing.md)",
            "```",
            "~~~~",
            "~~~",
            "[still inside the longer fence](missing.md)",
            "~~~~",
            "[outside](<with space.md#part>) [web](https://example.com/x.md) [top](#top)",
            "[mail](mailto:someone@example.com) [host](//example.com/x.md)",
            "[label]: ../docs/README.md",
        ]
    )

    targets = [raw for _, raw in _link_targets(document)]
    assert targets == [
        "../README.md",
        "images/a%20b.png",
        "<with space.md#part>",
        "https://example.com/x.md",
        "#top",
        "mailto:someone@example.com",
        "//example.com/x.md",
        "../docs/README.md",
    ]
    resolved = [_repository_path("docs/guide.md", raw) for raw in targets]
    assert resolved == [
        "README.md",
        "docs/images/a b.png",
        "docs/with space.md",
        None,
        None,
        None,
        None,
        "docs/README.md",
    ]


def test_a_path_above_the_root_or_in_another_case_does_not_resolve() -> None:
    resolvable = _resolvable(["docs/README.md", "docs/architecture/branching.md"])

    assert _repository_path("README.md", "../outside.md") == "../outside.md"
    assert "../outside.md" not in resolvable
    assert _repository_path("docs/README.md", "Architecture/branching.md") not in resolvable
    assert _repository_path("docs/README.md", "architecture/branching.md") in resolvable
    assert _repository_path("docs/README.md", "architecture/") in resolvable
    assert _repository_path("docs/README.md", "/docs/README.md#top") in resolvable
    assert _repository_path("docs/README.md", "..") in resolvable
