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


def _committed_artifacts() -> list[str]:
    """The committed JSON artifacts the rule applies to."""

    return sorted(path.name for path in DOCS.glob("*.json"))


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

    outstanding = sorted(set(unlisted_artifacts()) - set(EXEMPT))

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
