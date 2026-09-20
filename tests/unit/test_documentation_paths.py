"""A source path cited in the documentation names a file that is there.

Twice in one night a document cited `data/<module>.py` when the file is
`src/squadopt/data/<module>.py`, and both times the mistake survived a careful read. The
reason is specific to this repository: `data/` is **both** a runtime directory at the root
and a package under `src/squadopt/`, so a rooted-looking citation of a module resolves to a
real directory, and a reader who checks finds one and concludes they mistyped. A wrong path
that resolves to something is worse than one that resolves to nothing.

The second of the two was written by an author who had been told about the first an hour
earlier, which is the argument for a check rather than a rule: the failure is habit and
habit does not respond to being told.

Scope is deliberately narrow, chosen by counting rather than by taste. Across `docs/` there
are 576 backticked file citations; requiring all of them to resolve from the root fails 400,
because the house style also cites relative to `docs/` and relative to `src/squadopt/`, and
both are legitimate shorthand. Requiring it only of citations whose first segment is a real
top level directory leaves 43 failures; requiring it only of those that also name a Python
module leaves the handful this file pins, every one of them the ambiguity above. Runtime
JSON under `data/` is legitimately absent from the tree and is not checked.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"

#: Directories that exist at the repository root. A citation starting with one of these is
#: claiming a path from the root rather than using a relative shorthand.
ROOTED = frozenset({"src", "scripts", "tests", "web", "docs", "deploy", "data", ".github"})

#: A backticked path naming a Python module, with any line or line-range suffix.
CITATION = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.py)(?::\d+(?:-\d+)?)?`")

#: A citation holding a placeholder is a shape, not a claim about a file that exists.
PLACEHOLDER = re.compile(r"[<>*{}]|\bNN\b|\bXX\b")

#: Paths a document proposes rather than cites. A proposal names a file that is meant not to
#: exist yet, and no pattern can tell the two apart, so each one is listed with its reason.
PROPOSED: dict[str, str] = {
    # docs/data_followups.md item 12 proposes creating this to change ruff's isort resolution,
    # and records that it was left to the software owner because it also changes how pytest
    # imports the optimizer tests in that directory.
    "tests/unit/__init__.py": "proposed in docs/data_followups.md item 12, deliberately absent",
}


def _cited_paths() -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for document in sorted(DOCS.rglob("*.md")):
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for raw in CITATION.findall(line):
                if PLACEHOLDER.search(raw) or "/" not in raw:
                    continue
                if raw.split("/")[0] not in ROOTED:
                    continue
                found.append((document, number, raw))
    return found


def test_every_rooted_python_path_cited_in_docs_is_a_file_that_exists() -> None:
    """The check itself. A citation that resolves nowhere is a reader sent nowhere."""

    cited = _cited_paths()
    # If this ever reaches zero the pattern has stopped matching and the test is asleep.
    assert len(cited) >= 40, f"expected the docs to cite rooted modules; found {len(cited)}"

    missing = [
        f"{document.relative_to(REPOSITORY_ROOT)}:{number} cites {raw}"
        for document, number, raw in cited
        if raw not in PROPOSED and not (REPOSITORY_ROOT / raw).exists()
    ]
    assert not missing, "\n".join(
        [
            "these citations name no file; a module under src/squadopt is not rooted at data/:",
            *missing,
        ]
    )


def test_a_proposed_path_is_listed_only_while_it_does_not_exist() -> None:
    """An allowance outlives its reason unless something removes it.

    Once a proposed file is created the entry stops being an allowance and becomes a lie
    about the repository, so the list has to shrink by itself rather than by anyone
    remembering.
    """

    created = [raw for raw in PROPOSED if (REPOSITORY_ROOT / raw).exists()]
    assert not created, (
        "these are listed as proposed and now exist; delete their entries: " + ", ".join(created)
    )
