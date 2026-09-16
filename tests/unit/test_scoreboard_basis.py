"""One scoring basis per series.

The live weekly record is the only instrument that accumulates, and it is worth having
only if every row in it measures the same thing. Two rules for turning settled player
points into a score were in use here: the eleven a decision named, scored as named, and
the official scorer that applies automatic substitutions and the vice-captain fallback.
They are different measurements. The system's own gameweek 1 sits on the first, because
its decision froze neither a bench order nor a vice-captain and so nothing could complete
its eleven; every week from gameweek 2 on sits on the second.

A number does not carry its rule. So the rule is written down beside it, and these tests
attack the two ways that breaks: a record that states a score and no basis, and a total
that adds one basis to another. Both are refusals rather than conventions. A defaulted
basis is a claim nobody made, and a mixed total is a number that looks like a season score
and is not one, which is worse than publishing no total at all.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError
from tests.unit.test_build_scoreboard import SEASON, _entry, _payload, _rows
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard import (
    SERIES_SCORING_BASIS,
    _published_ours,
    single_basis,
)
from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.application.scoreboard_history import settled_scoreboard_entries
from squadopt.data.errors import DataError
from squadopt.evaluation.models import ScoringBasis, ScoringPolicy
from squadopt.live import LedgerEntry

LEGACY = str(ScoringBasis.NAMED_ELEVEN_NO_AUTOSUBS)


def test_the_two_vocabularies_name_the_official_scorer_identically() -> None:
    """The basis a record states and the policy the evaluator applies must not drift.

    They are separate enums on purpose: a basis describes a number already written down,
    a policy describes something the evaluator can run. Where they overlap they have to
    agree, or a record would claim a rule under a name no scorer answers to.
    """

    assert ScoringBasis.OFFICIAL_AUTOSUB_CAPTAIN_V2 == ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2
    assert SERIES_SCORING_BASIS == "official_autosub_captain_v2"
    # The legacy basis deliberately has no policy counterpart: nothing applies it.
    assert LEGACY not in {str(policy) for policy in ScoringPolicy}


# --- a record without a stated basis is refused, never defaulted -------------------------


def test_a_settled_row_without_a_stated_basis_is_refused_rather_than_defaulted() -> None:
    """The case that must never quietly pass: a real number, and nothing saying what made it.

    Before this, the publisher filled the gap with the legacy basis. That is a claim the
    record never made, and from gameweek 2 on it would have been the wrong one, since
    those decisions settle officially.
    """

    with pytest.raises(DataError, match="scoring_basis"):
        _payload(ledger_entries=(_entry(1, mode="live", settled=True, basis=None),))


def test_an_unsettled_row_states_no_basis_because_it_has_no_number() -> None:
    """A basis describes a score. No score, no basis.

    This row previously claimed the legacy basis while carrying ``net: null``, asserting
    a rule that had not run on a number that did not exist.
    """

    ours = _rows(_payload(ledger_entries=(_entry(2, mode="replay", settled=False),)))[2]["ours"]
    assert ours["net"] is None
    assert ours["xi"] is None
    assert ours["scoring_basis"] is None


def test_a_published_row_that_cannot_say_what_produced_its_number_is_not_carried(
    tmp_path: Path,
) -> None:
    """Inertia is not evidence.

    An empty ledger root lets already published rows stand. A row that states a score and
    no basis does not get to persist through republication just because it was published
    once; it is dropped, and the gameweek reads as having no row of ours at all.
    """

    target = tmp_path / "scoreboard.json"
    target.write_text(
        json.dumps(
            {
                "payload": {
                    "season": SEASON,
                    "gameweeks": [
                        {"gameweek": 1, "ours": {"net": 26.0, "scoring_basis": LEGACY}},
                        {"gameweek": 2, "ours": {"net": 31.0, "scoring_basis": None}},
                        {"gameweek": 3, "ours": {"net": 40.0}},
                        {"gameweek": 4, "ours": {"net": None, "scoring_basis": None}},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    kept = _published_ours(target, SEASON)

    # GW1 says what produced its number and stays. GW4 has no number to account for and
    # stays. GW2 and GW3 each publish a score with no basis, and are gone.
    assert sorted(kept) == [1, 4]


def test_an_uncoverable_entry_with_no_stated_basis_refuses_settlement(tmp_path: Path) -> None:
    """The layer boundary refuses too, not just the publisher.

    When no capture covers a week, its recorded outcome is carried through as it stands.
    That is the one path where a number reaches the scoreboard without a scorer having
    just run and stated the basis itself, so it is the path that has to demand one.
    """

    decision, _, _ = decision_inputs()
    entry = LedgerEntry(SEASON, 1, decision, {"realized_net_score": 42.0}, tmp_path)

    with pytest.raises(DataError, match="scoring_basis"):
        settled_scoreboard_entries((entry,), (), season=SEASON, as_of_utc="2026-08-24T12:00:00Z")


def test_an_uncoverable_entry_with_no_outcome_is_carried_through_untouched(
    tmp_path: Path,
) -> None:
    """Absent is not broken. A week with no outcome owes no basis and is not refused."""

    decision, _, _ = decision_inputs()
    entry = LedgerEntry(SEASON, 1, decision, None, tmp_path)

    assert settled_scoreboard_entries(
        (entry,), (), season=SEASON, as_of_utc="2026-08-24T12:00:00Z"
    ) == (entry,)


# --- two bases cannot enter one total ----------------------------------------------------


def test_two_bases_do_not_sum_into_one_season_total() -> None:
    """The heart of it: a legacy week and an official week are never added together.

    Both weeks stay published with their own numbers and their own bases. The total covers
    the official week alone and says so, and the legacy week is named as left out rather
    than silently dropped, so a reader can see the week exists and see why it is not in
    the running figure.
    """

    payload = _payload(
        ledger_entries=(
            _entry(1, mode="live", settled=True, net=26.0, basis=LEGACY),
            _entry(2, mode="live", settled=True, net=31.0, basis=SERIES_SCORING_BASIS),
        )
    )
    cumulative = payload["cumulative"]

    # The number this test exists to refuse, written out so the refusal is unmistakable.
    assert cumulative["ours_net"] != 26.0 + 31.0
    assert cumulative["ours_net"] == 31.0
    assert cumulative["ours_basis"] == SERIES_SCORING_BASIS
    assert cumulative["ours_gameweeks"] == [2]
    assert cumulative["ours_excluded_gameweeks"] == [{"gameweek": 1, "scoring_basis": LEGACY}]

    # Both weeks are still published, each stating what produced its own number.
    rows = _rows(payload)
    assert rows[1]["ours"]["net"] == 26.0
    assert rows[1]["ours"]["scoring_basis"] == LEGACY
    assert rows[2]["ours"]["net"] == 31.0
    assert rows[2]["ours"]["scoring_basis"] == SERIES_SCORING_BASIS


def test_the_legacy_week_alone_leaves_the_total_absent_rather_than_one_week_long() -> None:
    """The state of the real archive today, and the honest reading of it.

    Only gameweek 1 is recorded, and it is not on the series basis. So there is nothing to
    total. That reads as absent: not zero, and not a season total that is really one
    pre-contract week wearing the wrong label.
    """

    payload = _payload(
        ledger_entries=(_entry(1, mode="live", settled=True, net=26.0, basis=LEGACY),)
    )
    cumulative = payload["cumulative"]

    assert cumulative["ours_net"] is None
    assert cumulative["ours_basis"] is None
    assert cumulative["ours_gameweeks"] == []
    assert cumulative["ours_excluded_gameweeks"] == [{"gameweek": 1, "scoring_basis": LEGACY}]
    # The week itself is not hidden. It is published, and it is excluded.
    assert _rows(payload)[1]["ours"]["net"] == 26.0


def test_single_basis_refuses_two_names_one_and_reads_absence_as_absence() -> None:
    """The guard itself, directly.

    Any future caller that tries to combine rows across bases meets this rather than a
    silent sum, which is what makes the invariant structural instead of a convention held
    up by one call site.
    """

    official = {"net": 31.0, "scoring_basis": SERIES_SCORING_BASIS}
    legacy = {"net": 26.0, "scoring_basis": LEGACY}

    with pytest.raises(DataError, match="Two scoring bases"):
        single_basis([official, legacy])
    with pytest.raises(DataError, match="states no scoring basis"):
        single_basis([{"net": 26.0, "scoring_basis": None}])

    assert single_basis([official, dict(official)]) == SERIES_SCORING_BASIS
    assert single_basis([]) is None
    # Rows with no number are not measurements and do not constrain the basis.
    assert single_basis([{"net": None, "scoring_basis": None}]) is None


# --- the contract refuses it too, even if the producer is bypassed ------------------------


def _validator(pointer: str | None = None) -> Draft202012Validator:
    schema = json.loads(
        (
            Path(__file__).parents[2] / "docs/contracts/scoreboard_comparisons_v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    if pointer is None:
        return Draft202012Validator(schema)
    return Draft202012Validator({"$ref": pointer, "$defs": schema["$defs"]})


def test_the_contract_accepts_what_the_producer_actually_publishes() -> None:
    payload = _payload(
        ledger_entries=(
            _entry(1, mode="live", settled=True, net=26.0, basis=LEGACY),
            _entry(2, mode="live", settled=True, net=31.0, basis=SERIES_SCORING_BASIS),
        )
    )
    for week in payload["gameweeks"]:
        _validator().validate(week)
    _validator("#/$defs/cumulative").validate(payload["cumulative"])


@pytest.mark.parametrize("field", ["ours", "cumulative"])
def test_the_contract_refuses_a_score_whose_basis_is_null(field: str) -> None:
    """Hand-built, because the Python refusal is not the only thing that must hold.

    A document written by any other producer, or edited by hand, still has to fail.
    """

    payload = _payload(
        ledger_entries=(_entry(1, mode="live", settled=True, net=26.0, basis=LEGACY),)
    )
    if field == "ours":
        week = deepcopy(_rows(payload)[1])
        week["ours"]["scoring_basis"] = None
        with pytest.raises(ValidationError):
            _validator().validate(week)
    else:
        cumulative: dict[str, Any] = deepcopy(payload["cumulative"])
        cumulative["ours_net"] = 26.0
        cumulative["ours_gameweeks"] = [1]
        with pytest.raises(ValidationError):
            _validator("#/$defs/cumulative").validate(cumulative)


def test_the_contract_refuses_a_basis_on_a_row_that_has_no_number() -> None:
    week = deepcopy(_rows(_payload(ledger_entries=(_entry(2, mode="live", settled=False),)))[2])
    assert week["ours"]["scoring_basis"] is None
    week["ours"]["scoring_basis"] = LEGACY
    with pytest.raises(ValidationError):
        _validator().validate(week)


# --- the tripwire on the settlement path -------------------------------------------------


def test_a_decision_that_froze_no_completion_is_scored_as_named_and_nothing_is_invented() -> None:
    """Shaped like the system's real gameweek 1: no vice-captain, no ordered bench.

    This is the tripwire. The day the settlement path learns to manufacture a completion
    for such a decision, the basis here flips and the number moves, and this test names
    it. A completion invented after the fact is not the decision that was made, and a
    score built on one cannot join a series of scores that were not.
    """

    decision, projections, outcomes = decision_inputs()
    assert "vice_captain_player_id" not in decision
    assert "ordered_bench_player_ids" not in decision
    assert "completion_policy" not in decision

    scored = score_recorded_decision(decision, projections, outcomes)

    assert scored["scoring_basis"] == LEGACY
    assert scored["diagnostics"]["autosub_recovery"] is None


def test_the_same_decision_with_a_frozen_completion_settles_officially_and_differs() -> None:
    """The mirror, and the measured reason the two cannot be summed.

    Same squad, same settled points, same hits. The only difference is that this decision
    recorded what to do when a starter did not play. The two numbers differ, which is the
    whole argument: they are not two readings of one quantity.
    """

    decision, projections, outcomes = decision_inputs()
    named = score_recorded_decision(decision, projections, outcomes)

    completed = dict(decision)
    completed["ordered_bench_player_ids"] = [2, 6, 7, 12]
    completed["vice_captain_player_id"] = 9
    official = score_recorded_decision(completed, projections, outcomes)

    assert official["scoring_basis"] == SERIES_SCORING_BASIS
    assert official["net"] != named["net"]
    assert official["diagnostics"]["autosub_recovery"] is not None
