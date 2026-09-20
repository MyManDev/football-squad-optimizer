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

One allowance is structural rather than listed. A pre-registration names the runner that will
write its record, and pre-registration means the protocol is committed before the measurement
is run, so that runner routinely does not exist yet: nine citations across five protocols are
of this shape, and today exactly one of them resolves nowhere, because its record is still in
review. Requiring it to resolve would order the merges of a protocol and the record fulfilling
it, which is backwards.

The allowance covers a runner that resolves today as well as one that does not, and that is
deliberate rather than an oversight in the ordering of the clauses. **A protocol is frozen when
it merges.** It names what the runner was called at pre-registration, and if the runner is later
renamed the protocol is still an accurate record of what was registered; making this check drag
protocols after a rename would have it demand edits to pre-registered documents, which is the
one thing a pre-registration exists to prevent. Records, plans and notes are not frozen and are
checked in full.

The allowance is confined to the two directories a runner lives in. A protocol citing
`data/snapshots.py` is the ambiguity above, nothing about being a protocol makes it less wrong,
and a protocol's author has less to check a path against than anyone, not more.
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


#: Where a measurement runner lives. Only a citation under one of these can be the forward
#: reference a pre-registration is entitled to make.
RUNNER_ROOTS = ("scripts/", "src/squadopt/experiments/")


def _is_a_runner_a_protocol_has_not_had_written_yet(document: Path, raw: str) -> bool:
    """A pre-registration may name the runner that will produce its record.

    The protocol is committed before the run by design, so the runner arrives later, in the
    pull request that carries the record. Every other citation in the same document is held to
    the same standard as any other document's.
    """

    return document.name.endswith("_prereg.md") and raw.startswith(RUNNER_ROOTS)


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
        if raw not in PROPOSED
        and not _is_a_runner_a_protocol_has_not_had_written_yet(document, raw)
        and not (REPOSITORY_ROOT / raw).exists()
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


def test_the_protocol_allowance_covers_a_runner_and_nothing_else() -> None:
    """The allowance is the reason it was written, not the document it was written for.

    Widening it to any unresolved path in a protocol would excuse the citation this file
    exists to catch, in the documents most exposed to it: a protocol is written before the
    code, so its author has nothing to check a path against.
    """

    protocol = DOCS / "positional_defence_prereg.md"
    record = DOCS / "positional_defence.md"

    assert _is_a_runner_a_protocol_has_not_had_written_yet(
        protocol, "scripts/measure_positional_defence.py"
    )
    assert _is_a_runner_a_protocol_has_not_had_written_yet(
        protocol, "src/squadopt/experiments/positional_defence.py"
    )
    # The ambiguity this file exists to catch, inside a protocol.
    assert not _is_a_runner_a_protocol_has_not_had_written_yet(protocol, "data/snapshots.py")
    # A protocol is written before its runner. A record is written by one that ran.
    assert not _is_a_runner_a_protocol_has_not_had_written_yet(
        record, "scripts/measure_positional_defence.py"
    )
