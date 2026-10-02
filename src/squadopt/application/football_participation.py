"""Bind already captured participation evidence to the experimental football window."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace

import pandas as pd

from squadopt.application.football_context import (
    FULL_MATCH_UNAVAILABLE,
    manager_word_attestation_reason,
)
from squadopt.application.football_roles import bind_role_absences, fixture_role_estimates
from squadopt.application.manager_words import (
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    WORDS_UNRESOLVED,
    ManagerWord,
    ManagerWords,
)
from squadopt.live import RecommendationInputs
from squadopt.live.football_artifact import FootballForecast
from squadopt.live.minute_evidence import (
    ExplicitMinuteEvidence,
    FixtureComponentBasis,
    apply_explicit_minute_evidence,
)
from squadopt.prediction.participation_updates import (
    PARTICIPATION_UPDATE_CONTRACT,
    ParticipationEvidence,
    apply_participation_updates,
)

FOOTBALL_PARTICIPATION_VERSION = "football_participation_evidence_v3"
PUBLIC_PARTICIPATION_VERSION = "football_participation_evidence_v1"
INHERITED_ZERO_LIMIT = (
    "Earlier football forecasts may already carry an absence into later weeks. "
    "This update does not restore those values without a known conditional forecast."
)


def participation_summary(diagnostics: Mapping[str, object]) -> dict[str, object] | None:
    """Publish counts and stated limits; detailed evidence stays in internal diagnostics."""
    audit = diagnostics.get("participation_evidence")
    if not isinstance(audit, dict):
        return None
    captured = audit.get("captured_percentages", [])
    statements = audit.get("manager_statements", [])
    withheld = audit.get("unapplied_statements", [])
    if not all(isinstance(rows, list) for rows in (captured, statements, withheld)):
        return None

    def evidence_count(row: dict[str, object]) -> int:
        items = row.get("evidence")
        return len(items) if isinstance(items, list) else 1

    captured_count = sum(evidence_count(row) for row in captured if isinstance(row, dict))
    statement_count = len(withheld) + sum(
        evidence_count(row) for row in statements if isinstance(row, dict)
    )
    unsupported = audit.get("reason") == "unsupported_contract"
    if not captured_count and not statement_count and not unsupported:
        return None
    assumptions = (
        [
            "explicit_full_match_restriction",
            "no_start_reestimate",
            "appearance_unchanged_by_minute_evidence",
            "club_attack_shares_reallocated",
            "declared_minute_intervention_not_calibration",
        ]
        if audit.get("minutes_reestimated")
        else ["source_eligibility_only", "no_start_or_minutes_reestimate"]
    )
    assumptions.append("no_external_calibration")
    if audit.get("minute_statements_unapplied"):
        assumptions.append("minute_evidence_not_applied")
    if audit.get("inherited_future_zero"):
        assumptions.append("future_values_not_recovered")
    if unsupported:
        assumptions.append("unsupported_appearance_contract")
    outcomes = audit.get("statement_outcomes")
    public_outcomes = outcomes if isinstance(outcomes, list) else None
    if public_outcomes is not None:
        statement_count = len(public_outcomes)
    summary: dict[str, object] = {
        "version": PUBLIC_PARTICIPATION_VERSION,
        "as_of": audit.get("as_of"),
        "gameweek": audit.get("gameweek"),
        "applied_player_count": len(
            {
                row.get("player_id")
                for row in statements
                if isinstance(row, dict) and row.get("status") == "applied"
            }
        ),
        "unapplied_statement_count": len(withheld)
        + sum(
            evidence_count(row)
            for row in statements
            if isinstance(row, dict) and row.get("status") != "applied"
        ),
        "captured_percentage_count": captured_count,
        "manager_statement_count": statement_count,
        "assumptions": assumptions,
    }
    if public_outcomes is not None:
        summary["statement_outcomes"] = public_outcomes
        summary["applied_player_count"] = len(
            {
                row["player_id"]
                for row in public_outcomes
                if isinstance(row, dict) and row.get("applied") is True
            }
        )
        summary["unapplied_statement_count"] = sum(
            isinstance(row, dict) and row.get("applied") is False for row in public_outcomes
        )
    return summary


def _statement_outcomes(
    records: list[tuple[str, ManagerWord]],
    decisions: list[dict[str, object]],
    withheld: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Whitelist one public outcome per statement, including losing/conflicting sources."""
    results: dict[str, tuple[bool, str]] = {}
    for row in decisions:
        items = row.get("evidence", [])
        sources = items if isinstance(items, list) else []
        if not sources and isinstance(row.get("evidence_id"), str):
            sources = [row]
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("evidence_id"), str):
                continue
            identity = source["evidence_id"]
            reason = str(source.get("reason", row.get("reason", "evidence_not_applied")))
            applied = row.get("status") == "applied" and (
                reason == "eligible" or row.get("reason") == "explicit_full_match_restriction"
            )
            if applied or row.get("reason") in (
                "conflicting_sources",
                "duplicate_evidence_or_source",
                "zero_prior_without_conditional_mean",
            ):
                reason = str(row.get("reason", reason))
            results[identity] = (applied, reason)
    for row in withheld:
        identity = row.get("evidence_id")
        if isinstance(identity, str):
            results[identity] = (False, str(row["reason"]))
    outcomes: list[dict[str, object]] = []
    for identity, word in records:
        applied, reason = results.get(identity, (False, "evidence_not_applied"))
        outcomes.append(
            {
                "player_id": word.player_id,
                "disposition": word.disposition,
                "applied": applied,
                "reason": reason,
                "source_url": word.source_url,
                "source_published_at": word.published_at_utc,
            }
        )
    return outcomes


def _minute_updates(
    base: pd.DataFrame,
    news: list[ParticipationEvidence],
    words: Mapping[str, ManagerWord],
    *,
    inputs: RecommendationInputs,
    football: FootballForecast,
    basis: FixtureComponentBasis | None,
    basis_reason: str | None,
) -> tuple[
    pd.DataFrame,
    list[ParticipationEvidence],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    """Use the existing source-time gate, then change a verified fixture basis once."""
    minute_news = [item for item in news if item.disposition == FULL_MATCH_UNAVAILABLE]
    ordinary_news = [item for item in news if item.disposition != FULL_MATCH_UNAVAILABLE]
    metadata: dict[str, object] = {
        "available": basis is not None,
        "reason": basis_reason or ("missing_components" if basis is None else None),
        "components_fingerprint": None if basis is None else basis.companion["fingerprint"],
        "forecast_fingerprint": football.fingerprint,
        "role_estimates": fixture_role_estimates(basis, inputs),
    }
    if not minute_news:
        return base, news, [], [], metadata
    first = int(inputs.deadline.gameweek)
    cutoff = pd.Timestamp(inputs.captured_at_utc)
    deadline = pd.Timestamp(inputs.deadline.deadline_utc)
    # This is a source eligibility audit, not another probability update. Its table
    # is discarded. Absence is applied only after the accepted minute intervention.
    checked = apply_participation_updates(
        base,
        news,
        season=inputs.season,
        as_of=cutoff,
        deadlines={first: deadline},
        base_revision=football.fingerprint,
    )
    checks = {row["player_id"]: row for row in checked.diagnostics}
    minute_players = {item.player_id for item in minute_news}
    blocked_audit = [
        row
        for row in checked.diagnostics
        if row["player_id"] in minute_players
        and row.get("reason") in ("conflicting_sources", "duplicate_evidence_or_source")
    ]
    blocked_players = {row["player_id"] for row in blocked_audit}
    ordinary_news = [item for item in ordinary_news if item.player_id not in blocked_players]
    accepted: list[ExplicitMinuteEvidence] = []
    withheld: list[dict[str, object]] = []
    minute_counts = Counter(item.player_id for item in minute_news)

    def refuse(item: ParticipationEvidence, reason: str) -> None:
        withheld.append(
            {
                "player_id": item.player_id,
                "disposition": item.disposition,
                "evidence_id": item.evidence_id,
                "reason": reason,
            }
        )

    for item in minute_news:
        check = checks.get(item.player_id, {})
        if item.player_id in blocked_players:
            # Preserve the full-set refusal, including ordinary claims. Dropping the
            # minute claim must not make a duplicate-source absence eligible later.
            continue
        provenance = check.get("evidence", [])
        records = provenance if isinstance(provenance, list) else []
        source: dict[str, object] = next(
            (row for row in records if row["evidence_id"] == item.evidence_id), {}
        )
        # The established engine emits this semantic refusal only after all source,
        # deadline, freshness and capture-time checks have passed.
        if source.get("reason") != "categorical_statement_has_no_probability":
            refuse(item, str(source.get("reason", check.get("reason", "outside_projection"))))
            continue
        if any(
            row.get("disposition") == "stated_expected_absent" and row.get("reason") == "eligible"
            for row in records
        ):
            refuse(item, "explicit_absence_supersedes_minute_restriction")
            continue
        if minute_counts[item.player_id] != 1:
            refuse(item, "overlapping_minute_statements")
            continue
        if basis is None:
            refuse(item, basis_reason or "missing_components")
            continue
        if basis.served["fingerprint"] != football.fingerprint:
            refuse(item, "component_forecast_mismatch")
            continue
        effective = base.loc[base.player_id.eq(item.player_id), "appearance_probability"]
        if len(effective) != 1 or float(effective.iloc[0]) <= 0:
            refuse(item, "zero_effective_appearance_basis")
            continue
        word = words[item.evidence_id]
        rows = basis.fixture_rows
        scoped = rows.loc[rows.player_code.eq(item.player_id) & rows.GW.eq(first)]
        if len(scoped) != 1:
            refuse(item, "ambiguous_current_week_fixture")
            continue
        row = scoped.iloc[0]
        if pd.Timestamp(row.kickoff) <= cutoff:
            refuse(item, "fixture_not_after_capture")
            continue
        if row.appearance_probability <= 0 or (
            row.minute_probability_3 > 0
            and row.minute_probability_1 + row.minute_probability_2 <= 0
        ):
            refuse(item, "no_learned_positive_sub90_support")
            continue
        try:
            if word.source_sha256 is None or word.span_start is None or word.span_end is None:
                raise ValueError("Missing verified source span.")
            evidence = ExplicitMinuteEvidence(
                evidence_id=item.evidence_id,
                player_id=item.player_id,
                gameweek=first,
                fixture_ids=(int(row.fixture),),
                restriction="no_full_match",
                source_url=str(word.source_url),
                source_sha256=word.source_sha256,
                span_start=word.span_start,
                span_end=word.span_end,
            )
        except (TypeError, ValueError):
            refuse(item, "verified_source_span_missing")
            continue
        accepted.append(evidence)
    if not accepted or basis is None:
        return base, ordinary_news, blocked_audit, withheld, metadata
    try:
        intervention = apply_explicit_minute_evidence(basis, accepted)
    except ValueError:
        # An optional, unsupported physical intervention never makes football advice
        # unavailable. All selected restrictions are refused together, visibly.
        selected = {item.evidence_id for item in accepted}
        for item in minute_news:
            if item.evidence_id in selected:
                refuse(item, "unsupported_minute_intervention")
        return base, ordinary_news, blocked_audit, withheld, metadata
    original = basis.weekly_rows
    revised = intervention.weekly_rows
    changed = original.expected_points.ne(revised.expected_points) & original.gameweek.eq(first)
    values = revised.loc[changed].set_index("player_id").expected_points
    updated = base.copy(deep=True)
    mask = updated.player_id.isin(values.index)
    updated.loc[mask, "expected_points"] = updated.loc[mask, "player_id"].map(values)
    # The pure intervention preserves q; retain the exact loaded q bytes here.
    minute_audit: list[dict[str, object]] = [
        {
            "player_id": row["player_id"],
            "gameweek": first,
            "status": "applied",
            "reason": "explicit_full_match_restriction",
            "evidence": [row],
            "minutes_reestimated": True,
            "starts_reestimated": False,
        }
        for row in intervention.evidence_audit
    ]
    metadata.update(
        intervention_fingerprint=intervention.fingerprint,
        intervention_contract=intervention.contract_version,
        assumptions=list(intervention.assumptions),
        affected_player_count=int(mask.sum()),
        role_estimates=fixture_role_estimates(
            basis,
            inputs,
            revised_rows=intervention.fixture_rows,
            applied_fixtures={
                (item.player_id, fixture) for item in accepted for fixture in item.fixture_ids
            },
        ),
    )
    return updated, ordinary_news, blocked_audit + minute_audit, withheld, metadata


def bind_football_participation(
    football: FootballForecast,
    inputs: RecommendationInputs,
    *,
    manager_words: ManagerWords | None,
    rotation_table_sha256: str | None,
    minute_basis: FixtureComponentBasis | None = None,
    minute_basis_reason: str | None = None,
) -> FootballForecast:
    """Apply captured first-week evidence without guessing later recovery or starts.

    The captured feed is already applied by both artifact readers. Its percentage is
    recorded and checked as a no-op against that same immutable basis. It is not a
    second independent opinion competing with newly supplied manager evidence. Both
    checks start from the original projection; their outputs are never multiplied.
    A verified optional fixture basis permits an explicit full-match restriction to
    redistribute learned minutes and club attacking shares before absence is applied.
    """
    first = int(inputs.deadline.gameweek)
    as_of = pd.Timestamp(inputs.captured_at_utc)
    deadline = pd.Timestamp(inputs.deadline.deadline_utc)
    if "appearance_probability" not in football.horizon.table:
        # Older handoffs without a joint E/q basis remain usable, but cannot safely
        # be adjusted by this adapter. Missing q is not a certainty of appearance.
        return replace(
            football,
            projection=replace(
                football.projection,
                diagnostics={
                    **football.projection.diagnostics,
                    "participation_evidence": {
                        "version": FOOTBALL_PARTICIPATION_VERSION,
                        "contract": PARTICIPATION_UPDATE_CONTRACT,
                        "base_revision": football.fingerprint,
                        "source_snapshot_id": inputs.snapshot_id,
                        "as_of": str(as_of),
                        "gameweek": first,
                        "deadline": str(deadline),
                        "rotation_table_sha256": rotation_table_sha256,
                        "reason": "unsupported_contract",
                        "captured_percentages": [],
                        "manager_statements": [],
                        "unapplied_statements": [],
                        "statement_outcomes": [
                            {
                                "player_id": word.player_id,
                                "disposition": word.disposition,
                                "applied": False,
                                "reason": "unsupported_contract",
                                "source_url": word.source_url,
                                "source_published_at": word.published_at_utc,
                            }
                            for word in (() if manager_words is None else manager_words.words)
                        ],
                        "external_calibration_supplied": False,
                        "starts_reestimated": False,
                        "minutes_reestimated": False,
                        "future_rows_recovered": False,
                    },
                },
            ),
        )
    base = football.horizon.table.loc[football.horizon.table.gameweek.eq(first)].copy()
    # This is a basis for the same captured percentage, not an inferred future health
    # state. A contextual artifact may additionally contain an absence: q=0 remains 0.
    stated = inputs.availability.set_index("player_id").chance_of_playing
    percentages = pd.to_numeric(stated, errors="coerce")
    base["availability_multiplier"] = base.player_id.map(percentages).div(100.0)
    captured: list[ParticipationEvidence] = []
    for player_id, percentage in stated.items():
        if pd.isna(percentage):
            continue
        captured.append(
            ParticipationEvidence(
                evidence_id=f"{inputs.snapshot_id}:availability:{player_id}:{first}",
                player_id=int(str(player_id)),
                season=inputs.season,
                gameweek=first,
                deadline=deadline,
                published_at=as_of,
                captured_at=as_of,
                valid_until=deadline,
                source_id=inputs.snapshot_id,
                kind="captured_source_percentage",
                source_url="https://fantasy.premierleague.com/api/bootstrap-static/",
                source_percentage=percentage,
            )
        )
    feed = apply_participation_updates(
        base,
        captured,
        season=inputs.season,
        as_of=as_of,
        deadlines={first: deadline},
        base_revision=football.fingerprint,
    )
    news: list[ParticipationEvidence] = []
    source_words: dict[str, ManagerWord] = {}
    statement_records: list[tuple[str, ManagerWord]] = []
    withheld: list[dict[str, object]] = []
    if manager_words is not None:
        for word in manager_words.words:
            identity = hashlib.sha256(
                json.dumps(
                    [rotation_table_sha256, word.player_id, word.disposition, word.source_url],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            statement_records.append((identity, word))
            reason = None
            if not rotation_table_sha256 or (
                manager_words.source_check != SOURCE_CHECK_CITED_DOCUMENTS_HELD
            ):
                reason = "source_documents_unverified"
            elif (manager_words.season, manager_words.gameweek) != (inputs.season, first):
                reason = "decision_week_mismatch"
            elif word.words_status == WORDS_UNRESOLVED:
                reason = "source_span_unresolved"
            elif (
                not word.source_url
                or word.published_at_utc is None
                or word.fetched_at_utc is None
                or word.published_precision != "instant"
            ):
                reason = "source_time_or_citation_missing"
            if reason is None:
                reason = manager_word_attestation_reason(word)
            if reason is None and word.disposition in (
                "stated_expected_absent",
                FULL_MATCH_UNAVAILABLE,
                "stated_expected_to_start",
                "stated_minutes_limited",
            ):
                fixtures = base.loc[base.player_id.eq(word.player_id), "fixture_count"]
                if len(fixtures) != 1 or int(fixtures.iloc[0]) != 1:
                    reason = "ambiguous_current_week_fixture"
            if reason is not None:
                withheld.append(
                    {
                        "player_id": word.player_id,
                        "disposition": word.disposition,
                        "evidence_id": identity,
                        "reason": reason,
                    }
                )
                continue
            try:
                assert word.published_at_utc is not None
                assert word.fetched_at_utc is not None
                published = pd.Timestamp(word.published_at_utc)
                fetched = pd.Timestamp(word.fetched_at_utc)
            except (TypeError, ValueError):
                withheld.append(
                    {
                        "player_id": word.player_id,
                        "disposition": word.disposition,
                        "evidence_id": identity,
                        "reason": "invalid_source_timing",
                    }
                )
                continue
            source_words[identity] = word
            news.append(
                ParticipationEvidence(
                    evidence_id=identity,
                    player_id=word.player_id,
                    season=inputs.season,
                    gameweek=first,
                    deadline=deadline,
                    published_at=published,
                    captured_at=fetched,
                    valid_until=deadline,
                    source_id=str(word.source_url),
                    source_url=word.source_url,
                    kind="source_statement",
                    disposition=word.disposition,
                )
            )
    base, news, minute_audit, minute_withheld, minute_metadata = _minute_updates(
        base,
        news,
        source_words,
        inputs=inputs,
        football=football,
        basis=minute_basis,
        basis_reason=minute_basis_reason,
    )
    withheld.extend(minute_withheld)
    result = apply_participation_updates(
        base,
        news,
        season=inputs.season,
        as_of=as_of,
        deadlines={first: deadline},
        base_revision=football.fingerprint,
    )
    adjusted = football.horizon.table.copy(deep=True)
    first_mask = adjusted.gameweek.eq(first)
    for column in ("expected_points", "appearance_probability"):
        adjusted.loc[first_mask, column] = result.table[column].to_numpy()
    statements = [
        row for row in result.diagnostics if row.get("reason") != "no_evidence"
    ] + minute_audit
    audit = {
        "version": FOOTBALL_PARTICIPATION_VERSION,
        "contract": PARTICIPATION_UPDATE_CONTRACT,
        "base_revision": football.fingerprint,
        "source_snapshot_id": inputs.snapshot_id,
        "as_of": str(as_of),
        "gameweek": first,
        "deadline": str(deadline),
        "rotation_table_sha256": rotation_table_sha256,
        "captured_percentages": [
            row for row in feed.diagnostics if row.get("reason") != "no_evidence"
        ],
        "manager_statements": statements,
        "statement_outcomes": _statement_outcomes(statement_records, statements, withheld),
        "unapplied_statements": withheld,
        "external_calibration_supplied": False,
        "minutes_reestimated": any(row.get("status") == "applied" for row in minute_audit),
        "starts_reestimated": False,
        "minute_statements_unapplied": any(
            row.get("disposition") == FULL_MATCH_UNAVAILABLE for row in withheld
        )
        or any(row.get("status") != "applied" for row in minute_audit),
        "minute_basis": minute_metadata,
        "future_rows_recovered": False,
        "inherited_future_zero": bool(
            (
                adjusted.gameweek.ne(first)
                & adjusted.fixture_count.gt(0)
                & adjusted.appearance_probability.eq(0)
            ).any()
        ),
    }
    role_estimates = minute_metadata.get("role_estimates", [])
    assert isinstance(role_estimates, list)
    projection = replace(
        football.projection,
        table=adjusted.loc[first_mask].copy(),
        unavailable_players=tuple(
            int(player)
            for player in adjusted.loc[
                first_mask & adjusted.appearance_probability.eq(0), "player_id"
            ]
        ),
        diagnostics={
            **football.projection.diagnostics,
            "participation_evidence": audit,
            "fixture_role_estimates": bind_role_absences(role_estimates, result.table),
        },
    )
    return replace(
        football, horizon=replace(football.horizon, table=adjusted), projection=projection
    )
