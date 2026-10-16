"""Application dispatch checks with a frozen method stub, not a model-math oracle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_minute_integration import world

from squadopt.application import football_composite_news as module
from squadopt.application.football_context import FULL_MATCH_UNAVAILABLE
from squadopt.application.manager_words import ManagerWord
from squadopt.data.errors import DataError
from squadopt.live.football_artifact import FootballForecast
from squadopt.prediction.football_capabilities import COMPOSITE_MODEL_VERSION
from squadopt.prediction.football_joint_week_law import VerifiedWeekEvidence
from squadopt.prediction.participation_updates import ParticipationEvidence


@dataclass(frozen=True, slots=True)
class FrozenBasisStub:
    """Only mimic the application-facing method boundary on pristine stored frames."""

    served: dict[str, Any]
    companion: dict[str, Any]
    original_weekly: pd.DataFrame
    original_fixtures: pd.DataFrame
    unsupported_minutes: bool = False
    support_error: type[Exception] = ValueError
    absence_failure: bool = False
    population_fault: str | None = None
    future_tamper: bool = False
    calls: list[tuple[VerifiedWeekEvidence, ...]] = field(default_factory=list)

    @property
    def fixture_rows(self) -> pd.DataFrame:
        return self.original_fixtures.copy(deep=True)

    def validate_evidence(self, evidence: tuple[VerifiedWeekEvidence, ...]) -> None:
        if self.unsupported_minutes and any(e.kind == "no_full_match" for e in evidence):
            raise self.support_error("Synthetic unsupported within-role minute support.")
        if self.absence_failure and any(e.kind == "absence" for e in evidence):
            raise ValueError("Synthetic unavailable absence recomposition.")

    def recompose(self, evidence: tuple[VerifiedWeekEvidence, ...] = ()) -> SimpleNamespace:
        self.validate_evidence(evidence)
        self.calls.append(evidence)
        weekly = self.original_weekly.copy(deep=True)
        fixtures = self.original_fixtures.copy(deep=True)
        for item in evidence:
            selected = weekly.player_id.eq(item.player_code) & weekly.gameweek.eq(item.gameweek)
            if item.kind == "absence":
                weekly.loc[selected, ["appearance_probability", "expected_points"]] = 0.0
            else:
                weekly.loc[selected, "expected_points"] -= 0.5
            # A deliberate marker on both clubs proves that forwarding does not
            # reduce the richer recomposition to the named player's rows.
            affected = fixtures.fixture.isin(item.fixture_ids)
            fixtures.loc[affected, "expected_points"] += 0.125
        if self.future_tamper:
            future = weekly.gameweek.gt(int(self.served["gameweek"]))
            weekly.loc[future, "expected_points"] += 1.0
        if self.population_fault == "extra":
            extra = weekly.iloc[[0]].copy()
            extra["player_id"] = 999999
            weekly = pd.concat([weekly, extra], ignore_index=True)
        elif self.population_fault == "missing":
            weekly = weekly.iloc[1:].copy()
        elif self.population_fault == "repeated":
            weekly = pd.concat([weekly, weekly.iloc[[0]]], ignore_index=True)
        fingerprint = (
            hashlib.sha256(
                json.dumps([e.evidence_id for e in evidence], separators=(",", ":")).encode()
            ).hexdigest()
            if evidence
            else self.served["fingerprint"]
        )
        return SimpleNamespace(weekly_rows=weekly, fixture_rows=fixtures, fingerprint=fingerprint)


def case(monkeypatch: pytest.MonkeyPatch, **options: Any) -> tuple[Any, ...]:
    from squadopt.live import football_composite_basis as basis_module

    football, inputs, manager, basis = world()
    football = replace(
        football, horizon=replace(football.horizon, model_version=COMPOSITE_MODEL_VERSION)
    )
    stub = FrozenBasisStub(
        dict(basis.served, model_version=COMPOSITE_MODEL_VERSION),
        dict(basis.companion, model_version=COMPOSITE_MODEL_VERSION),
        football.horizon.table.copy(deep=True),
        basis.fixture_rows.copy(deep=True),
        **options,
    )
    monkeypatch.setattr(basis_module, "CompositeComponentBasis", FrozenBasisStub)
    forwarded: list[pd.DataFrame] = []

    def capture_roles(
        _basis: Any, _inputs: Any, *, revised_rows: pd.DataFrame, applied_fixtures: Any
    ) -> list[Any]:
        forwarded.append(revised_rows.copy(deep=True))
        return []

    monkeypatch.setattr(module, "fixture_role_estimates", capture_roles)
    return football, inputs, manager.words[0], stub, forwarded


def claims(
    word: ManagerWord, inputs: Any, selected: tuple[tuple[int, str], ...]
) -> tuple[list[ParticipationEvidence], dict[str, ManagerWord]]:
    news, words = [], {}
    deadline = pd.Timestamp(inputs.deadline.deadline_utc)
    for i, (player, disposition) in enumerate(selected):
        identity = f"source-{i}"
        source = replace(
            word,
            player_id=player,
            disposition=disposition,
            source_url=f"https://club.example/claim/{i}",
        )
        words[identity] = source
        news.append(
            ParticipationEvidence(
                identity,
                player,
                inputs.season,
                inputs.deadline.gameweek,
                deadline,
                pd.Timestamp(source.published_at_utc),
                pd.Timestamp(source.fetched_at_utc),
                deadline,
                str(source.source_url),
                "source_statement",
                source_url=source.source_url,
                disposition=disposition,
            )
        )
    return news, words


def run(
    football: FootballForecast,
    inputs: Any,
    word: ManagerWord,
    stub: FrozenBasisStub,
    selected: tuple[tuple[int, str], ...] = (),
) -> tuple[Any, ...]:
    news, words = claims(word, inputs, selected)
    return module.recompose_composite_news(football, inputs, news, words, stub)


@pytest.mark.parametrize("error", [ValueError, DataError])
def test_failed_optional_minute_keeps_unrelated_verified_absence(
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
) -> None:
    football, inputs, word, stub, _ = case(
        monkeypatch, unsupported_minutes=True, support_error=error
    )
    adjusted, decisions, withheld, metadata = run(
        football,
        inputs,
        word,
        stub,
        ((3, FULL_MATCH_UNAVAILABLE), (9, "stated_expected_absent")),
    )
    absent = adjusted.loc[adjusted.gameweek.eq(6) & adjusted.player_id.eq(9)]
    assert absent.appearance_probability.item() == absent.expected_points.item() == 0
    assert [r["player_id"] for r in decisions] == [9]
    assert [(r["player_id"], r["reason"]) for r in withheld] == [
        (3, "unsupported_composite_intervention")
    ]
    assert [[e.kind for e in call] for call in stub.calls] == [["absence"]]
    assert metadata["joint_recomposition"] is True


@pytest.mark.parametrize("include_minutes", [False, True])
def test_uncomposable_absence_refuses_instead_of_restoring_baseline(
    monkeypatch: pytest.MonkeyPatch, include_minutes: bool
) -> None:
    football, inputs, word, stub, _ = case(
        monkeypatch, unsupported_minutes=True, absence_failure=True
    )
    selected = ((9, "stated_expected_absent"),)
    if include_minutes:
        selected = ((3, FULL_MATCH_UNAVAILABLE), *selected)
    with pytest.raises(ValueError, match="absence recomposition"):
        run(football, inputs, word, stub, selected)
    assert not stub.calls


def test_first_week_only_and_both_clubs_forwarded_to_role_explanations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    football, inputs, word, stub, forwarded = case(monkeypatch)
    adjusted, _, _, _ = run(football, inputs, word, stub, ((3, FULL_MATCH_UNAVAILABLE),))
    future = football.horizon.table.gameweek.ne(inputs.deadline.gameweek)
    assert_frame_equal(adjusted.loc[future], football.horizon.table.loc[future], check_exact=True)
    assert len(forwarded) == 1
    fixture = stub.original_fixtures.loc[
        stub.original_fixtures.player_code.eq(3) & stub.original_fixtures.GW.eq(6), "fixture"
    ].item()
    before = stub.original_fixtures.loc[stub.original_fixtures.fixture.eq(fixture)]
    after = forwarded[0].loc[forwarded[0].fixture.eq(fixture)]
    assert before.club.nunique() == after.club.nunique() == 2
    assert list(before.player_code) == list(after.player_code)
    assert (after.expected_points.to_numpy() == before.expected_points.to_numpy() + 0.125).all()


def test_future_tampering_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    football, inputs, word, stub, _ = case(monkeypatch, future_tamper=True)
    with pytest.raises(ValueError, match="later composite weeks"):
        run(football, inputs, word, stub, ((3, FULL_MATCH_UNAVAILABLE),))


@pytest.mark.parametrize("fault", ["extra", "missing", "repeated"])
def test_exact_population_checked_before_reindex(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    football, inputs, word, stub, _ = case(monkeypatch, population_fault=fault)
    with pytest.raises(ValueError, match="projected population"):
        run(football, inputs, word, stub)


def test_no_news_is_exact_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    football, inputs, word, stub, _ = case(monkeypatch)
    adjusted, decisions, withheld, metadata = run(football, inputs, word, stub)
    assert_frame_equal(adjusted, football.horizon.table, check_exact=True)
    assert decisions == withheld == []
    assert metadata["intervention_fingerprint"] == football.fingerprint
    assert stub.calls == [()]


def test_repeated_calls_reuse_original_basis_without_compounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    football, inputs, word, stub, _ = case(monkeypatch)
    selected = ((3, FULL_MATCH_UNAVAILABLE),)
    first, _, _, first_metadata = run(football, inputs, word, stub, selected)
    changed = replace(football, horizon=replace(football.horizon, table=first))
    second, _, _, second_metadata = run(changed, inputs, word, stub, selected)
    assert_frame_equal(first, second, check_exact=True)
    assert first_metadata["intervention_fingerprint"] == second_metadata["intervention_fingerprint"]
    assert_frame_equal(stub.original_weekly, football.horizon.table, check_exact=True)
    reset, _, _, reset_metadata = run(changed, inputs, word, stub)
    assert_frame_equal(reset, football.horizon.table, check_exact=True)
    assert reset_metadata["intervention_fingerprint"] == football.fingerprint


def test_forecast_fingerprint_mismatch_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    football, inputs, word, stub, _ = case(monkeypatch)
    with pytest.raises(ValueError, match="requested forecast"):
        run(replace(football, fingerprint="0" * 64), inputs, word, stub)
    assert not stub.calls
