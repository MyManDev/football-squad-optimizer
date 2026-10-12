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
one thing a pre-registration exists to prevent. Plans and notes are not frozen and are checked in
full. A dated record listed in `RECORDS` is checked in full except for a runner it names: it says
what was run on its day, so a runner retired since stays cited, as the command check excuses it.

The allowance is confined to the two directories a runner lives in. A protocol citing
`data/snapshots.py` is the ambiguity above, nothing about being a protocol makes it less wrong,
and a protocol's author has less to check a path against than anyone, not more.

A command is a citation too. When the manual capture shell was removed with 1.0.0 the live
runbooks kept telling an operator to run it, because the check above reads only backticked
rooted `.py` paths and a runbook writes `python -m scripts.<name>`. The second check reads that
form, a backticked `scripts.<name>`, and any `scripts/<name>.py`. A dated record keeps the
command that was run on its day, so the records are excused by name, and a living document may
name a removed module only in the paragraph that says it was removed: the same name on any
other line of that document is reported.

Both checks read the same documents: every Markdown file under `docs/`, the two root guides
`ARCHITECTURE.md` and `CONTRIBUTING.md`, and every `README.md` in the repository. A folder guide
cites modules and commands as often as a runbook does, and a reader takes either at its word.
The guides are found through git (tracked files and untracked ones it does not ignore), so a
dependency's README under an ignored folder is not read and a guide written in the same pull
request is.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"

#: The guides outside `docs/` that both checks read beside the documentation tree.
ROOT_GUIDES = ("ARCHITECTURE.md", "CONTRIBUTING.md")


def _folder_guides() -> list[Path]:
    """Every `README.md` git lists: tracked, or untracked and not ignored."""

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
            "--",
            "README.md",
            "*/README.md",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [REPOSITORY_ROOT / path for path in listing.split("\0") if path]


#: Every document both checks read, each once.
DOCUMENTS = tuple(
    sorted(
        {
            *DOCS.rglob("*.md"),
            *(REPOSITORY_ROOT / name for name in ROOT_GUIDES),
            *_folder_guides(),
        }
    )
)

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

#: Wrong citations in a guide under `scripts/`, which a pull request outside a release window
#: does not edit: the backend restart compares `src`, `scripts` and `docs/contracts` with the
#: live release (ADR 0010, context). Each entry is the document and the citation, with the path
#: it should name; the next change to that document fixes it and deletes the entry, and the
#: test below fails once an entry excuses nothing.
RELEASED_PATH_CITATIONS: dict[tuple[str, str], str] = {
    ("scripts/README.md", "data/sources/vaastav.py"): "src/squadopt/data/sources/vaastav.py",
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


def _is_a_runner_a_dated_record_ran(document: Path, raw: str) -> bool:
    """A dated record may name the runner that produced it after that runner is retired.

    The record states what was run on its day, which is why the command check below excuses
    the documents listed in `RECORDS`; rewriting the record to follow a retirement would edit
    evidence. The allowance is confined to the directories a runner lives in, so a record citing
    `data/snapshots.py` is still the ambiguity above.
    """

    relative = document.relative_to(REPOSITORY_ROOT).as_posix()
    return relative in RECORDS and raw.startswith(RUNNER_ROOTS)


def _cited_paths() -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for document in DOCUMENTS:
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
        and not _is_a_runner_a_dated_record_ran(document, raw)
        and (document.relative_to(REPOSITORY_ROOT).as_posix(), raw) not in RELEASED_PATH_CITATIONS
        and not (REPOSITORY_ROOT / raw).exists()
    ]
    assert not missing, "\n".join(
        [
            "these citations name no file; a module under src/squadopt is not rooted at data/:",
            *missing,
        ]
    )


def test_a_released_path_allowance_still_excuses_a_wrong_citation() -> None:
    """The allowance waits for the next edit of a released guide; it does not outlive it."""

    unresolved = {
        (document.relative_to(REPOSITORY_ROOT).as_posix(), raw)
        for document, _, raw in _cited_paths()
        if not (REPOSITORY_ROOT / raw).exists()
    }
    stale = [
        f"{document} {raw}"
        for document, raw in RELEASED_PATH_CITATIONS
        if (document, raw) not in unresolved
    ]
    assert not stale, "these allowances excuse nothing; delete them: " + ", ".join(stale)
    for corrected in RELEASED_PATH_CITATIONS.values():
        assert (REPOSITORY_ROOT / corrected).is_file(), corrected


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


SCRIPTS = REPOSITORY_ROOT / "scripts"

#: Every document a reader follows to run something.
COMMAND_DOCUMENTS = DOCUMENTS

#: `python -m scripts.<name>`: the whole dotted name must be a module.
COMMAND = re.compile(r"python3?(?:\.exe)?\s+-m\s+scripts\.([\w.<>{}*]+)")
#: A backticked `scripts.<name>`: a module, or a name a module binds at its top level (read
#: from the module's source, see `_names_bound_at_top_level`).
MODULE_NAME = re.compile(r"`scripts\.([\w.<>{}*]+)")
#: `scripts/<name>.py`, backticked or not, and not the tail of a longer path.
SCRIPT_PATH = re.compile(r"(?<![\w./-])scripts/([\w./<>{}*-]+?)\.py\b")

#: Dated records. Each keeps the commands of its day, and a command removed since is still
#: what was run then, so the whole document is excused.
RECORDS: dict[str, str] = {
    "docs/baseline_benchmark.md": "the real-data baseline benchmark of 2026-08-12",
    "docs/candidate_runtime.md": "the #43 candidate timing of 2026-08-16",
    "docs/chip_bayesopt_note.md": "the chip Bayesian search of 2026-08-18",
    "docs/fixture_group_conformal_note.md": "the fixture-group conformal reading of 2026-08-18",
    "docs/fw10_holdout_plan.md": "the form_window=10 locked-holdout plan of 2026-08-15",
    "docs/gw1_run_sheet.md": "the order of commands for Friday 2026-08-21",
    "docs/gw2_run_sheet.md": "the order of commands for Friday 2026-08-28",
    "docs/handover_2026-08-23.md": "the data and prediction handover of 2026-08-22",
    "docs/horizon_decay.md": "the horizon decay measurement of 2026-08-16",
    "docs/in_season_residual_export.md": "the in-season residual export of 2026-08-23",
    "docs/measurement_instrument.md": "the measurement instrument run of 2026-09-13",
    "docs/opening_newcomer_note.md": "the opening newcomer study of 2026-08-19",
    "docs/opponent_signal.md": "the opponent signal build of 2026-08-21",
    "docs/projection_uncertainty_v2_declaration.md": "the v2 uncertainty declaration of 2026-08-18",
    "docs/rank_objective_rehearsal_note.md": "the rank-objective rehearsal of 2026-08-18",
    "docs/route_a_declaration.md": "the Route A declaration of 2026-08-23",
    "docs/scenario_calibration_correction_note.md": "the corrected scenario audit of 2026-08-18",
}

#: A living document may name a removed module in the note that says it was removed. Only
#: these names are excused, and only on the lines of that note: the same name on any other
#: line of the document is checked like every other citation.
REMOVAL_NOTES: dict[str, frozenset[str]] = {
    "docs/architecture/decisions/0008-structure-investment.md": frozenset(
        {"build_opponent_signal"}
    ),
    "docs/architecture/platform_runtime.md": frozenset(
        {"run_gameweek_ops", "run_season_tick", "capture_deadline_snapshot"}
    ),
    "docs/experimentation_spec.md": frozenset({"run_screening_doe", "run_frozen_holdout"}),
    "docs/learned_prediction_spec.md": frozenset({"run_learned_benchmark"}),
    "docs/player_uncertainty_spec.md": frozenset({"run_player_risk_screening"}),
    "docs/risk_optimization_spec.md": frozenset({"run_risk_screening"}),
    "docs/scenario_spec.md": frozenset({"run_scenario_benchmark"}),
    "docs/uncertainty_spec.md": frozenset({"run_uncertainty_benchmark"}),
}

#: What makes a paragraph (a run of non-blank lines) a removal note. It is looked for in the
#: paragraph's lines joined by spaces, so a line break inside the phrase does not hide it, and
#: no line number is recorded, so an edit that moves the note does not break the allowance.
REMOVED = "been removed"


class Citation(NamedTuple):
    document: str
    line: int
    name: str
    resolves: bool
    excused: bool


def _is_a_module(dotted: str) -> bool:
    location = SCRIPTS.joinpath(*dotted.split("."))
    return location.with_suffix(".py").is_file() or (location / "__main__.py").is_file()


def _names_assigned(target: ast.expr) -> list[str]:
    """The names an assignment target binds: `a`, and each name unpacked from a tuple or list.

    An attribute or a subscript target binds no name of the module's own.
    """

    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _names_assigned(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _names_assigned(element)]
    return []


def _names_bound_at_top_level(source: str) -> frozenset[str]:
    """The names a module binds by definition, assignment or import at its top level.

    A statement nested in a top-level ``if`` or ``try`` counts too, since it also runs on
    import. A name bound inside a function or a class does not, and neither does a ``for``,
    ``with`` or ``:=`` target: a document citing one of those is reported, and should cite the
    module instead.
    """

    bound: set[str] = set()
    pending: list[ast.stmt] = list(ast.parse(source).body)
    while pending:
        statement = pending.pop()
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(statement.name)
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            bound.update(
                (alias.asname or alias.name).partition(".")[0] for alias in statement.names
            )
        elif isinstance(statement, ast.Assign):
            bound.update(name for target in statement.targets for name in _names_assigned(target))
        elif isinstance(statement, ast.AnnAssign):
            bound.update(_names_assigned(statement.target))
        elif isinstance(statement, ast.If):
            pending += [*statement.body, *statement.orelse]
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            pending += [*statement.body, *statement.orelse, *statement.finalbody]
            pending += [inner for handler in statement.handlers for inner in handler.body]
    return frozenset(bound)


def _is_bound_in_a_module(dotted: str) -> bool:
    """Whether `<module>.<name>` names a module under scripts/ and a name it binds."""

    module, _, name = dotted.rpartition(".")
    if not module:
        return False
    location = SCRIPTS.joinpath(*module.split("."))
    for source in (location.with_suffix(".py"), location / "__init__.py"):
        if source.is_file():
            return name in _names_bound_at_top_level(source.read_text(encoding="utf-8"))
    return False


def _removal_note_lines(lines: list[str]) -> frozenset[int]:
    """The line numbers, from 1, of every paragraph that says something has been removed."""

    note: set[int] = set()
    paragraph: list[int] = []
    for number, line in enumerate([*lines, ""], 1):
        if line.strip():
            paragraph.append(number)
            continue
        if REMOVED in " ".join(lines[held - 1].strip() for held in paragraph):
            note.update(paragraph)
        paragraph = []
    return frozenset(note)


def _scripts_cited_in(document: Path, text: str) -> list[Citation]:
    """Every scripts citation in one document's text.

    Placeholders are left out, and so is the runner a protocol names, by the allowance above.
    """

    relative = document.relative_to(REPOSITORY_ROOT).as_posix()
    lines = text.splitlines()
    removed_here = REMOVAL_NOTES.get(relative, frozenset())
    note = _removal_note_lines(lines) if removed_here else frozenset()
    found: list[Citation] = []
    for number, line in enumerate(lines, 1):
        cited: list[tuple[str, bool]] = []
        for name in (raw.rstrip(".") for raw in COMMAND.findall(line)):
            cited.append((name, _is_a_module(name)))
        for name in (raw.rstrip(".") for raw in MODULE_NAME.findall(line)):
            cited.append((name, _is_a_module(name) or _is_bound_in_a_module(name)))
        for name in SCRIPT_PATH.findall(line):
            cited.append((name.replace("/", "."), (SCRIPTS / f"{name}.py").is_file()))
        found.extend(
            Citation(
                relative,
                number,
                name,
                resolves,
                excused=relative in RECORDS or (number in note and name in removed_here),
            )
            for name, resolves in cited
            if not PLACEHOLDER.search(name)
            and not _is_a_runner_a_protocol_has_not_had_written_yet(
                document, "scripts/" + name.replace(".", "/") + ".py"
            )
        )
    return found


def _cited_scripts() -> list[Citation]:
    return [
        citation
        for document in COMMAND_DOCUMENTS
        for citation in _scripts_cited_in(document, document.read_text(encoding="utf-8"))
    ]


def test_every_scripts_command_a_document_cites_exists() -> None:
    """A runbook step that names a removed script sends the operator to an error at a deadline."""

    cited = _cited_scripts()
    # If this ever falls near zero the patterns have stopped matching and the test is asleep.
    assert len(cited) >= 100, f"expected the documents to cite scripts; found {len(cited)}"

    missing = [
        f"{citation.document}:{citation.line} cites scripts.{citation.name}"
        for citation in cited
        if not citation.resolves and not citation.excused
    ]
    assert not missing, "\n".join(
        [
            "these name no module under scripts/, or a name their module does not bind; a "
            "removed command's replacement is in the 'Retired compatibility commands' table of "
            "scripts/README.md:",
            *missing,
        ]
    )


def test_every_command_allowance_still_excuses_a_citation() -> None:
    """A record that no longer cites a removed command, or a note whose name came back or that
    no longer names it, is a stale allowance; delete the entry so the list shrinks by itself."""

    unresolved = [citation for citation in _cited_scripts() if not citation.resolves]
    stale = [document for document in RECORDS if document not in {c.document for c in unresolved}]
    in_a_note = {(c.document, c.name) for c in unresolved if c.excused}
    stale += [
        f"{document} {name}"
        for document, names in REMOVAL_NOTES.items()
        for name in sorted(names)
        if (document, name) not in in_a_note
    ]
    assert not stale, "these allowances excuse nothing; delete them: " + ", ".join(stale)


def test_a_removal_note_excuses_its_names_only_inside_the_note() -> None:
    """The note says the module is gone. A later line of the same document telling an operator
    to run it is the stale instruction this check exists to catch, so it is reported."""

    document = DOCS / "architecture" / "platform_runtime.md"
    text = "\n".join(
        [
            "The old `scripts.run_season_tick` and `scripts.gone_module` have been",
            "removed with 1.0.0.",
            "",
            "Run `python -m scripts.run_season_tick --execute` every fifteen minutes.",
        ]
    )
    cited = _scripts_cited_in(document, text)

    # Inside the note: the listed name is excused, a name the allowance does not list is not.
    assert [(c.line, c.name) for c in cited if c.excused] == [(1, "run_season_tick")]
    # Outside the note the listed name is reported like any other.
    assert [(c.line, c.name) for c in cited if not c.resolves and not c.excused] == [
        (1, "gone_module"),
        (4, "run_season_tick"),
    ]


def test_a_name_cited_in_a_module_is_one_the_module_binds() -> None:
    """`scripts.<module>.<name>` claims the name as well as the file, so both are checked."""

    text = "\n".join(
        [
            "See `scripts.run_measurement_preflight.main` here.",
            "See `scripts.run_measurement_preflight.no_such_name` here.",
            "See `scripts.no_such_module.main` here.",
        ]
    )
    cited = _scripts_cited_in(REPOSITORY_ROOT / "README.md", text)

    assert [(c.name, c.resolves) for c in cited] == [
        ("run_measurement_preflight.main", True),
        ("run_measurement_preflight.no_such_name", False),
        ("no_such_module.main", False),
    ]


def test_a_module_binds_its_top_level_names_and_no_others() -> None:
    """The source is parsed, not run, so a name that only appears in a target is a probe."""

    source = "\n".join(
        [
            "import os.path",
            "from json import dumps as to_json",
            "LIMIT: int = 3",
            "first, (second, [third, *rest]) = 1, (2, [3, 4])",
            "TABLE = {}",
            "TABLE[only_an_index] = 1",
            "only_an_owner.attribute = 1",
            "for loop_variable in range(1):",
            "    FROM_A_LOOP = 1",
            "class Runner:",
            "    inside_the_class = 1",
            "async def fetch() -> None: ...",
            "def main() -> None:",
            "    inside_the_function = 1",
            "if True:",
            "    FROM_AN_IF = 1",
            "else:",
            "    FROM_AN_ELSE = 1",
            "try:",
            "    import tomllib",
            "except ImportError:",
            "    FROM_A_HANDLER = None",
            "finally:",
            "    FROM_A_FINALLY = 1",
        ]
    )

    assert _names_bound_at_top_level(source) == {
        "os",
        "to_json",
        "LIMIT",
        "first",
        "second",
        "third",
        "rest",
        "TABLE",
        "Runner",
        "fetch",
        "main",
        "FROM_AN_IF",
        "FROM_AN_ELSE",
        "tomllib",
        "FROM_A_HANDLER",
        "FROM_A_FINALLY",
    }


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


def test_the_record_allowance_covers_a_runner_and_nothing_else() -> None:
    """A dated record keeps the runner of its day; nothing else in it is excused, and a living
    document that cites the same retired runner is reported."""

    record = DOCS / "route_a_declaration.md"
    living = DOCS / "architecture" / "system_map.md"

    assert record.relative_to(REPOSITORY_ROOT).as_posix() in RECORDS
    assert _is_a_runner_a_dated_record_ran(record, "scripts/build_opponent_signal.py")
    # The ambiguity this file exists to catch, inside a record.
    assert not _is_a_runner_a_dated_record_ran(record, "data/snapshots.py")
    assert not _is_a_runner_a_dated_record_ran(living, "scripts/build_opponent_signal.py")
