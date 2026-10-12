"""Bind captured feed availability and source-resolved manager claims to football input."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from squadopt.application.manager_words import (
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    WORDS_UNRESOLVED,
    ManagerWord,
    ManagerWords,
)
from squadopt.prediction.availability import apply_availability

FULL_MATCH_UNAVAILABLE = "stated_full_match_unavailable"


def manager_word_attestation_reason(word: ManagerWord) -> str | None:
    """Require independently checked publication and upcoming league scope."""
    if (
        not word.publication_verified
        or not word.publication_source
        or not word.publication_source_sha256
    ):
        return "publication_unverified"
    if not word.scope_verified or word.fixture_scope != "upcoming_premier_league":
        if word.fixture_binding_reason == "ambiguous_current_week_fixture":
            return "ambiguous_current_week_fixture"
        return "upcoming_league_scope_unverified"
    return None


def bind_football_context(
    roster: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    cutoff: pd.Timestamp,
    manager_words: ManagerWords | None = None,
    fixture_calendar: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Bind explicit source evidence to one captured upcoming league fixture.

    Generic rotation/minute language never removes full-match support. Both absence
    and an explicit full-match exclusion need verified publication and league scope;
    a double gameweek cannot be narrowed from a weekly label alone.
    """
    if cutoff.tzinfo is None:
        raise ValueError("Football context requires an aware cutoff.")
    result = roster.copy(deep=True)
    applied = apply_availability(result.assign(expected_points=1.0), availability)
    result["availability_probability"] = applied.table.expected_points.to_numpy(float)
    result["minutes_limited"] = False
    audit: list[dict[str, Any]] = []
    if manager_words is None:
        return result, audit
    if manager_words.season != season or manager_words.gameweek != gameweek:
        raise ValueError("Manager evidence does not match the forecast decision week.")
    result["captured_availability_probability"] = result.availability_probability
    result["manager_context_gameweek"] = gameweek
    result["manager_context_fixture"] = pd.Series(pd.NA, index=result.index, dtype="Int64")

    def record(word: ManagerWord, reason: str, *, fixture: int | None = None) -> None:
        audit.append(
            {
                "player_id": word.player_id,
                "disposition": word.disposition,
                "source_url": word.source_url,
                "published_at_utc": word.published_at_utc,
                "fetched_at_utc": word.fetched_at_utc,
                "gameweek": gameweek,
                "fixture_id": fixture,
                "reason": reason,
                "status": "applied" if reason == "explicit_source_restriction" else "unapplied",
            }
        )

    valid: list[tuple[ManagerWord, int]] = []
    for word in manager_words.words:
        if word.player_id not in set(result.player_id):
            raise ValueError("Manager evidence names a player outside the captured roster.")
        reason = manager_word_attestation_reason(word)
        if manager_words.source_check != SOURCE_CHECK_CITED_DOCUMENTS_HELD:
            reason = "source_documents_unverified"
        elif word.words_status == WORDS_UNRESOLVED:
            reason = "source_span_unresolved"
        elif (
            not word.source_url
            or not word.source_sha256
            or word.span_start is None
            or word.span_end is None
            or word.published_at_utc is None
            or word.fetched_at_utc is None
            or word.published_precision != "instant"
        ):
            reason = "source_time_or_citation_missing"
        if reason is not None:
            record(word, reason)
            continue
        assert word.published_at_utc is not None
        assert word.fetched_at_utc is not None
        try:
            published = pd.Timestamp(word.published_at_utc)
            fetched = pd.Timestamp(word.fetched_at_utc)
        except (TypeError, ValueError):
            record(word, "invalid_source_timing")
            continue
        if (
            published.tzinfo is None
            or fetched.tzinfo is None
            or not published <= fetched <= cutoff
            or cutoff - published > pd.Timedelta(days=7)
        ):
            record(word, "ineligible_source_timing")
            continue
        if fixture_calendar is None or "club" not in result:
            record(word, "fixture_scope_unavailable")
            continue
        club = result.loc[result.player_id.eq(word.player_id), "club"].iloc[0]
        matches = fixture_calendar.loc[
            fixture_calendar.club.eq(club) & fixture_calendar.GW.eq(gameweek)
        ]
        if len(matches) != 1:
            record(word, "ambiguous_current_week_fixture")
            continue
        match = matches.iloc[0]
        if pd.Timestamp(match.kickoff) <= cutoff:
            record(word, "fixture_not_after_capture")
            continue
        valid.append((word, int(match.fixture)))
    sources = Counter((word.player_id, word.source_url) for word, _ in valid)
    duplicates = {player for (player, _), count in sources.items() if count > 1}
    absent = {word.player_id for word, _ in valid if word.disposition == "stated_expected_absent"}
    playing = {
        word.player_id
        for word, _ in valid
        if word.disposition in ("stated_expected_to_start", "stated_minutes_limited")
    }
    conflicts = absent & playing
    minute_counts = Counter(
        word.player_id for word, _ in valid if word.disposition == FULL_MATCH_UNAVAILABLE
    )
    for word, fixture in valid:
        if word.player_id in duplicates:
            record(word, "duplicate_evidence_or_source")
        elif word.player_id in conflicts:
            record(word, "conflicting_sources")
        elif word.disposition not in ("stated_expected_absent", FULL_MATCH_UNAVAILABLE):
            record(word, "categorical_statement_has_no_probability")
        elif word.disposition == FULL_MATCH_UNAVAILABLE and word.player_id in absent:
            record(word, "explicit_absence_supersedes_minute_restriction")
        elif word.disposition == FULL_MATCH_UNAVAILABLE and minute_counts[word.player_id] != 1:
            record(word, "overlapping_minute_statements")
        elif (
            word.disposition == FULL_MATCH_UNAVAILABLE
            and not result.loc[result.player_id.eq(word.player_id), "availability_probability"]
            .gt(0)
            .all()
        ):
            record(word, "zero_effective_appearance_basis")
        else:
            mask = result.player_id.eq(word.player_id)
            if word.disposition == "stated_expected_absent":
                result.loc[mask, "availability_probability"] = 0.0
            else:
                result.loc[mask, "minutes_limited"] = True
            result.loc[mask, "manager_context_fixture"] = fixture
            record(word, "explicit_source_restriction", fixture=fixture)
    return result, audit
