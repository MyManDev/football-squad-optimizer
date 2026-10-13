"""A committed record says which code produced it, and the list of those that cannot only shrinks.

Measured on 2026-09-20 across the 109 dict-shaped records under `docs/`: 91 name the commit
that produced them and 18 do not. This file does not repair the 18. It freezes them, so that a
record written tomorrow cannot quietly become the nineteenth.

A record is the only evidence that a measurement happened, and a reader deciding whether to
trust one asks which code produced it. A record that cannot answer is not wrong, it is
unfalsifiable, which is a worse thing for evidence to be: nothing about it can ever be checked
and it will read as authoritative for as long as it exists.

Only the repository's own commit counts. `archive_commit` and `dataset_commit` appear in most
of these records and name the **data** the run read, which is a different claim and does not
answer the question this file asks. Conflating the two is how a first pass at this measurement
reported 90 of 108 records naming their code when 82 of the hits were the archive.

The list below carries one collective reason rather than eighteen invented ones. Each of these
needs its own judgement about which stamp is honest for it, because the wide stamp names an
archive commit and a manifest digest, and for a runner that never opens the archive that would
trade a missing field for a false one. Where that judgement has not been made, saying so is
better than guessing at it per file.

Removing an entry is not a repair of the record. A committed record is the run that happened,
and re-running one to fix a metadata field replaces a measurement with a different one. An
entry leaves this list when a **later** run of that measurement writes a record that names its
commit.

## Records under `docs/research`

Since 2026-10-13 the check also reads the JSON records in `docs/research/` (a deferred move of
ADR 0010), named by their path below `docs/`, such as ``research/planning_shortlist.json``. Of
the 20 there that day, one names the commit that produced it and 19 do not; the 19 are frozen
in their own list under the same rule, so a twenty-first fails. Eight of the 19 carry a commit
under a key the check does not count (``base_commit``, ``commit``, ``measured_code_commit``,
``measured_source_commit``, ``repository_base_commit``, ``source_base_commit`` and
``source_commit``). Some of those may name the code that ran and some name a base the run
changed; telling which needs a judgement per record, the same judgement the root list leaves
open, so they are listed with the rest rather than counted.

One of the 19, ``research/football_information_worlds.json``, is a list rather than an object.
The scan reads a list the same way, so a record's shape does not take it out of the check;
every record at the root of `docs/` is an object.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"

#: A hex string long enough to identify a commit. Abbreviated hashes are accepted because some
#: records were written with `--short`, and a short hash still resolves.
SHA = re.compile(r"^[0-9a-f]{7,40}$")

#: The keys that answer "which code ran". Deliberately not `archive_commit` or `dataset_commit`,
#: which answer "which data was read". A record may carry both and most do.
CODE_COMMIT_KEYS = frozenset({"repository_commit", "producer_repository_commit", "repo_commit"})

#: The 18 records present on 2026-09-20 that name no producing commit. See the module docstring
#: for why there is one shared reason rather than eighteen, and for what removes an entry.
WITHOUT_A_COMMIT: frozenset[str] = frozenset(
    {
        "capture_lead_time.json",
        "capture_season_phase.json",
        "chip_forecast_rule.json",
        "chip_threshold_induction.json",
        "fw10_frozen_candidate.json",
        "in_season_blend_benchmark.json",
        "issue43_candidate_declaration.json",
        "learned_benchmark_development.json",
        "live_projection_audit.json",
        "member_plan_determinism.json",
        "member_policy_hit_cost_grid.json",
        "member_window_proofs.json",
        "opponent_signal.json",
        "production_gate_judgement.json",
        "rank_tail_selector_inertness.json",
        "recalibration_dry_run.json",
        "route_a_declaration.json",
        "settled_outcomes.json",
    }
)

#: The 19 records under `docs/research/` on 2026-10-13 that name no producing commit, by their
#: path below `docs/`. Kept apart from the root list because they joined the check later and
#: under a different count; the rule for leaving is the same. **It may only shrink.**
RESEARCH_WITHOUT_A_COMMIT: frozenset[str] = frozenset(
    {
        "research/calendar_chip_tail.json",
        "research/continuation_diagnostic.json",
        "research/explicit_lookahead_measurement.json",
        "research/football_candidate_development_record.json",
        "research/football_complete_policy_acceptance.json",
        "research/football_defcon_development.json",
        "research/football_information_worlds.json",
        "research/football_planning_replay.json",
        "research/football_role_followups_2026_10_03.json",
        "research/football_role_reference_2026_10_03.json",
        "research/football_sequential_minutes.json",
        "research/football_single_swap_2026_10_03.json",
        "research/football_window_totals.json",
        "research/incumbent_refinement_measurement.json",
        "research/observed_rollout_measurement.json",
        "research/planning_shortlist.json",
        "research/planning_shortlist_matrix.json",
        "research/temporal_refinement_measurement.json",
        "research/triple_refinement_measurement.json",
    }
)

#: The folders whose JSON files the check reads, relative to `docs/` ("" is the root).
RECORD_FOLDERS: tuple[str, ...] = ("", "research")


def _commit_bearing_keys(value: object) -> list[str]:
    """Every key anywhere in the document whose value looks like a commit."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and SHA.match(child):
                found.append(key)
            found.extend(_commit_bearing_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_commit_bearing_keys(child))
    return found


def _records() -> dict[str, bool]:
    """Each record in the record folders, named by its path below `docs/`, against whether it
    names the code that produced it."""

    named: dict[str, bool] = {}
    for path in sorted(
        path for folder in RECORD_FOLDERS for path in (DOCS / folder).glob("*.json")
    ):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict | list):
            continue
        name = path.relative_to(DOCS).as_posix()
        named[name] = bool(set(_commit_bearing_keys(document)) & CODE_COMMIT_KEYS)
    return named


def test_a_record_written_from_now_on_names_the_code_that_produced_it() -> None:
    """The check itself. The listed records are excused; any other one is a defect."""

    records = _records()
    # If either count collapses a glob has stopped matching and the check is asleep.
    root = [name for name in records if "/" not in name]
    research = [name for name in records if name.startswith("research/")]
    assert len(root) >= 100, f"expected the docs to hold records; found {len(root)}"
    assert len(research) >= 20, f"expected docs/research to hold records; found {len(research)}"

    unnamed = sorted(name for name, named in records.items() if not named)
    new = [name for name in unnamed if name not in WITHOUT_A_COMMIT | RESEARCH_WITHOUT_A_COMMIT]
    assert not new, (
        "these records name no producing commit and are not on a frozen list; a record that "
        "cannot say which code wrote it cannot be checked by anyone, ever: " + ", ".join(new)
    )


def test_the_frozen_lists_only_shrink() -> None:
    """An allowance outlives its reason unless something removes it.

    Once a measurement is run again by a runner that stamps its commit, the entry stops being
    a statement about the repository and becomes a false one, so the lists have to shrink by
    themselves rather than by anyone remembering.
    """

    records = _records()
    listed = WITHOUT_A_COMMIT | RESEARCH_WITHOUT_A_COMMIT
    repaired = sorted(name for name in listed if records.get(name))
    assert not repaired, (
        "these are listed as naming no commit and now name one; delete their entries: "
        + ", ".join(repaired)
    )

    departed = sorted(name for name in listed if name not in records)
    assert not departed, (
        "these are listed but no longer exist under docs/; delete their entries: "
        + ", ".join(departed)
    )


def test_the_two_lists_are_kept_apart() -> None:
    """The root list names records at the root of `docs/`, the research list names records in
    `docs/research/`, and no record is on both."""

    assert not WITHOUT_A_COMMIT & RESEARCH_WITHOUT_A_COMMIT
    assert all("/" not in name for name in WITHOUT_A_COMMIT)
    assert all(name.startswith("research/") for name in RESEARCH_WITHOUT_A_COMMIT)


def test_a_commit_under_another_key_is_not_counted() -> None:
    """`football_single_swap_2026_10_03.json` names a `source_commit` and no key the check
    counts, so it is on the research list rather than read as naming its code."""

    path = DOCS / "research" / "football_single_swap_2026_10_03.json"
    keys = set(_commit_bearing_keys(json.loads(path.read_text(encoding="utf-8"))))

    assert "source_commit" in keys
    assert not keys & CODE_COMMIT_KEYS
    assert "research/football_single_swap_2026_10_03.json" in RESEARCH_WITHOUT_A_COMMIT


def test_a_list_shaped_record_is_read() -> None:
    """A record that is a list is walked like an object, so its shape does not excuse it."""

    assert _commit_bearing_keys([{"repository_commit": "0123abc"}]) == ["repository_commit"]
    assert "research/football_information_worlds.json" in _records()


def test_the_data_a_run_read_is_not_mistaken_for_the_code_that_ran() -> None:
    """The distinction the whole file turns on, pinned against a real record.

    `learned_benchmark_development.json` carries a `dataset_commit` and no repository commit.
    If the check ever counted that, this record would read as provenanced when it names only
    the data it read, and the eighteen would silently become seventeen without anything being
    fixed.
    """

    assert "archive_commit" not in CODE_COMMIT_KEYS
    assert "dataset_commit" not in CODE_COMMIT_KEYS

    path = DOCS / "learned_benchmark_development.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    keys = set(_commit_bearing_keys(document))

    assert "dataset_commit" in keys
    assert not keys & CODE_COMMIT_KEYS
    assert path.name in WITHOUT_A_COMMIT
