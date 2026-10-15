"""Select source-verified interventions for the retained composite joint laws."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from squadopt.application.football_context import FULL_MATCH_UNAVAILABLE
from squadopt.application.football_roles import fixture_role_estimates
from squadopt.application.manager_words import ManagerWord
from squadopt.live import RecommendationInputs
from squadopt.live.football_artifact import FootballForecast
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.prediction.football_joint_week_law import VerifiedWeekEvidence
from squadopt.prediction.participation_updates import (
    ParticipationEvidence,
    apply_participation_updates,
)


@dataclass(frozen=True, slots=True)
class CompositeNewsSelection:
    evidence: tuple[VerifiedWeekEvidence, ...]
    decisions: tuple[dict[str, Any], ...]
    withheld: tuple[dict[str, Any], ...]


def recompose_composite_news(
    football: FootballForecast,
    inputs: RecommendationInputs,
    news: list[ParticipationEvidence],
    words: Mapping[str, ManagerWord],
    basis: FixtureComponentBasis | None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Reproject verified claims from the original complete composite basis once."""
    from squadopt.live.football_composite_basis import CompositeComponentBasis

    if not isinstance(basis, CompositeComponentBasis):
        raise ValueError("Composite football requires its verified reprojection basis.")
    if basis.served["fingerprint"] != football.fingerprint:
        raise ValueError("Composite basis differs from the requested forecast.")
    first = int(inputs.deadline.gameweek)
    selected = select_composite_news(
        football.horizon.table.loc[football.horizon.table.gameweek.eq(first)],
        news,
        words,
        basis.fixture_rows,
        season=inputs.season,
        first_gameweek=first,
        as_of=pd.Timestamp(inputs.captured_at_utc),
        deadline=pd.Timestamp(inputs.deadline.deadline_utc),
        base_revision=football.fingerprint,
    )
    decisions = list(selected.decisions)
    withheld = list(selected.withheld)
    accepted = selected.evidence
    try:
        basis.validate_evidence(accepted)
        result = basis.recompose(accepted)
    except ValueError:
        restricted_players = {item.player_code for item in accepted if item.kind == "no_full_match"}
        if not restricted_players:
            raise
        for decision in decisions:
            if decision["player_id"] not in restricted_players:
                continue
            for source in decision["evidence"]:
                withheld.append(
                    dict(
                        player_id=decision["player_id"],
                        disposition=source["disposition"],
                        evidence_id=source["evidence_id"],
                        reason="unsupported_composite_intervention",
                    )
                )
        decisions = [d for d in decisions if d["player_id"] not in restricted_players]
        accepted = tuple(item for item in accepted if item.kind == "absence")
        # Optional minute support cannot cancel a verified absence. If even the
        # absence-only fixture cannot be composed, this forecast is unavailable.
        basis.validate_evidence(accepted)
        result = basis.recompose(accepted)
    adjusted = football.horizon.table.copy(deep=True)
    keys = ["gameweek", "player_id"]
    original = adjusted.set_index(keys)
    revised = result.weekly_rows.set_index(keys)
    if (
        revised.index.has_duplicates
        or original.index.has_duplicates
        or not revised.index.sort_values().equals(original.index.sort_values())
    ):
        raise ValueError("Composite intervention changed the projected population.")
    revised = revised.reindex(original.index)
    for column in ("expected_points", "appearance_probability"):
        if revised[column].isna().any():
            raise ValueError("Composite intervention omitted a projected value.")
        future = original.index.get_level_values("gameweek") != first
        if not revised.loc[future, column].equals(original.loc[future, column]):
            raise ValueError("First-week evidence changed later composite weeks.")
        adjusted[column] = revised[column].to_numpy()
    metadata = {
        "available": True,
        "reason": None,
        "components_fingerprint": basis.companion["fingerprint"],
        "forecast_fingerprint": football.fingerprint,
        "intervention_fingerprint": result.fingerprint,
        "joint_recomposition": True,
        "role_estimates": fixture_role_estimates(
            basis,
            inputs,
            revised_rows=result.fixture_rows,
            applied_fixtures={
                (item.player_code, fixture) for item in accepted for fixture in item.fixture_ids
            },
        ),
    }
    return adjusted, decisions, withheld, metadata


def select_composite_news(
    base: pd.DataFrame,
    news: list[ParticipationEvidence],
    words: Mapping[str, ManagerWord],
    fixture_rows: pd.DataFrame,
    *,
    season: str,
    first_gameweek: int,
    as_of: pd.Timestamp,
    deadline: pd.Timestamp,
    base_revision: str,
) -> CompositeNewsSelection:
    """Reuse the source/time/conflict audit, discarding its scalar point updates.

    A current manager statement names one upcoming league fixture. Ambiguous double
    weeks remain refused here, although the lower-level joint-law API can represent
    explicitly scoped double-week evidence. Multiple independent absence sources
    identify one intervention whose digest binds all their verified source spans.
    """
    checked = apply_participation_updates(
        base,
        news,
        season=season,
        as_of=as_of,
        deadlines={first_gameweek: deadline},
        base_revision=base_revision,
    )
    checks = {row["player_id"]: row for row in checked.diagnostics}
    minute_counts = Counter(
        item.player_id for item in news if item.disposition == FULL_MATCH_UNAVAILABLE
    )
    selected: dict[int, list[tuple[ParticipationEvidence, dict[str, Any], int]]] = {}
    withheld: list[dict[str, Any]] = []

    def refuse(item: ParticipationEvidence, reason: str) -> None:
        withheld.append(
            dict(
                player_id=item.player_id,
                disposition=item.disposition,
                evidence_id=item.evidence_id,
                reason=reason,
            )
        )

    for item in news:
        check = checks.get(item.player_id, {})
        if check.get("reason") in ("conflicting_sources", "duplicate_evidence_or_source"):
            refuse(item, str(check["reason"]))
            continue
        provenance = check.get("evidence", [])
        records = provenance if isinstance(provenance, list) else []
        source: dict[str, Any] = next(
            (r for r in records if r["evidence_id"] == item.evidence_id), {}
        )
        absent = item.disposition == "stated_expected_absent"
        restricted = item.disposition == FULL_MATCH_UNAVAILABLE
        expected_reason = "eligible" if absent else "categorical_statement_has_no_probability"
        if not (absent or restricted) or source.get("reason") != expected_reason:
            refuse(item, str(source.get("reason", check.get("reason", "outside_projection"))))
            continue
        if restricted and any(
            r.get("disposition") == "stated_expected_absent" and r.get("reason") == "eligible"
            for r in records
        ):
            refuse(item, "explicit_absence_supersedes_minute_restriction")
            continue
        if restricted and minute_counts[item.player_id] != 1:
            refuse(item, "overlapping_minute_statements")
            continue
        scoped = fixture_rows.loc[
            fixture_rows.player_code.eq(item.player_id) & fixture_rows.GW.eq(first_gameweek)
        ]
        if len(scoped) != 1:
            refuse(item, "ambiguous_current_week_fixture")
            continue
        row = scoped.iloc[0]
        if pd.Timestamp(row.kickoff) <= as_of:
            refuse(item, "fixture_not_after_capture")
            continue
        if restricted and float(row.appearance_probability) <= 0:
            refuse(item, "zero_effective_appearance_basis")
            continue
        word = words.get(item.evidence_id)
        if (
            word is None
            or word.source_sha256 is None
            or word.span_start is None
            or word.span_end is None
        ):
            refuse(item, "verified_source_span_missing")
            continue
        selected.setdefault(item.player_id, []).append(
            (
                item,
                {
                    **source,
                    "source_sha256": word.source_sha256,
                    "span_start": word.span_start,
                    "span_end": word.span_end,
                },
                int(row.fixture),
            )
        )
    evidence: list[VerifiedWeekEvidence] = []
    decisions: list[dict[str, Any]] = []
    for player, rows in sorted(selected.items()):
        rows.sort(key=lambda value: value[0].evidence_id)
        sources = [row[1] for row in rows]
        source_digest = hashlib.sha256(
            json.dumps(sources, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        restricted = rows[0][0].disposition == FULL_MATCH_UNAVAILABLE
        evidence.append(
            VerifiedWeekEvidence(
                evidence_id=source_digest,
                player_code=player,
                gameweek=first_gameweek,
                fixture_ids=(rows[0][2],),
                kind="no_full_match" if restricted else "absence",
                source_sha256=source_digest,
            )
        )
        decisions.append(
            dict(
                player_id=player,
                gameweek=first_gameweek,
                status="applied",
                reason="explicit_full_match_restriction" if restricted else "explicit_evidence",
                evidence=sources,
                minutes_reestimated=True,
                starts_reestimated=not restricted,
                source_bundle_sha256=source_digest,
            )
        )
    return CompositeNewsSelection(tuple(evidence), tuple(decisions), tuple(withheld))
