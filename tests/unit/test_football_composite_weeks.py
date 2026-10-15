"""Analytical whole-population composition and source alignment checks."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest

from squadopt.data.errors import DataError
from squadopt.features.football_load_inputs import LoadFixture, native_joint_law_digest
from squadopt.features.football_observed_load import (
    COVERAGE_KIND,
    FEATURE_NAMES,
    FEATURE_VERSION,
    MINUTE_DEFINITION,
    ObservedLoadCapturedNativeBasis,
    ObservedLoadProvenance,
    ObservedLoadWeek,
)
from squadopt.prediction.football_composite_weeks import (
    CompositeCalendarFixture,
    CompositeDeadline,
    CompositePlayer,
    CompositeWeekInput,
    CompositeWeekInventory,
    compose_composite_weeks,
    composite_native_sources,
)
from squadopt.prediction.football_joint_week_law import (
    VerifiedWeekEvidence,
    apply_shared_eligibility,
    joint_week_law_digest,
    joint_week_marginals,
    make_joint_week_law,
    model_week_law,
)
from squadopt.prediction.football_observed_load import (
    CONTEXT_NAMES,
    DESIGN_NAMES,
    MODEL_VERSION,
    ObservedLoadServingModel,
    ObservedLoadServingParameters,
    ObservedLoadTransform,
    read_observed_load_serving_result,
)

HEAD_SCORE = (0.15, 0.2, -0.15, -0.4, 0.1, -0.1, -0.3)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def serving(*, zero: bool = False) -> ObservedLoadServingModel:
    coefficients = tuple(
        0.0 if zero or index else score
        for score in HEAD_SCORE
        for index in range(len(CONTEXT_NAMES))
    )
    parameters = ObservedLoadServingParameters(
        "f" * 64,
        MODEL_VERSION,
        FEATURE_VERSION,
        COVERAGE_KIND,
        MINUTE_DEFINITION,
        FEATURE_NAMES,
        DESIGN_NAMES,
        "2026-10-14T00:00:00Z",
        "2026-27",
        (7, 8, 9),
        False,
        ObservedLoadTransform((0.0,) * 24, (1.0,) * 24, (1,) * 24),
        coefficients,
        (("EFL Cup",),),
        "normalize_once_after_1e-12_validation_preserve_structural_zeros",
        "not_applied",
    )
    raw = json.dumps(asdict(parameters), sort_keys=True, separators=(",", ":")).encode()
    return read_observed_load_serving_result(raw, sha256=hashlib.sha256(raw).hexdigest())


def population() -> tuple[CompositeWeekInventory, tuple[CompositeWeekInput, ...]]:
    calendar = (
        CompositeCalendarFixture(7, 100, "2026-10-17T15:00:00Z", 10, 20),
        CompositeCalendarFixture(8, 101, "2026-10-24T15:00:00Z", 10, 20),
        CompositeCalendarFixture(8, 102, "2026-10-27T15:00:00Z", 21, 10),
    )
    inventory = CompositeWeekInventory(
        "2026-27",
        (7, 8, 9),
        (CompositePlayer(42, "MID", 10, 0.6), CompositePlayer(43, "GK", 99, 1.0)),
        calendar,
        tuple(
            CompositeDeadline(gw, f"2026-10-{day}T10:00:00Z")
            for gw, day in ((7, 17), (8, 24), (9, 31))
        ),
        "fpl-live-20261015T130000Z-333333333333",
        "3" * 64,
        "2026-10-15T13:00:00Z",
        "2026-10-16T12:00:00Z",
        "4" * 64,
        "2" * 64,
        "1" * 64,
        "5" * 64,
        "6" * 64,
        "7" * 64,
    )
    rows = []
    single = (0.2, 0.1, 0.1, 0.2, 0.1, 0.1, 0.2)
    for gw in inventory.gameweeks:
        for person in inventory.roster:
            events = tuple(
                f
                for f in calendar
                if f.gameweek == gw and person.club_code in (f.home_club_code, f.away_club_code)
            )
            states = tuple(itertools.product(range(7), repeat=len(events)))
            probabilities = tuple(
                0.9 * math.prod(single[k] for k in state) + (0.1 if not any(state) else 0.0)
                for state in states
            )
            fixtures = tuple(
                LoadFixture(
                    f.fixture_id,
                    f.kickoff,
                    person.club_code,
                    f.away_club_code if person.club_code == f.home_club_code else f.home_club_code,
                    int(person.club_code == f.home_club_code),
                    tuple(
                        math.fsum(
                            p for s, p in zip(states, probabilities, strict=True) if s[j] == k
                        )
                        for k in range(7)
                    ),
                    (0, 25, 70, 90, 15, 65, 90),
                )
                for j, f in enumerate(events)
            )
            native = ObservedLoadCapturedNativeBasis(
                fixtures,
                states,
                probabilities,
                native_joint_law_digest(fixtures, states, probabilities),
                inventory.native_basis_sha256,
                "native_fixture_v1",
                inventory.captured_at,
                "2026-10-14T23:00:00Z",
                inventory.source_snapshot_id,
                inventory.source_fingerprint,
                inventory.captured_at,
                "2026-10-16T09:00:00Z",
                "2026-10-16T09:01:00Z",
                True,
                inventory.gameweeks,
                inventory.calendar_sha256,
                "original native source receipt",
            )
            provenance = ObservedLoadProvenance(
                "prospective",
                "a" * 40,
                "2026-10-15T12:00:00Z",
                "2026-10-16T09:00:00Z",
                "2026-10-16T10:00:00Z",
                "2026-10-16T11:00:00Z",
                composite_native_sources(inventory),
                "e" * 64,
                True,
                "test source receipt",
            )
            week = ObservedLoadWeek(
                inventory.season,
                gw,
                person.player_code,
                person.position,
                inventory.decision_at,
                next(d.deadline_at for d in inventory.deadlines if d.gameweek == gw),
                ("EFL Cup",),
                (),
                native,
                provenance,
            )
            law = make_joint_week_law(
                season=week.season,
                gameweek=gw,
                player_code=person.player_code,
                position=person.position,
                fixtures=fixtures,
                states=states,
                probabilities=probabilities,
                role_metadata_sha256=inventory.role_metadata_sha256,
                sources=composite_native_sources(inventory),
            )
            flag = None
            if gw == 7:
                values = tuple(
                    p * math.exp(0.4 * any(s))
                    for s, p in zip(law.states, law.probabilities, strict=True)
                )
                flag = model_week_law(
                    law,
                    states,
                    tuple(p / math.fsum(values) for p in values),
                    kind="flag",
                    sources=(("retained_flag_result", inventory.first_week_flag_result_sha256),),
                )
            rows.append(
                CompositeWeekInput(
                    law,
                    flag,
                    week,
                    person.captured_eligibility,
                    inventory.captured_eligibility_sha256,
                )
            )
    return inventory, tuple(rows)


def test_exact_sgw_dgw_bgw_likelihood_and_first_week_no_double_eligibility() -> None:
    inventory, rows = population()
    model = serving()
    result = compose_composite_weeks(rows, model, inventory=inventory, first_gameweek=7)
    assert len(result.laws) == len(result.receipts) == 6
    for row, final, receipt in zip(rows, result.laws, result.receipts, strict=True):
        if row.first_week_flag:
            offset = row.first_week_flag.probabilities
        else:
            offset = tuple(
                row.captured_eligibility * p + (1 - row.captured_eligibility if not any(s) else 0)
                for s, p in zip(row.native.states, row.native.probabilities, strict=True)
            )
        values = tuple(
            p
            * math.exp(
                HEAD_SCORE[0] * any(s) + sum(HEAD_SCORE[k] * s.count(k) for k in range(1, 7))
            )
            for s, p in zip(row.native.states, offset, strict=True)
        )
        expected = tuple(p / math.fsum(values) for p in values)
        assert final.probabilities == pytest.approx(expected, abs=3e-16)
        assert receipt.final_sha256 == joint_week_law_digest(final)
        assert receipt.input_sha256 == digest(asdict(row))
        marginal = joint_week_marginals(final)
        assert marginal.weekly_appearance == pytest.approx(
            sum(p for s, p in zip(final.states, expected, strict=True) if any(s))
        )
        if not row.native.fixtures:
            assert final.states == ((),) and final.probabilities == (1.0,)
    first = result.laws[0]
    assert all(s.policy != "shared_eligibility_mixture_v1" for s in first.lineage)
    assert result.model_sha256 == model.model_sha256
    assert result.serving_result_sha256 == model.result_sha256 != model.model_sha256
    assert result.inventory_sha256 == digest(asdict(inventory))
    with pytest.raises(FrozenInstanceError):
        result.model_sha256 = "bad"  # type: ignore[misc]


def test_zero_coefficients_and_news_last_preserve_appearance() -> None:
    inventory, rows = population()
    evidence = (VerifiedWeekEvidence("no-full", 42, 7, (100,), "no_full_match", "a" * 64),)
    baseline = compose_composite_weeks(
        rows, serving(zero=True), inventory=inventory, first_gameweek=7
    )
    result = compose_composite_weeks(
        rows, serving(zero=True), inventory=inventory, first_gameweek=7, evidence=evidence
    )
    assert baseline.laws[0].probabilities == rows[0].first_week_flag.probabilities
    before, after = baseline.laws[0].probabilities, result.laws[0].probabilities
    assert after[0] == before[0]
    assert after[3] == after[6] == 0
    assert sum(after[1:4]) == pytest.approx(sum(before[1:4]))
    assert sum(after[4:7]) == pytest.approx(sum(before[4:7]))
    assert after[1] / after[2] == pytest.approx(before[1] / before[2])
    assert result.laws[0].lineage[-1].policy == "same_role_conditional_no_full_match_v1"
    assert result.laws[1:] == baseline.laws[1:]
    absent = compose_composite_weeks(
        rows,
        serving(),
        inventory=inventory,
        first_gameweek=7,
        evidence=(replace(evidence[0], kind="absence"),),
    )
    assert absent.laws[0].probabilities == (1.0, 0, 0, 0, 0, 0, 0)
    assert absent.laws[2:] != baseline.laws[2:]


@pytest.mark.parametrize(
    "variant", ["missing", "duplicate", "unordered", "blank_missing", "unknown_player"]
)
def test_complete_population_inventory_refuses(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, rows = population()
    bad = {
        "missing": rows[:-1],
        "duplicate": (*rows[:-1], rows[0]),
        "unordered": tuple(reversed(rows)),
        "blank_missing": tuple(r for r in rows if r.native.fixtures),
        "unknown_player": (
            *rows[:-1],
            replace(rows[-1], load_week=replace(rows[-1].load_week, player_code=999)),
        ),
    }[variant]
    monkeypatch.setattr(
        ObservedLoadServingModel,
        "predict",
        lambda *_: pytest.fail("prediction before inventory validation"),
    )
    with pytest.raises(ValueError, match="inventory"):
        compose_composite_weeks(bad, serving(), inventory=inventory, first_gameweek=7)


@pytest.mark.parametrize(
    "variant",
    [
        "basis",
        "capture",
        "role",
        "calendar",
        "eligibility",
        "flag_source",
        "flag_missing",
        "flag_later",
        "twice",
        "future_fit",
    ],
)
def test_source_guards_precede_any_prediction(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, source = population()
    rows = list(source)
    index = 4
    row = rows[index]
    if variant == "basis":
        rows[index] = replace(
            row,
            load_week=replace(
                row.load_week, native=replace(row.load_week.native, basis_sha256="f" * 64)
            ),
        )
    elif variant == "capture":
        inventory = replace(inventory, captured_at="2026-10-15T14:00:00Z")
    elif variant == "role":
        rows[index] = replace(row, native=replace(row.native, role_metadata_sha256="b" * 64))
    elif variant == "calendar":
        inventory = replace(inventory, calendar=inventory.calendar[:-1])
    elif variant == "eligibility":
        rows[index] = replace(row, captured_eligibility=True)
    elif variant == "flag_source":
        inventory = replace(inventory, first_week_flag_result_sha256="a" * 64)
    elif variant == "flag_missing":
        rows[0] = replace(rows[0], first_week_flag=None)
    elif variant == "flag_later":
        rows[index] = replace(row, first_week_flag=rows[0].first_week_flag)
    elif variant == "twice":
        rows[index] = replace(
            row, native=apply_shared_eligibility(row.native, 0.8, sources=(("eligible", "a" * 64),))
        )
    else:
        rows[index] = replace(
            row,
            load_week=replace(
                row.load_week,
                provenance=replace(row.load_week.provenance, feature_cutoff="2026-10-13T00:00:00Z"),
            ),
        )
    monkeypatch.setattr(
        ObservedLoadServingModel,
        "predict",
        lambda *_: pytest.fail("prediction before all source headers"),
    )
    with pytest.raises(ValueError):
        compose_composite_weeks(tuple(rows), serving(), inventory=inventory, first_gameweek=7)


@pytest.mark.parametrize(
    "kind", ["unknown", "overlap", "late", "boolean", "unknown_fixture", "duplicate"]
)
def test_evidence_is_validated_for_full_population_before_load(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, rows = population()
    item = VerifiedWeekEvidence("news", 42, 7, (100,), "absence", "a" * 64)
    evidence = {
        "unknown": (replace(item, player_code=999),),
        "overlap": (item, replace(item, evidence_id="second")),
        "late": (replace(item, gameweek=8),),
        "boolean": (replace(item, gameweek=True),),
        "unknown_fixture": (replace(item, fixture_ids=(999,)),),
        "duplicate": (item, item),
    }[kind]
    monkeypatch.setattr(
        ObservedLoadServingModel,
        "predict",
        lambda *_: pytest.fail("prediction before evidence validation"),
    )
    with pytest.raises(ValueError):
        compose_composite_weeks(
            rows, serving(), inventory=inventory, first_gameweek=7, evidence=evidence
        )


def test_one_week_subset_is_explicit_and_missing_first_week_not_silently_skipped() -> None:
    inventory, rows = population()
    subset = replace(
        inventory,
        gameweeks=(7,),
        calendar=inventory.calendar[:1],
        deadlines=inventory.deadlines[:1],
    )
    result = compose_composite_weeks(rows[:2], serving(), inventory=subset, first_gameweek=7)
    assert len(result.laws) == 2
    with pytest.raises(ValueError, match="first week"):
        compose_composite_weeks(rows, serving(), inventory=inventory, first_gameweek=8)


def test_native_law_is_passed_unchanged_to_load(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, rows = population()
    original = ObservedLoadServingModel.predict
    seen = []

    def inspect(self: ObservedLoadServingModel, week: ObservedLoadWeek) -> Any:
        seen.append(week)
        return original(self, week)

    monkeypatch.setattr(ObservedLoadServingModel, "predict", inspect)
    compose_composite_weeks(rows, serving(), inventory=inventory, first_gameweek=7)
    assert tuple(seen) == tuple(row.load_week for row in rows)
    assert tuple(asdict(row) for row in rows) == tuple(asdict(row) for row in population()[1])


@pytest.mark.parametrize(
    "variant",
    [
        "hash_bool",
        "deadline_bool",
        "deadline_gap",
        "fixture_bool",
        "calendar_order",
        "future_calendar",
        "empty_roster",
        "clock_offset",
        "duplicate_roster",
    ],
)
def test_strict_inventory_refuses(variant: str) -> None:
    inventory, rows = population()
    if variant == "hash_bool":
        inventory = replace(inventory, native_basis_sha256=True)
    elif variant == "deadline_bool":
        inventory = replace(inventory, deadlines=(*inventory.deadlines, True))
    elif variant == "deadline_gap":
        inventory = replace(inventory, deadlines=inventory.deadlines[1:])
    elif variant == "fixture_bool":
        inventory = replace(
            inventory,
            calendar=(replace(inventory.calendar[0], fixture_id=True), *inventory.calendar[1:]),
        )
    elif variant == "calendar_order":
        inventory = replace(inventory, calendar=tuple(reversed(inventory.calendar)))
    elif variant == "future_calendar":
        inventory = replace(
            inventory,
            calendar=(
                *inventory.calendar,
                CompositeCalendarFixture(9, 900, "2027-10-31T15:00:00Z", 80, 90),
            ),
        )
    elif variant == "empty_roster":
        inventory = replace(inventory, roster=())
    elif variant == "clock_offset":
        inventory = replace(inventory, decision_at="2026-10-16T12:00:00")
    else:
        inventory = replace(inventory, roster=(inventory.roster[0], inventory.roster[0]))
    with pytest.raises((ValueError, DataError)):
        compose_composite_weeks(rows, serving(), inventory=inventory, first_gameweek=7)


def test_sparse_native_support_and_mismatched_flag_native_are_not_repaired() -> None:
    inventory, rows = population()
    row = rows[0]
    probabilities = (0.2, 0.3, 0.0, 0.5, 0.0, 0.0, 0.0)
    fixture = replace(row.load_week.native.fixtures[0], probabilities=probabilities)
    basis = replace(
        row.load_week.native,
        fixtures=(fixture,),
        probabilities=probabilities,
        law_sha256=native_joint_law_digest((fixture,), row.native.states, probabilities),
    )
    law = make_joint_week_law(
        season=row.native.season,
        gameweek=7,
        player_code=42,
        position="MID",
        fixtures=(fixture,),
        states=row.native.states,
        probabilities=probabilities,
        role_metadata_sha256=inventory.role_metadata_sha256,
        sources=composite_native_sources(inventory),
    )
    flag = model_week_law(
        law,
        law.states,
        probabilities,
        kind="flag",
        sources=(("retained_flag_result", inventory.first_week_flag_result_sha256),),
    )
    changed = replace(
        row, native=law, first_week_flag=flag, load_week=replace(row.load_week, native=basis)
    )
    result = compose_composite_weeks(
        (changed, *rows[1:]), serving(), inventory=inventory, first_gameweek=7
    )
    assert all(
        (p == 0) == (q == 0)
        for p, q in zip(probabilities, result.laws[0].probabilities, strict=True)
    )
    with pytest.raises(ValueError, match=r"support|source"):
        compose_composite_weeks(
            (replace(changed, first_week_flag=row.first_week_flag), *rows[1:]),
            serving(),
            inventory=inventory,
            first_gameweek=7,
        )
