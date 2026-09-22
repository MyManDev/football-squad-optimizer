"""Bind captured feed availability and source-resolved manager claims to football input."""

from __future__ import annotations

from typing import Any

import pandas as pd

from squadopt.application.manager_words import WORDS_UNRESOLVED, ManagerWords
from squadopt.prediction.availability import apply_availability


def bind_football_context(
    roster: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    cutoff: pd.Timestamp,
    manager_words: ManagerWords | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Keep source percentages separate from learned minutes; no LLM confidence parsing.

    No later-week recovery time is invented. The captured eligibility state is held
    until another explicit observation updates it. Minute-limited is a categorical
    restriction on full-match support, not a generated playing probability.
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
    for word in manager_words.words:
        if word.player_id not in set(result.player_id):
            raise ValueError("Manager evidence names a player outside the captured roster.")
        if word.disposition not in ("stated_expected_absent", "stated_minutes_limited"):
            continue  # expected start/return/risk is not a calibrated numeric probability
        if (
            not word.source_url
            or word.published_at_utc is None
            or word.fetched_at_utc is None
            or word.words_status == WORDS_UNRESOLVED
        ):
            raise ValueError("An applied manager statement must have source and timestamps.")
        published = pd.Timestamp(word.published_at_utc)
        fetched = pd.Timestamp(word.fetched_at_utc)
        if (
            published.tzinfo is None
            or fetched.tzinfo is None
            or not published <= fetched < cutoff
            or cutoff - published > pd.Timedelta(days=7)
        ):
            raise ValueError("Manager statement is late, stale or has invalid source timing.")
        mask = result.player_id.eq(word.player_id)
        if word.disposition == "stated_expected_absent":
            result.loc[mask, "availability_probability"] = 0.0
        else:
            result.loc[mask, "minutes_limited"] = True
        audit.append(
            {
                "player_id": word.player_id,
                "disposition": word.disposition,
                "source_url": word.source_url,
                "published_at_utc": word.published_at_utc,
                "fetched_at_utc": word.fetched_at_utc,
            }
        )
    return result, audit
