"""Analytical checks of weekly dependence, supported transport and evidence."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import defaultdict
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from squadopt.data.errors import DataError
from squadopt.features.football_load_inputs import LoadFixture
from squadopt.prediction.football_joint_week_law import (
    JointWeekLaw,
    VerifiedWeekEvidence,
    apply_shared_eligibility,
    apply_verified_week_evidence,
    joint_week_law_digest,
    joint_week_law_document,
    joint_week_marginals,
    make_joint_week_law,
    model_week_law,
    read_joint_week_law_document,
    read_verified_week_evidence_document,
    transport_load,
    validate_joint_week_law,
    verified_week_evidence_document,
)

SOURCE = (("native_components", "a" * 64),)
MODEL_SOURCE = (("model", "b" * 64), ("input", "c" * 64), ("result", "d" * 64))
SPARSE = {
    (0, 0): 0.1,
    (1, 1): 0.1,
    (1, 3): 0.2,
    (3, 1): 0.1,
    (3, 3): 0.2,
    (4, 4): 0.1,
    (4, 6): 0.1,
    (6, 4): 0.1,
}


def native(count: int = 2, mass: dict[tuple[int, ...], float] | None = None) -> JointWeekLaw:
    states = tuple(itertools.product(range(7), repeat=count))
    if mass is None:
        mass = (
            SPARSE
            if count == 2
            else {(): 1.0}
            if count == 0
            else {(0,) * count: 0.2, (1,) * count: 0.3, (3,) * count: 0.5}
        )
    probabilities = tuple(mass.get(s, 0.0) for s in states)
    fixtures = tuple(
        LoadFixture(
            100 + j,
            f"2026-10-{18 + j}T12:00:00Z",
            10,
            20 + j,
            j % 2,
            tuple(
                math.fsum(p for s, p in zip(states, probabilities, strict=True) if s[j] == k)
                for k in range(7)
            ),
            (0, 25, 70, 90, 15, 65, 90),
        )
        for j in range(count)
    )
    return make_joint_week_law(
        season="2026-27",
        gameweek=7,
        player_code=42,
        position="MID",
        fixtures=fixtures,
        states=states,
        probabilities=probabilities,
        role_metadata_sha256="e" * 64,
        sources=SOURCE,
    )


def evidence(
    kind: str, fixtures: tuple[int, ...] = (100,), name: str = "claim"
) -> VerifiedWeekEvidence:
    return VerifiedWeekEvidence(name, 42, 7, fixtures, kind, "f" * 64)


def tilt(law: JointWeekLaw, scores: tuple[float, ...]) -> tuple[float, ...]:
    values = tuple(p * math.exp(s) for p, s in zip(law.probabilities, scores, strict=True))
    return tuple(p / math.fsum(values) for p in values)


def roles(law: JointWeekLaw) -> dict[tuple[int, ...], float]:
    result: dict[tuple[int, ...], float] = defaultdict(float)
    for state, probability in zip(law.states, law.probabilities, strict=True):
        result[tuple(0 if k == 0 else 1 if k < 4 else 2 for k in state)] += probability
    return dict(result)


def test_transport_matches_direct_additive_log_score_on_correlated_week() -> None:
    base = native()
    flag_score = tuple(0.4 * any(s) - 0.2 * s.count(4) for s in base.states)
    load_score = tuple(-0.7 * s.count(3) + 0.3 * s.count(1) for s in base.states)
    flag = model_week_law(
        base, base.states, tilt(base, flag_score), kind="flag", sources=MODEL_SOURCE
    )
    loaded = model_week_law(
        base, base.states, tilt(base, load_score), kind="load", sources=MODEL_SOURCE
    )
    final = transport_load(base, loaded, flag, sources=MODEL_SOURCE)
    direct = tilt(base, tuple(a + b for a, b in zip(flag_score, load_score, strict=True)))
    assert final.probabilities == pytest.approx(direct, abs=2e-16)
    assert all(
        (p == 0) == (q == 0) for p, q in zip(base.probabilities, final.probabilities, strict=True)
    )
    marginal = joint_week_marginals(final)
    assert marginal.weekly_appearance == pytest.approx(1 - direct[0])
    assert final.probabilities[7] == 0
    assert marginal.fixture_probabilities[0][1] * marginal.fixture_probabilities[1][0] > 0
    assert final.lineage[-1].parents == tuple(
        joint_week_law_digest(x) for x in (base, loaded, flag)
    )
    assert final.original_native_sha256 == base.original_native_sha256


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_zero_load_returns_offset_probabilities_exactly(count: int) -> None:
    base = native(count)
    offset = apply_shared_eligibility(base, 0.73, sources=SOURCE)
    loaded = model_week_law(
        base, base.states, base.probabilities, kind="load", sources=MODEL_SOURCE
    )
    final = transport_load(base, loaded, offset, sources=SOURCE)
    assert final.probabilities == offset.probabilities
    assert [f.minutes for f in final.fixtures] == [f.minutes for f in base.fixtures]
    assert final.role_metadata_sha256 == base.role_metadata_sha256
    if count == 0:
        assert joint_week_marginals(final).weekly_appearance == 0
        assert final.states == ((),) and final.probabilities == (1.0,)


def test_shared_eligibility_is_one_weekly_event_and_never_applied_after_flag() -> None:
    base = native()
    final = apply_shared_eligibility(base, 0.5, sources=SOURCE)
    assert final.probabilities[0] == pytest.approx(0.55)
    assert joint_week_marginals(final).weekly_appearance == pytest.approx(0.45)
    for index in range(1, len(base.states)):
        assert final.probabilities[index] == 0.5 * base.probabilities[index]
    assert final.probabilities[8] == pytest.approx(0.05)
    # Multiplying each fixture eligibility would instead give 0.025 at (1, 1).
    flag = model_week_law(base, base.states, base.probabilities, kind="flag", sources=MODEL_SOURCE)
    with pytest.raises(ValueError, match="unadjusted native"):
        apply_shared_eligibility(flag, 0.5, sources=SOURCE)
    assert apply_shared_eligibility(base, 1, sources=SOURCE).probabilities == base.probabilities
    assert apply_shared_eligibility(base, 0, sources=SOURCE).probabilities == (1.0, *([0.0] * 48))


def test_structural_eligibility_exception_is_recorded_but_cannot_invent_load_ratio() -> None:
    base = native(1, {(3,): 1.0})
    eligible = apply_shared_eligibility(base, 0.5, sources=SOURCE)
    assert eligible.lineage[-1].created_absent_indices == (0,)
    loaded = model_week_law(
        base, base.states, base.probabilities, kind="load", sources=MODEL_SOURCE
    )
    with pytest.raises(ValueError, match="extrapolate"):
        transport_load(base, loaded, eligible, sources=SOURCE)


def test_no_full_match_agrees_with_old_same_role_sgw_arithmetic() -> None:
    base = native(
        1, {(0,): 0.1, (1,): 0.15, (2,): 0.1, (3,): 0.35, (4,): 0.1, (5,): 0.05, (6,): 0.15}
    )
    result = apply_verified_week_evidence(base, (evidence("no_full_match"),), first_gameweek=7)
    expected = list(base.probabilities)
    for a, b, full in ((1, 2, 3), (4, 5, 6)):
        shorter = expected[a] + expected[b]
        multiplier = 1 + expected[full] / shorter
        expected[a] *= multiplier
        expected[b] *= multiplier
        expected[full] = 0
    assert result.probabilities == pytest.approx(expected, abs=2e-16)
    assert roles(result) == pytest.approx(roles(base))
    assert joint_week_marginals(result).weekly_appearance == pytest.approx(
        joint_week_marginals(base).weekly_appearance, abs=2e-16
    )
    assert result.fixtures[0].minutes == base.fixtures[0].minutes
    assert result.lineage[-1].created_absent_indices == ()


def test_correlated_no_full_match_preserves_role_pattern_and_other_joint_marginal() -> None:
    base = native()
    first = apply_verified_week_evidence(base, (evidence("no_full_match"),), first_gameweek=7)
    assert roles(first) == pytest.approx(roles(base))
    original = joint_week_marginals(base)
    changed = joint_week_marginals(first)
    assert changed.weekly_appearance == pytest.approx(original.weekly_appearance)
    assert changed.fixture_probabilities[1] == pytest.approx(original.fixture_probabilities[1])
    assert changed.start_probabilities == pytest.approx(original.start_probabilities)
    assert changed.cameo_probabilities == pytest.approx(original.cameo_probabilities)
    assert all(
        p > 0 or q == 0 for p, q in zip(base.probabilities, first.probabilities, strict=True)
    )
    both = apply_verified_week_evidence(
        base, (evidence("no_full_match", (101, 100)),), first_gameweek=7
    )
    positive = {s: p for s, p in zip(both.states, both.probabilities, strict=True) if p > 0}
    assert positive == pytest.approx({(0, 0): 0.1, (1, 1): 0.6, (4, 4): 0.3})
    assert [step.fixture_ids for step in both.lineage[1:]] == [(100,), (101,)]


def test_conditional_support_refusal_is_atomic_despite_marginal_shorter_support() -> None:
    base = native(2, {(1, 1): 0.4, (3, 3): 0.6})
    before = joint_week_law_document(base)
    assert base.fixtures[0].probabilities[1] > 0
    with pytest.raises(ValueError, match="conditional slice"):
        apply_verified_week_evidence(base, (evidence("no_full_match"),), first_gameweek=7)
    assert joint_week_law_document(base) == before
    role_missing = native(1, {(1,): 0.4, (6,): 0.6})
    with pytest.raises(ValueError, match="same-role"):
        apply_verified_week_evidence(role_missing, (evidence("no_full_match"),), first_gameweek=7)


def test_absence_is_scoped_pushforward_with_explicit_created_support() -> None:
    base = native()
    result = apply_verified_week_evidence(base, (evidence("absence"),), first_gameweek=7)
    expected: dict[tuple[int, ...], float] = defaultdict(float)
    for state, probability in zip(base.states, base.probabilities, strict=True):
        expected[0, state[1]] += probability
    assert result.probabilities == pytest.approx(tuple(expected.get(s, 0.0) for s in base.states))
    marginals = joint_week_marginals(result)
    assert marginals.fixture_probabilities[0] == (1.0, 0, 0, 0, 0, 0, 0)
    assert marginals.fixture_probabilities[1] == pytest.approx(
        joint_week_marginals(base).fixture_probabilities[1]
    )
    assert result.lineage[-1].created_absent_indices == (1, 3, 4, 6)
    whole = apply_verified_week_evidence(base, (evidence("absence", (100, 101)),), first_gameweek=7)
    assert whole.probabilities == (1.0, *([0.0] * 48))
    assert joint_week_marginals(whole).weekly_appearance == 0


def test_three_fixture_absence_preserves_full_other_fixture_joint_law() -> None:
    base = native(3, {(0, 0, 0): 0.2, (1, 1, 3): 0.1, (3, 1, 3): 0.3, (4, 4, 1): 0.4})
    result = apply_verified_week_evidence(base, (evidence("absence"),), first_gameweek=7)
    for a, b in itertools.product(range(7), repeat=2):
        old = math.fsum(
            p for s, p in zip(base.states, base.probabilities, strict=True) if s[1:] == (a, b)
        )
        new = math.fsum(
            p for s, p in zip(result.states, result.probabilities, strict=True) if s[1:] == (a, b)
        )
        assert old == new


@pytest.mark.parametrize("value", [True, -0.1, 1.1, math.nan, math.inf, "0.5"])
def test_bad_eligibility_refuses(value: Any) -> None:
    with pytest.raises(ValueError):
        apply_shared_eligibility(native(), value, sources=SOURCE)


@pytest.mark.parametrize(
    "change",
    [
        {"player_code": 43},
        {"gameweek": 8},
        {"fixture_ids": ()},
        {"fixture_ids": (999,)},
        {"fixture_ids": (100, 100)},
        {"fixture_ids": (True,)},
        {"kind": "maybe"},
        {"source_sha256": "fake"},
        {"evidence_id": ""},
    ],
)
def test_bad_verified_evidence_refuses(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        apply_verified_week_evidence(
            native(), (replace(evidence("absence"), **change),), first_gameweek=7
        )


def test_evidence_first_week_overlap_and_no_positive_appearance_guards() -> None:
    base = native()
    assert apply_verified_week_evidence(base, (), first_gameweek=7) is base
    with pytest.raises(ValueError, match="first"):
        apply_verified_week_evidence(base, (evidence("absence"),), first_gameweek=8)
    with pytest.raises(ValueError, match="overlapping"):
        apply_verified_week_evidence(
            base, (evidence("absence"), evidence("no_full_match", name="other")), first_gameweek=7
        )
    with pytest.raises(ValueError, match="positive effective"):
        apply_verified_week_evidence(
            native(1, {(0,): 1.0}), (evidence("no_full_match"),), first_gameweek=7
        )


@pytest.mark.parametrize(
    "field,value", [("player_code", 43), ("position", "DEF"), ("role_metadata_sha256", "9" * 64)]
)
def test_transport_rejects_different_context(field: str, value: Any) -> None:
    base = native()
    loaded = model_week_law(base, base.states, base.probabilities, kind="load", sources=SOURCE)
    offset = apply_shared_eligibility(base, 0.5, sources=SOURCE)
    with pytest.raises(ValueError, match="differ"):
        transport_load(base, loaded, replace(offset, **{field: value}), sources=SOURCE)


def test_transport_requires_exact_order_minutes_model_and_parent_lineage() -> None:
    base = native()
    loaded = model_week_law(base, base.states, base.probabilities, kind="load", sources=SOURCE)
    offset = apply_shared_eligibility(base, 0.5, sources=SOURCE)
    changed = replace(
        offset,
        fixtures=(
            replace(offset.fixtures[0], minutes=(0, 26, 70, 90, 15, 65, 90)),
            offset.fixtures[1],
        ),
    )
    with pytest.raises(ValueError, match="minutes"):
        transport_load(base, loaded, changed, sources=SOURCE)
    with pytest.raises((ValueError, DataError)):
        transport_load(
            base, loaded, replace(offset, fixtures=offset.fixtures[::-1]), sources=SOURCE
        )
    with pytest.raises(ValueError, match="exact original"):
        transport_load(base, offset, offset, sources=SOURCE)
    with pytest.raises(ValueError, match="exact original"):
        transport_load(
            base,
            replace(
                loaded,
                lineage=(*loaded.lineage[:-1], replace(loaded.lineage[-1], parents=("0" * 64,))),
            ),
            offset,
            sources=SOURCE,
        )


def test_model_binding_rejects_reordered_states_and_changed_structural_support() -> None:
    base = native()
    with pytest.raises(ValueError, match="canonical"):
        model_week_law(base, base.states[::-1], base.probabilities, kind="load", sources=SOURCE)
    boolean_states = tuple(tuple(True if k == 1 else k for k in s) for s in base.states)
    with pytest.raises(ValueError, match="canonical"):
        model_week_law(base, boolean_states, base.probabilities, kind="flag", sources=SOURCE)
    values = list(base.probabilities)
    values[0] -= 0.01
    values[1] += 0.01
    with pytest.raises(ValueError, match="support"):
        model_week_law(base, base.states, tuple(values), kind="flag", sources=SOURCE)


def test_transport_refuses_underflow_without_clipping_supported_atoms() -> None:
    base = native(1, {(0,): 0.5, (1,): 0.5})
    loaded = model_week_law(
        base, base.states, (1.0, 5e-324, 0, 0, 0, 0, 0), kind="load", sources=SOURCE
    )
    flag = model_week_law(
        base, base.states, (1.0, 5e-324, 0, 0, 0, 0, 0), kind="flag", sources=SOURCE
    )
    with pytest.raises(ValueError, match="lost positive"):
        transport_load(base, loaded, flag, sources=SOURCE)


def test_json_roundtrip_exact_digest_and_immutable_return() -> None:
    base = native()
    law = apply_verified_week_evidence(base, (evidence("absence"),), first_gameweek=7)
    document = joint_week_law_document(law)
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == joint_week_law_digest(law)
    assert read_joint_week_law_document(json.loads(encoded)) == law
    claim = evidence("absence", (100, 101))
    assert read_verified_week_evidence_document(verified_week_evidence_document(claim)) == claim
    document["probabilities"][0] = 999
    assert law.probabilities[0] != 999
    with pytest.raises(FrozenInstanceError):
        law.gameweek = 8  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("gameweek", True),
        ("probabilities", [True] * 49),
        ("states", [[0, 0]]),
        ("role_version", "changed"),
        ("lineage", []),
        ("fixtures", []),
        ("version", "future"),
    ],
)
def test_document_reader_rejects_malformed_inventory(field: str, value: Any) -> None:
    document = joint_week_law_document(native())
    document[field] = value
    with pytest.raises((ValueError, DataError)):
        read_joint_week_law_document(document)


def test_document_reader_rejects_nested_extra_fields_and_unjustified_support_receipts() -> None:
    for location in ((), ("fixtures", 0), ("lineage", 0)):
        document = joint_week_law_document(native())
        target = document
        for key in location:
            target = target[key]
        target["unknown"] = "value"
        with pytest.raises(ValueError, match="inventory"):
            read_joint_week_law_document(document)
    document = joint_week_law_document(native())
    document["lineage"][0]["created_absent_indices"] = [0]
    with pytest.raises(ValueError, match="structural absence"):
        read_joint_week_law_document(document)
    bad = verified_week_evidence_document(evidence("absence"))
    bad["fixture_ids"] = [True]
    with pytest.raises(ValueError):
        read_verified_week_evidence_document(bad)
    validate_joint_week_law(native())
