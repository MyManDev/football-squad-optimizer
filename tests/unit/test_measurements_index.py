"""ADR 0003 rule 1, enforced instead of remembered.

The rule reads: **"Every committed artifact has a row in `measurements_index.md`. No row, no
commit."** Nothing checked it, and when it was measured the repository was at 56 of 78 — the
rule had been decaying quietly for weeks, which is what happens to a rule with no test.

The exemption tuple below is the debt that existed when the check was written. It works the
way ``ignore_imports`` in ``pyproject.toml`` works, and it carries the same obligation:

    **It may only shrink. If this test fails, add the row — do not add the file here.**

Growing the list turns a governance rule back into a suggestion, which is exactly the state
this test exists to leave behind. The exemptions belong to measurements this side did not run,
so the rows are theirs to write; the list is the record of what is owed, not permission to owe
more.
"""

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"
INDEX = DOCS / "measurements_index.md"

# Committed artifacts that predate this check and have no row yet. May only shrink.
# Every entry is a measurement this side did not run, so its finding is not ours to write.
UNLISTED_AT_THE_TIME_OF_WRITING: tuple[str, ...] = (
    "baseline_benchmark.json",
    "mode_rehearsal_asiri_agresif.json",
    "mode_rehearsal_garantici.json",
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
    "template_rival_strength_2021-22.json",
    "template_rival_strength_2022-23.json",
    "template_rival_strength_2023-24.json",
    "transfer_discipline_rolling.json",
)


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
    """ADR 0003 rule 1. The exemption tuple may only shrink -- add the row, not the file."""

    outstanding = sorted(set(unlisted_artifacts()) - set(UNLISTED_AT_THE_TIME_OF_WRITING))

    assert not outstanding, (
        "These committed artifacts have no row in docs/measurements_index.md, which ADR 0003 "
        f"rule 1 forbids: {outstanding!r}. Write the row. Do not add them to "
        "UNLISTED_AT_THE_TIME_OF_WRITING -- that tuple is the debt this check inherited and it "
        "may only shrink."
    )


def test_the_exemption_list_does_not_outlive_its_files() -> None:
    """A stale exemption is a claim about a file that is no longer there.

    Left unchecked the tuple would slowly become fiction, and a fictional exemption hides the
    fact that the debt was paid.
    """

    present = set(_committed_artifacts())
    stale = sorted(name for name in UNLISTED_AT_THE_TIME_OF_WRITING if name not in present)

    assert not stale, (
        f"These files are exempt but no longer committed: {stale!r}. Remove them from "
        "UNLISTED_AT_THE_TIME_OF_WRITING; the list shrinking is the point."
    )


def test_an_exempt_artifact_is_not_also_listed() -> None:
    """Once a row exists the exemption must go, or the list stops meaning anything."""

    named = _names_in_index()
    both = sorted(name for name in UNLISTED_AT_THE_TIME_OF_WRITING if Path(name).stem in named)

    assert not both, f"These artifacts now have a row and must leave the exemption list: {both!r}."


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
