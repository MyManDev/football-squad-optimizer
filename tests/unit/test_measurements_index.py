"""ADR 0003 rule 1, enforced instead of remembered.

The rule reads: **"Every committed artifact has a row in `measurements_index.md`. No row, no
commit."** Nothing checked it -- searching `tests/` for `measurements_index` returned nothing --
and 22 of the 78 committed artifacts were named nowhere in the index.

That headline number is not the violation, though, and this file is careful about the
difference. ADR 0003 rule 4 grandfathers the 54 artifacts that existed when the ADR landed
(commit ``c530b74``, 2026-08-18) and says plainly that "the rule applies from here". Splitting
the 22 against that commit gives:

- 3 that were mine, now written (see the index rows for ``issue43_candidate_declaration``,
  ``learned_benchmark_development`` and ``production_gate_judgement``);
- 14 grandfathered by rule 4, which owe nothing;
- **5 committed after the ADR with no row, which is the actual breach of rule 1.**

Both remaining groups are declared below, separately, because they mean different things: one is
a closed historical set and the other is debt. Merging them into a single "known exceptions"
tuple would have let the second hide inside the first.

## What this file does and does not cover

The first version globbed ``docs/*.json`` only, and said it enforced rule 1. It half enforced
it. ADR 0003's record tier is **"markdown, plus JSON under ~250 KB"**, so markdown records are
artifacts too, and `docs/` holds more markdown (150 files) than JSON (80). #258 demonstrated the
gap on its first outing: two generated markdown records landed with no row and nothing noticed.

Markdown is now in scope **when a committed JSON of the same stem exists** -- that pair is one
artifact published in two forms, sharing one row, so no guessing is involved and 77 files come
in at once.

Markdown with no JSON twin stays **out** of automatic scope, deliberately. Separating a
generated record from prose by filename cannot be done reliably: ``weekly_scorecard.md`` is a
record and ``data_contract.md`` is not, and no marker distinguishes them. Grepping for the paths
the code writes conflates writes with references -- it returns ``data_contract.md``, which is
only read. The alternative is an allowlist of some fifty prose documents, which would rot. So the
limit is asserted by a test rather than left for a reader to assume, and the twinless records
that matter are pinned by name.
"""

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"
INDEX = DOCS / "measurements_index.md"
ADR = DOCS / "architecture" / "decisions" / "0003-measurement-artifacts.md"

# Artifacts that already existed when ADR 0003 landed and that rule 4 grandfathers: "No
# retroactive purge... The rule applies from here." A closed set -- the commit it is defined
# against cannot gain members -- so nothing may ever be added here. Rows would still be an
# improvement; they are simply not owed.
GRANDFATHERED_BY_RULE_4: tuple[str, ...] = (
    "baseline_benchmark.json",
    "opening_backtest.json",
    "rank_objective_rehearsal_heldout.json",
    "risk_frontier_shrunk.json",
    "scenario_calibration_audit_dev_dgw.json",
    "scenario_calibration_audit_development.json",
    "scenario_calibration_audit_development_disp.json",
    "scenario_calibration_audit_located_k10.json",
    "scenario_calibration_audit_located_k2.json",
    "scenario_calibration_audit_online.json",
    "scenario_calibration_audit_online_dgw.json",
    "scenario_calibration_audit_online_disp.json",
    "scenario_calibration_audit_shrunk.json",
    "transfer_discipline_rolling.json",
)

# Committed after ADR 0003 with no row: rule 1 is owed here, and this tuple is the debt.
# It works the way ``ignore_imports`` in ``pyproject.toml`` works and carries the same
# obligation:
#
#     **It may only shrink. If this test fails, add the row -- do not add the file here.**
#
# Growing it turns a governance rule back into a suggestion, which is the state this test
# exists to leave behind. These are measurements this side did not run, so the findings are not
# ours to phrase and the rows are not ours to write; the tuple is the record of what is owed.
UNLISTED_AT_THE_TIME_OF_WRITING: tuple[str, ...] = ()

EXEMPT: tuple[str, ...] = GRANDFATHERED_BY_RULE_4 + UNLISTED_AT_THE_TIME_OF_WRITING

# Two generated markdown records with no JSON twin, so the twin rule cannot see them. They are
# the settle chain's outputs and the reason the markdown gap was found; naming them is the only
# thing that keeps them covered.
TWINLESS_RECORDS_PINNED_BY_NAME: tuple[str, ...] = (
    "season_ledger_2026-27.md",
    "weekly_scorecard.md",
)


def _exempt_stems() -> set[str]:
    """Exemptions are per *artifact*, so one entry covers a record's JSON and markdown alike."""

    return {Path(name).stem for name in EXEMPT}


def _committed_artifacts() -> list[str]:
    """The committed record files rule 1 applies to.

    JSON, plus markdown that has a committed JSON of the same stem: one artifact in two forms,
    one row. Twinless markdown is out of scope on purpose -- see the module docstring, and the
    test that asserts the limit rather than leaving it implied.
    """

    json_names = sorted(path.name for path in DOCS.glob("*.json"))
    stems = {Path(name).stem for name in json_names}
    twinned = sorted(path.name for path in DOCS.glob("*.md") if path.stem in stems)
    return json_names + twinned + sorted(TWINLESS_RECORDS_PINNED_BY_NAME)


def _names_in_index() -> set[str]:
    """Every backticked name anywhere in the index, reduced to a bare stem.

    Every occurrence, not only the first cell of each row, because rows legitimately name
    more than one artifact -- ``fw10_screening`` + ``fw10_frozen_candidate`` is one row for
    two files. A matcher that read only the first cell reported 8 unlisted artifacts when the
    real number was 22, which is the kind of wrong answer that looks like a passing check.
    """

    text = INDEX.read_text(encoding="utf-8")
    return {
        name.rsplit("/", 1)[-1].removesuffix(".json").removesuffix(".md")
        for name in re.findall(r"`([A-Za-z0-9_./-]+)`", text)
    }


def unlisted_artifacts() -> list[str]:
    """Committed artifacts the index does not mention anywhere."""

    named = _names_in_index()
    return [name for name in _committed_artifacts() if Path(name).stem not in named]


# --- the rule itself ---------------------------------------------------------


def test_every_committed_artifact_is_named_in_the_index() -> None:
    """ADR 0003 rule 1. The debt tuple may only shrink -- add the row, not the file."""

    excused = _exempt_stems()
    outstanding = sorted(name for name in unlisted_artifacts() if Path(name).stem not in excused)

    assert not outstanding, (
        "These committed artifacts have no row in docs/measurements_index.md, which ADR 0003 "
        f"rule 1 forbids: {outstanding!r}. Write the row. Do not add them to "
        "UNLISTED_AT_THE_TIME_OF_WRITING -- that tuple is the debt this check inherited and it "
        "may only shrink."
    )


def test_the_grandfathering_this_file_leans_on_is_still_in_the_adr() -> None:
    """The larger exemption is only legitimate while rule 4 says so.

    If rule 4 were ever withdrawn, 14 artifacts would silently stay excused by a tuple whose
    justification no longer existed. The exemption should fail with the rule, not outlive it.

    Whitespace is collapsed first because the sentence is wrapped in the source and a literal
    search for it silently found nothing -- a check that fails for the wrong reason is only
    marginally better than one that passes for the wrong reason.
    """

    text = " ".join(ADR.read_text(encoding="utf-8").split())

    assert "artifacts are grandfathered" in text
    assert "No retroactive purge" in text
    assert "The rule applies from here." in text


def test_the_two_exemptions_are_kept_apart() -> None:
    """Grandfathered is not debt, and debt must not be able to hide inside it."""

    assert not set(GRANDFATHERED_BY_RULE_4) & set(UNLISTED_AT_THE_TIME_OF_WRITING)
    assert len(EXEMPT) == len(set(EXEMPT))


def test_the_exemption_list_does_not_outlive_its_files() -> None:
    """A stale exemption is a claim about a file that is no longer there.

    Left unchecked either tuple would slowly become fiction, and a fictional exemption hides
    the fact that the debt was paid.
    """

    present = set(_committed_artifacts())
    stale = sorted(name for name in EXEMPT if name not in present)

    assert not stale, (
        f"These files are exempt but no longer committed: {stale!r}. Remove them; the lists "
        "shrinking is the point."
    )


def test_an_exempt_artifact_is_not_also_listed() -> None:
    """Once a row exists the exemption must go, or the lists stop meaning anything."""

    named = _names_in_index()
    both = sorted(name for name in EXEMPT if Path(name).stem in named)

    assert not both, f"These artifacts now have a row and must leave the exemption lists: {both!r}."


# --- what is in scope, and what is not ---------------------------------------


def test_markdown_with_a_json_twin_is_in_scope() -> None:
    """The record tier is "markdown, plus JSON", so the markdown half is an artifact too."""

    covered = set(_committed_artifacts())

    assert "fw10_holdout.json" in covered
    assert "fw10_holdout.md" in covered


def test_one_exemption_entry_covers_both_forms_of_the_same_artifact() -> None:
    """Grandfathering is per artifact, not per file.

    Widening the glob to markdown surfaced fourteen ``.md`` siblings of the fourteen already
    exempt ``.json`` records -- the same debt, previously counted once. Excusing them by stem
    keeps the tuple a list of artifacts instead of doubling it into a list of files.
    """

    covered = set(_committed_artifacts())
    excused = _exempt_stems()

    assert "baseline_benchmark.md" in covered
    assert "baseline_benchmark.md" not in EXEMPT
    assert Path("baseline_benchmark.md").stem in excused


def test_twinless_markdown_is_out_of_automatic_scope() -> None:
    """The limit, asserted rather than implied.

    Telling a generated record from prose by filename cannot be done reliably --
    ``weekly_scorecard.md`` is a record and ``data_contract.md`` is not, with no marker between
    them. So twinless markdown is not swept in, and this test exists so nobody reads the widened
    glob as full coverage. The twinless records that matter are pinned by name instead.
    """

    covered = set(_committed_artifacts())

    assert "data_contract.md" not in covered
    assert "handoff_acceptance_checklist.md" not in covered
    for name in TWINLESS_RECORDS_PINNED_BY_NAME:
        assert name in covered


def test_the_settle_records_that_found_this_gap_stay_listed() -> None:
    """#258 landed both with no row while the JSON-only glob watched. Keep them pinned."""

    named = _names_in_index()

    assert "weekly_scorecard" in named
    assert "season_ledger_2026-27" in named


# --- the check itself has to be able to fail ---------------------------------


def test_the_matcher_finds_a_row_that_names_two_artifacts() -> None:
    """The property the first version of this matcher got wrong."""

    named = _names_in_index()

    assert "fw10_screening" in named
    assert "fw10_frozen_candidate" in named


def test_the_matcher_would_notice_an_unlisted_artifact() -> None:
    """A guard that cannot fail guards nothing, so prove it separates the two cases."""

    named = _names_in_index()

    assert "fw10_holdout" in named
    assert "an_artifact_nobody_committed" not in named


def test_the_index_exists_and_carries_rows() -> None:
    """If the file were renamed the checks above would pass on an empty set."""

    text = INDEX.read_text(encoding="utf-8")

    assert text.startswith("# Measurements Index")
    assert text.count("\n| `") > 50


# --- the header must not contradict the table -------------------------------


def test_the_header_does_not_deny_a_holdout_read_the_table_records() -> None:
    """The specific contradiction this file was written alongside.

    The header used to claim nothing in the index had read the locked holdout, while the table
    carried the holdout run itself. Either the claim goes or the row does, and the row is
    required by rule 1 -- so the claim went.
    """

    text = INDEX.read_text(encoding="utf-8")
    header = text.split("## ", 1)[0]
    records_a_holdout_read = "fw10_holdout" in _names_in_index()

    if records_a_holdout_read:
        assert "nothing here" not in header or "read the 2025-26 locked holdout" not in header, (
            "The index records an artifact that read the locked holdout while its header "
            "denies any such read. A header a reader trusts must not contradict its table."
        )
        assert "locked 2025-26 holdout" in header or "locked holdout" in header, (
            "The header should say plainly that one artifact read the holdout, rather than "
            "going silent about it."
        )
