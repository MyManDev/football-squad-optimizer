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

## Records under `docs/research`

Records are read from three folders: the root of `docs/`, `docs/architecture/` and, since
2026-10-13, `docs/research/` (a deferred move of ADR 0010). A record below the root is named by
its path relative to `docs/`, such as ``research/calendar_chip_tail.json``, and the twin rule
pairs a Markdown file only with the JSON of the same stem in the same folder.

The research rows name their records by a Markdown link, ``[record](research/<name>.json)``,
more often than by a backticked name, so the matcher reads link targets as well. Read by
backticks alone, 13 of the 20 JSON records in `docs/research/` had no row; with link targets,
two did (`football_complete_policy_acceptance` and `football_information_worlds`), and they
were given rows in the same change, so no research record is on the debt tuple. The matcher
still reduces every name to a bare stem, which is only sound while no two records share one,
and a test holds that.

`docs/research/evidence/` is not read: it holds a committed copy of one measurement's receipts,
which its readout, `football_joint_role_minutes_2026_10_02.md`, cites and which has its own row.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

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
# Widening the check to `docs/research/` on 2026-10-13 added nothing here: the two research
# records without a row were given rows in the same change.
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


# The folders whose JSON files are records, relative to ``docs/`` ("" is the root). Not
# ``docs/**``: rule 1 has no directory clause, but ``docs/contracts/*.schema.json`` are schemas
# the code validates against, not measurements, and a recursive glob would demand rows for them.
# The first artifact to land outside ``docs/`` was a serving-capacity record under
# ``docs/architecture/``, and the glob missed it for a day; the record tier is named by
# content, not by directory. ``docs/research/`` joined on 2026-10-13 (see the module docstring).
RECORD_FOLDERS: tuple[str, ...] = ("", "architecture", "research")


def _record_name(path: Path) -> str:
    """A record's path relative to ``docs/``: a bare name at the root, with its folder below."""

    return path.relative_to(DOCS).as_posix()


def _record_json() -> list[Path]:
    """Every committed JSON record in the record folders."""

    return sorted(
        path
        for folder in RECORD_FOLDERS
        for path in (DOCS / folder).glob("*.json")
        if not path.name.endswith(".schema.json")
    )


def _committed_artifacts() -> list[str]:
    """The committed record files rule 1 applies to, named relative to ``docs/``.

    JSON, plus markdown that has a committed JSON of the same stem in the same folder: one
    artifact in two forms, one row. Twinless markdown is out of scope on purpose -- see the
    module docstring, and the test that asserts the limit rather than leaving it implied.
    """

    json_paths = _record_json()
    twins = {path.with_suffix(".md") for path in json_paths}
    twinned = sorted(
        _record_name(path)
        for folder in RECORD_FOLDERS
        for path in (DOCS / folder).glob("*.md")
        if path in twins
    )
    return (
        [_record_name(path) for path in json_paths]
        + twinned
        + sorted(TWINLESS_RECORDS_PINNED_BY_NAME)
    )


def _stem(reference: str) -> str:
    """A name or link target from the index, reduced to a bare stem."""

    path = reference.split("#", 1)[0].rsplit("/", 1)[-1]
    return path.removesuffix(".json").removesuffix(".md")


def _backticked_names(text: str) -> set[str]:
    """Every backticked name in `text`, as a bare stem."""

    return {_stem(name) for name in re.findall(r"`([A-Za-z0-9_./-]+)`", text)}


def _linked_names(text: str) -> set[str]:
    """Every Markdown link target in `text`, without its anchor, as a bare stem."""

    return {_stem(target) for target in re.findall(r"\]\(<?([^)\s>]+)>?(?:\s[^)]*)?\)", text)}


def _names_in_index() -> set[str]:
    """Every backticked name and every link target anywhere in the index, as bare stems.

    Every occurrence, not only the first cell of each row, because rows legitimately name
    more than one artifact -- ``fw10_screening`` + ``fw10_frozen_candidate`` is one row for
    two files. A matcher that read only the first cell reported 8 unlisted artifacts when the
    real number was 22, which is the kind of wrong answer that looks like a passing check.
    Link targets count because the research rows name their records by a link
    (``[record](research/<name>.json)``) more often than by a backticked name.
    """

    text = INDEX.read_text(encoding="utf-8")
    return _backticked_names(text) | _linked_names(text)


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


def test_the_research_records_are_in_scope() -> None:
    """`docs/research/` holds records too, named by their path below `docs/`.

    A readout with no JSON of its own stem stays out, as at the root, and so does the copied
    receipt under `docs/research/evidence/`, which its readout's row covers.
    """

    covered = set(_committed_artifacts())

    assert "research/calendar_chip_tail.json" in covered
    assert "research/calendar_chip_tail.md" in covered
    assert "research/football_information_worlds.json" in covered
    assert "research/football_candidate_results.md" not in covered
    assert not [name for name in covered if name.startswith("research/evidence/")]
    assert len([name for name in covered if name.startswith("research/")]) >= 20


def test_a_stem_names_one_record() -> None:
    """The matcher reduces every name to a bare stem, which is only sound while stems differ.

    If a record in one folder shared its stem with a record in another, a row for either would
    excuse both, and the check would pass on a record nobody listed.
    """

    stems = [path.stem for path in _record_json()]

    assert sorted({stem for stem in stems if stems.count(stem) > 1}) == []


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


def test_the_matcher_reads_a_markdown_link_target() -> None:
    """The research rows name `calendar_chip_tail` only by links, never in backticks."""

    text = INDEX.read_text(encoding="utf-8")

    assert "calendar_chip_tail" not in _backticked_names(text)
    assert "calendar_chip_tail" in _linked_names(text)
    assert "calendar_chip_tail" in _names_in_index()
    assert _linked_names("[a](research/x.json#top) [b](<y.md>) [c](../z.md 'title')") == {
        "x",
        "y",
        "z",
    }


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


def test_every_artifact_that_flags_a_holdout_read_is_named_in_the_header() -> None:
    """The same rule, derived from the artifacts instead of from one remembered name.

    The check above pattern-matches the ``fw10_holdout`` wording, so it kept passing while a
    second artifact landed carrying ``locked_holdout_accessed: true`` and the header went on
    enumerating the reads as one. Which artifacts read the locked season is a fact their own
    committed JSON states; the header has to agree with it, whoever adds the next row.
    """

    header = INDEX.read_text(encoding="utf-8").split("## ", 1)[0]
    documents = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in _record_json()}
    flagged = sorted(
        stem
        for stem, document in documents.items()
        if isinstance(document, dict) and document.get("locked_holdout_accessed") is True
    )
    unnamed = [stem for stem in flagged if f"`{stem}`" not in header]

    assert not unnamed, (
        "These committed artifacts record a read of the locked holdout and the index header "
        f"does not name them: {unnamed!r}. The header states how many reads there have been, "
        "so it has to name every artifact that says it made one."
    )


# --- a row must not quote a pool its protocol forbids without saying so -------

PROJECTION_AUDIT = DOCS / "live_projection_audit.json"
PROJECTION_AUDIT_PREREG = DOCS / "live_projection_audit_prereg.md"
NEVER_MIXED = "never mixed with a live one"
# The pooling rules the reader below knows, copied here rather than imported from the runner:
# if the runner changes its rule, the record states the new one and these copies have to stop
# the check, which an import would change along with the runner and never do.
#
# The rule the committed record was written under: it pooled whichever handoff the ledger named,
# and so stacked GW4's control replay beside GW5's live handoff.
LEDGER_POOLING_RULE = (
    "the handoff the ledger's decision names for that gameweek; where the ledger names "
    "none of the kept handoffs, the last one by file name"
)
# The repaired rule (#1122 question 2 (a)): the handoff the week's published advice read, each
# handoff labelled, a replay never pooled.
PUBLISHED_POOLING_RULE = (
    "the handoff written before the deadline that the week's published advice read: the one "
    "the retained advice records of the last publish before the deadline name, with their "
    "capture (docs/defcon_component_prereg.md section 4); a week whose retained advice names "
    "no such handoff is not pooled, and a handoff written after the deadline is labelled "
    "replay and never pooled"
)


def _row_of(stem: str) -> str:
    rows = [
        line
        for line in INDEX.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{stem}`")
    ]
    assert len(rows) == 1, f"expected one index row for `{stem}`, found {len(rows)}"
    return " ".join(rows[0].split())


def _replays_pooled_beside_a_live_week(record: dict[str, Any]) -> list[str]:
    """Fingerprints of the replay handoffs a projection audit's pool stacks beside another week.

    Each pooled gameweek enters with the handoff the runner's rule picks, which the record
    states as ``primary_projection_rule``. A pool of replays alone mixes nothing, so it returns
    no fingerprint. The reader knows two rules and stops on any other with a message saying the
    runner's rule changed.

    Under the ledger rule the record names no pooled handoff, so the reader re-derives the
    choice from ``in_ledger``: the one the ledger names, or the last kept one when the ledger
    names none. That is only right for a record that states this rule, because ``in_ledger`` is
    set from the ledger's own fingerprint whatever the runner pools.

    Under the published-advice rule each projection carries its ``label`` and exactly one per
    pooled gameweek is ``pooled``; the runner never pools one it labels ``replay``. A pooled
    handoff the ledger still holds as a replay is reported, so a record that pooled one is held
    to the row as well.
    """

    rule = record["pooled"].get("primary_projection_rule")
    assert rule in (LEDGER_POOLING_RULE, PUBLISHED_POOLING_RULE), (
        "The runner's pooling rule changed: docs/live_projection_audit.json now states "
        f"{rule!r}, and this reader knows only the ledger rule ({LEDGER_POOLING_RULE!r}) and the "
        f"published-advice rule ({PUBLISHED_POOLING_RULE!r}). Update this reader to the new rule "
        "before holding the index row to it."
    )
    chosen = []
    for gameweek in record["pooled"]["gameweeks"]:
        projections = record["gameweeks"][str(gameweek)]["projections"]
        if rule == PUBLISHED_POOLING_RULE:
            pooled = [
                projection for projection in projections if projection.get("label") == "pooled"
            ]
            assert len(pooled) == 1, (
                f"Gameweek {gameweek} is pooled, and {len(pooled)} of its handoffs are labelled "
                "`pooled`; the published-advice rule pools exactly one."
            )
            chosen.append(pooled[0])
            continue
        held = [projection for projection in projections if projection.get("in_ledger")]
        chosen.append(held[0] if held else projections[-1])
    replays = [
        str(projection["handoff_fingerprint"])
        for projection in chosen
        if projection.get("ledger_mode") == "replay"
    ]
    return replays if len(replays) < len(chosen) else []


def test_the_projection_audit_row_says_when_its_pool_mixes_a_replay_with_a_live_week() -> None:
    """The protocol says a replay "is never mixed with a live one"; the runner pools whichever
    handoff the ledger names, and for GW4 that is a control replay written after the deadline.

    Numbers from such a pool are not the protocol's pooled reading, and the record's own pooled
    table does not say a replay is in it. So the index row that quotes them has to name the
    replay handoff and the clause the pool breaks.

    The runner was repaired to pool the handoff the week's published advice read, and the
    reader knows that rule too. The committed record still states the ledger rule until it is
    regenerated from the weekly run's stores, so the row still names the replay; once the record
    states the repaired rule and its pool holds no replay, this check has nothing to hold the row
    to. A runner that changes its rule again states a new ``primary_projection_rule``, and the
    reader stops on it until it is taught that rule as well.
    """

    prereg = " ".join(PROJECTION_AUDIT_PREREG.read_text(encoding="utf-8").split())
    assert NEVER_MIXED in prereg, "The clause this check holds the row to has left the protocol."

    record = json.loads(PROJECTION_AUDIT.read_text(encoding="utf-8"))
    replays = _replays_pooled_beside_a_live_week(record)
    row = _row_of("live_projection_audit")
    unnamed = [fingerprint[:8] for fingerprint in replays if fingerprint[:8] not in row]

    assert not unnamed, (
        "docs/live_projection_audit.json pools these replay handoffs beside a live week and the "
        f"index row does not name them: {unnamed!r}. Name each one where the row quotes the pool."
    )
    assert not replays or NEVER_MIXED in row, (
        "The committed pool mixes a replay with a live week, which the protocol forbids "
        f'("{NEVER_MIXED}"). The row has to quote that clause and say the pooled numbers are '
        "not the protocol's pooled reading."
    )


def test_the_mix_check_tells_a_mixed_pool_from_a_clean_one() -> None:
    """A guard that cannot fail guards nothing, so prove it separates the cases."""

    replay = {"handoff_fingerprint": "e7abac4d", "in_ledger": True, "ledger_mode": "replay"}
    elite = {"handoff_fingerprint": "48f9e1ea", "in_ledger": False, "ledger_mode": None}
    live = {"handoff_fingerprint": "a8984200", "in_ledger": True, "ledger_mode": "live"}

    def record(
        week_four: list[dict[str, Any]], week_five: list[dict[str, Any]], rule: str
    ) -> dict[str, Any]:
        weeks = {"4": {"projections": week_four}, "5": {"projections": week_five}}
        return {
            "gameweeks": weeks,
            "pooled": {"gameweeks": [4, 5], "primary_projection_rule": rule},
        }

    ledger = LEDGER_POOLING_RULE
    assert _replays_pooled_beside_a_live_week(record([replay, elite], [live], ledger)) == [
        "e7abac4d"
    ]
    assert _replays_pooled_beside_a_live_week(record([elite, replay], [live], ledger)) == [
        "e7abac4d"
    ]
    assert _replays_pooled_beside_a_live_week(record([elite], [live], ledger)) == []
    assert _replays_pooled_beside_a_live_week(record([replay], [replay], ledger)) == []

    # Under the published-advice rule the label says which handoff is pooled, whatever the
    # ledger names: GW4's elite handoff pooled beside the labelled replay mixes nothing.
    published = PUBLISHED_POOLING_RULE
    labelled_replay = {**replay, "label": "replay"}
    pooled_elite = {**elite, "label": "pooled"}
    pooled_live = {**live, "label": "pooled"}
    assert (
        _replays_pooled_beside_a_live_week(
            record([labelled_replay, pooled_elite], [pooled_live], published)
        )
        == []
    )
    pooled_replay = {**replay, "label": "pooled"}
    assert _replays_pooled_beside_a_live_week(
        record([pooled_replay, {**elite, "label": "beside"}], [pooled_live], published)
    ) == ["e7abac4d"]
    with pytest.raises(AssertionError, match="exactly one"):
        _replays_pooled_beside_a_live_week(
            record([labelled_replay, {**elite, "label": "beside"}], [pooled_live], published)
        )


def test_the_mix_check_stops_when_the_runner_pools_by_another_rule() -> None:
    """The repaired runner pools 48f9e1ea for GW4 while the ledger still names the replay, so
    it still writes ``in_ledger`` on e7abac4d. Read under the ledger rule, that record would
    report a replay the pool no longer holds, which is why the reader reads each record by the
    rule it states. A rule it does not know has to stop it, not pass or fail on a pool it has
    misread; a record that states no rule stops too.
    """

    replay = {"handoff_fingerprint": "e7abac4d", "in_ledger": True, "ledger_mode": "replay"}
    elite = {"handoff_fingerprint": "48f9e1ea", "in_ledger": False, "ledger_mode": None}
    live = {"handoff_fingerprint": "a8984200", "in_ledger": True, "ledger_mode": "live"}
    weeks = {"4": {"projections": [replay, elite]}, "5": {"projections": [live]}}
    repaired = "the last handoff kept from before the deadline, never a replay"

    for pooled in (
        {"gameweeks": [4, 5], "primary_projection_rule": repaired},
        {"gameweeks": [4, 5]},
    ):
        with pytest.raises(AssertionError, match="pooling rule changed"):
            _replays_pooled_beside_a_live_week({"gameweeks": weeks, "pooled": pooled})
