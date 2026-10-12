"""Original-byte and causal synthetic source contract regressions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

import pytest
from tests.unit.test_football_tactical_matchup import CUTOFF, _observation, _projection

import squadopt.features.football_tactical_inputs as inputs
from squadopt.features.football_tactical_inputs import (
    RAW_FPL_CREDITS_VERSION,
    RAW_PHYSICAL_GOALS_VERSION,
    RAW_PROJECTION_VERSION,
    STYLE_COUNTS,
    TRAITS,
    TacticalProjection,
    TacticalSource,
    projection_digest,
    read_tactical_observation,
    read_tactical_projection,
    team_features,
    validate_tactical_projection,
)


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _bound(payload: bytes, source: TacticalSource) -> TacticalSource:
    return replace(source, raw_sha256=hashlib.sha256(payload).hexdigest())


def _projection_document(projection: TacticalProjection) -> dict[str, Any]:
    row = asdict(projection)
    del row["source"]
    row["contract_version"] = RAW_PROJECTION_VERSION
    for name in ("home_style", "away_style"):
        row[name]["counts"] = dict(zip(STYLE_COUNTS, row[name]["counts"], strict=True))
    for state in row["states"]:
        for side in (state["home"], state["away"]):
            for player in side["players"]:
                player["profile"]["attributes"] = dict(
                    zip(TRAITS, player["profile"]["attributes"], strict=True)
                )
    return row


def _read_projection(document: dict[str, Any] | None = None) -> TacticalProjection:
    original = _projection()
    payload = _bytes(document if document is not None else _projection_document(original))
    return read_tactical_projection(
        payload,
        source=_bound(payload, original.source),
        season=original.season,
        gameweek=original.gameweek,
    )


def _final_documents(projection: TacticalProjection) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = _observation()
    identity = {
        "season": projection.season,
        "gameweek": projection.gameweek,
        "fixture": projection.fixture,
        "home_club": projection.home_club,
        "away_club": projection.away_club,
        "kickoff": projection.kickoff,
        "decision_at": projection.decision_at,
        "projection_sha256": projection_digest(projection),
        "outcome_available_at": observation.outcome_available_at,
        "final": True,
        "rules_version": observation.rules_version,
    }
    return (
        {
            **identity,
            "contract_version": RAW_PHYSICAL_GOALS_VERSION,
            "physical_goals": list(observation.physical_goals),
        },
        {
            **identity,
            "contract_version": RAW_FPL_CREDITS_VERSION,
            "credits": [asdict(c) for c in observation.credits],
        },
    )


def _read_observation(
    goal: dict[str, Any] | None = None, credit: dict[str, Any] | None = None
) -> Any:
    projection = _read_projection()
    original = _observation()
    defaults = _final_documents(projection)
    goal_raw, credit_raw = (
        _bytes(defaults[0] if goal is None else goal),
        _bytes(defaults[1] if credit is None else credit),
    )
    return read_tactical_observation(
        goal_raw,
        credit_raw,
        projection=projection,
        goal_source=_bound(goal_raw, original.goal_source),
        credit_source=_bound(credit_raw, original.credit_source),
        training_cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
    )


def _at(document: Any, path: tuple[str | int, ...]) -> Any:
    for field in path:
        document = document[field]
    return document


def test_projection_original_bytes_and_all_named_nullable_sources_round_trip() -> None:
    original = _projection()
    document = _projection_document(original)
    loaded = _read_projection(document)
    assert loaded == replace(original, source=_bound(_bytes(document), original.source))
    assert len(loaded.states[0].home.players[0].profile.attributes) == len(TRAITS)
    assert loaded.home_style.counts == original.home_style.counts
    assert loaded.source.raw_sha256 == hashlib.sha256(_bytes(document)).hexdigest()


def test_independent_final_sources_round_trip_with_original_sha_and_full_roster() -> None:
    loaded = _read_observation()
    assert loaded.physical_goals == (3, 1)
    assert len(loaded.credits) == 8
    assert loaded.credits == _observation().credits
    assert loaded.goal_source.raw_sha256 != loaded.credit_source.raw_sha256
    assert (
        projection_digest(loaded.projection)
        == _final_documents(loaded.projection)[0]["projection_sha256"]
    )


@pytest.mark.parametrize(
    "season,gameweek", [("2025-26", 3), ("2024-26", 3), ("2024-25", True), ("2024-25", 39)]
)
def test_declared_projection_context_refuses_before_source_decoding(
    season: str, gameweek: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        inputs, "_raw_json", lambda *args: pytest.fail("context guard decoded raw source")
    )
    with pytest.raises(ValueError):
        read_tactical_projection(
            b"not-json", source=_projection().source, season=season, gameweek=gameweek
        )


@pytest.mark.parametrize("source_change", ["rights", "wrong-kind", "wrong-sha", "future-published"])
def test_projection_source_guards_refuse_before_decoding(
    source_change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _projection()
    raw = _bytes(_projection_document(original))
    source = _bound(raw, original.source)
    if source_change == "rights":
        source = replace(source, model_use_approved=False)
    elif source_change == "wrong-kind":
        source = replace(source, source_kind="traits")
    elif source_change == "wrong-sha":
        source = replace(source, raw_sha256="b" * 64)
    else:
        source = replace(source, published_at="2024-09-02T00:00:00Z")
    monkeypatch.setattr(
        inputs, "_raw_json", lambda *args: pytest.fail("source guard decoded raw source")
    )
    with pytest.raises(ValueError):
        read_tactical_projection(
            raw, source=source, season=original.season, gameweek=original.gameweek
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"nested":{"a":1,"a":2}}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b"\xff",
        b"{",
        b"[]",
    ],
)
def test_invalid_json_duplicate_fields_and_nonfinite_literals_refuse(raw: bytes) -> None:
    original = _projection()
    with pytest.raises(ValueError):
        read_tactical_projection(
            raw,
            source=_bound(raw, original.source),
            season=original.season,
            gameweek=original.gameweek,
        )


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("home_style",),
        ("home_style", "source"),
        ("home_style", "fixtures", 0),
        ("states", 0),
        ("states", 0, "home"),
        ("states", 0, "home", "players", 0),
        ("states", 0, "home", "players", 0, "profile"),
        ("states", 0, "home", "players", 0, "profile", "attributes"),
    ],
)
def test_projection_unknown_fields_are_rejected_at_every_nesting_level(
    path: tuple[str | int, ...],
) -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    _at(document, path)["unexpected"] = 1
    with pytest.raises(ValueError, match="exactly its versioned named fields"):
        _read_projection(document)


@pytest.mark.parametrize(
    "field,value", [("season", "2023-24"), ("gameweek", 4), ("contract_version", "unknown")]
)
def test_raw_projection_must_match_declared_version_season_and_gameweek(
    field: str, value: Any
) -> None:
    document = _projection_document(_projection())
    document[field] = value
    with pytest.raises(ValueError, match="declared version/context"):
        _read_projection(document)


@pytest.mark.parametrize(
    "path,field,value",
    [
        ((), "gameweek", True),
        (("states", 0), "weight", True),
        (("states", 0, "home"), "base_goal_rate", float("inf")),
        (("states", 0, "home", "players", 0), "minutes", True),
        (("states", 0, "home", "players", 0), "tactical_role", None),
        (("states", 0, "home", "players", 0, "profile", "attributes"), "heading", True),
        (("states", 0, "home", "players", 0, "profile", "attributes"), "heading", 1.5),
        (("states", 0, "home", "players", 0, "profile", "attributes"), "heading", 0),
        (("states", 0, "home", "players", 0, "profile", "attributes"), "heading", 21),
        (("home_style", "counts"), "cross_attempts", True),
        (("home_style", "counts"), "cross_attempts", -1),
    ],
)
def test_json_types_ranges_and_explicit_tactical_roles_are_not_coerced(
    path: tuple[str | int, ...], field: str, value: Any
) -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    _at(document, path)[field] = value
    with pytest.raises(ValueError):
        _read_projection(document)


@pytest.mark.parametrize("channel", ["trait", "style"])
def test_published_unknowns_are_preserved_then_needed_feature_channel_refuses(channel: str) -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    if channel == "trait":
        document["states"][0]["home"]["players"][3]["profile"]["attributes"]["heading"] = None
    else:
        document["home_style"]["counts"]["cross_attempts"] = None
    loaded = _read_projection(document)
    if channel == "trait":
        assert loaded.states[0].home.players[3].profile.attributes[TRAITS.index("heading")] is None
    else:
        assert loaded.home_style.counts[STYLE_COUNTS.index("cross_attempts")] is None
    with pytest.raises(ValueError, match=r"lacks named trait|unavailable exposure or counts"):
        team_features(loaded, loaded.states[0], home=True)


@pytest.mark.parametrize("channel", ["keeper", "defense"])
def test_missing_explicit_keeper_or_defense_channel_is_not_filled(channel: str) -> None:
    projection = _read_projection()
    state = projection.states[0]
    players = tuple(
        replace(p, tactical_role="attacker")
        if (
            p.tactical_role == "goalkeeper"
            if channel == "keeper"
            else p.tactical_role in ("defender", "midfielder")
        )
        else p
        for p in state.away.players
    )
    altered = replace(
        projection, states=(replace(state, away=replace(state.away, players=players)),)
    )
    validate_tactical_projection(altered)
    with pytest.raises(ValueError, match="no projected trait exposure"):
        team_features(altered, altered.states[0], home=True)


def test_original_source_uid_cannot_map_to_two_persistent_players() -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    home, away = document["states"][0]["home"]["players"], document["states"][0]["away"]["players"]
    away[0]["profile"]["original_identity"] = home[0]["profile"]["original_identity"]
    with pytest.raises(ValueError, match="source identity maps to multiple players"):
        _read_projection(document)


def test_original_identity_namespace_includes_provider_and_version() -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    home, away = document["states"][0]["home"]["players"], document["states"][0]["away"]["players"]
    away[0]["profile"]["original_identity"] = home[0]["profile"]["original_identity"]
    away[0]["profile"]["source"]["provider"] = "independent-synthetic-provider"
    assert _read_projection(document).away_club == 2


def test_style_fixture_cannot_claim_current_season_with_a_prior_season_kickoff() -> None:
    document = json.loads(_bytes(_projection_document(_projection())))
    style = document["home_style"]
    style["window_start"] = "2023-08-01T00:00:00Z"
    style["fixtures"][0]["kickoff"] = "2023-08-10T12:00:00Z"
    style["fixtures"][0]["final_at"] = "2023-08-10T15:00:00Z"
    with pytest.raises(ValueError, match="fixture exposure or finality"):
        _read_projection(document)


def test_native_assist_fraction_is_conditional_on_credited_goals_for_personal_bound() -> None:
    projection = _read_projection()
    state = projection.states[0]
    home = replace(
        state.home,
        scored_fraction=0.5,
        assist_fraction=1,
        players=tuple(
            replace(p, native_assist_share=p.native_goal_share) for p in state.home.players
        ),
    )
    # The striker receives .5*.7 goals plus .5*1*.7 assists per physical event.
    validate_tactical_projection(replace(projection, states=(replace(state, home=home),)))
    assert 0.5 * 0.7 + 0.5 * 1 * 0.7 <= 1 < 0.5 * 0.7 + 1 * 0.7


@pytest.mark.parametrize("source_name", ["goal_source", "credit_source"])
@pytest.mark.parametrize("field", ["published_at", "captured_at"])
def test_each_final_source_strict_cutoff_refuses_before_any_json(
    source_name: str, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, original = _read_projection(), _observation()
    sources = {"goal_source": original.goal_source, "credit_source": original.credit_source}
    sources[source_name] = replace(sources[source_name], **{field: CUTOFF})
    monkeypatch.setattr(
        inputs, "_raw_json", lambda *args: pytest.fail("late source decoded labels")
    )
    with pytest.raises(ValueError, match="causal cutoff"):
        read_tactical_observation(
            b"not-json",
            b"not-json",
            projection=projection,
            **sources,
            training_cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
        )


@pytest.mark.parametrize(
    "guard", ["target", "unselected", "protected", "rights", "wrong-kind", "credit-sha"]
)
def test_final_context_rights_and_both_hashes_are_guarded_before_any_decode(
    guard: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, original = _read_projection(), _observation()
    goal_source, credit_source = original.goal_source, original.credit_source
    allowed, excluded = ("2024-25",), None
    if guard == "target":
        excluded = (projection.season, projection.gameweek)
    elif guard == "unselected":
        allowed = ("2023-24",)
    elif guard == "protected":
        projection = replace(projection, season="2025-26")
    elif guard == "rights":
        credit_source = replace(credit_source, model_use_approved=False)
    elif guard == "wrong-kind":
        credit_source = replace(credit_source, source_kind="traits")
    else:
        goal_source = _bound(b"{}", goal_source)
    monkeypatch.setattr(
        inputs, "_raw_json", lambda *args: pytest.fail("final guard decoded labels")
    )
    with pytest.raises(ValueError):
        read_tactical_observation(
            b"{}",
            b"{}",
            projection=projection,
            goal_source=goal_source,
            credit_source=credit_source,
            training_cutoff=CUTOFF,
            allowed_seasons=allowed,
            excluded_target=excluded,
        )


@pytest.mark.parametrize(
    "document,field,value",
    [
        ("goal", "fixture", 9000),
        ("credit", "away_club", 9),
        ("goal", "season", "2023-24"),
        ("credit", "projection_sha256", "b" * 64),
        ("goal", "gameweek", True),
        ("credit", "kickoff", "2024-09-02T12:00:00Z"),
        ("credit", "decision_at", "2024-09-01T10:00:00Z"),
        ("goal", "final", False),
        ("credit", "final", "true"),
        ("credit", "rules_version", "other-rules"),
        ("goal", "outcome_available_at", "2024-09-01T16:00:00Z"),
        ("goal", "contract_version", "unknown"),
    ],
)
def test_independent_final_envelopes_bind_every_fixture_clock_and_rules(
    document: str, field: str, value: Any
) -> None:
    goal, credit = _final_documents(_read_projection())
    (goal if document == "goal" else credit)[field] = value
    with pytest.raises(ValueError):
        _read_observation(goal, credit)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-credit",
        "duplicate-credit",
        "invented-credit",
        "wrong-club",
        "bool-goal",
        "null-assist",
        "head-exceeds-physical",
        "personal-exceeds-physical",
        "extra-field",
        "one-physical-side",
    ],
)
def test_complete_final_counts_never_turn_missing_or_invalid_records_into_zero(
    mutation: str,
) -> None:
    goal, credit = _final_documents(_read_projection())
    if mutation == "missing-credit":
        credit["credits"].pop()
    elif mutation == "duplicate-credit":
        credit["credits"].append(dict(credit["credits"][0]))
    elif mutation == "invented-credit":
        credit["credits"][0]["player_code"] = 999
    elif mutation == "wrong-club":
        credit["credits"][0]["club"] = 2
    elif mutation == "bool-goal":
        goal["physical_goals"][0] = True
    elif mutation == "null-assist":
        credit["credits"][0]["assists"] = None
    elif mutation == "head-exceeds-physical":
        credit["credits"][0]["goals"] = 1
    elif mutation == "personal-exceeds-physical":
        credit["credits"][3]["assists"] = 1
    elif mutation == "extra-field":
        credit["credits"][0]["extra"] = 1
    else:
        goal["physical_goals"].pop()
    with pytest.raises(ValueError):
        _read_observation(goal, credit)


def test_final_settlement_must_be_after_kickoff_and_no_later_than_each_capture() -> None:
    goal, credit = _final_documents(_read_projection())
    for document in (goal, credit):
        document["outcome_available_at"] = "2024-09-01T16:00:00Z"
    with pytest.raises(ValueError, match="capture predates declared settlement"):
        _read_observation(goal, credit)


def test_timezone_offset_is_rejected_without_assuming_local_time() -> None:
    document = _projection_document(_projection())
    document["decision_at"] = "2024-09-01T11:00:00+03:00"
    with pytest.raises(ValueError, match="explicit UTC"):
        _read_projection(document)


def test_malformed_declared_sources_and_allowlists_refuse_with_value_error() -> None:
    with pytest.raises(ValueError, match="wrong semantic kind"):
        read_tactical_projection(b"{}", source=None, season="2024-25", gameweek=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique explicit tactical season"):
        read_tactical_observation(
            b"{}",
            b"{}",
            projection=_projection(),
            goal_source=_observation().goal_source,
            credit_source=_observation().credit_source,
            training_cutoff=CUTOFF,
            allowed_seasons=([],),
        )  # type: ignore[arg-type]


def test_source_resource_limit_is_checked_before_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inputs, "MAX_TACTICAL_SOURCE_BYTES", 2)
    monkeypatch.setattr(inputs, "_raw_json", lambda *args: pytest.fail("oversized source decoded"))
    with pytest.raises(ValueError, match="bounded nonempty original bytes"):
        read_tactical_projection(
            b"{} ", source=_bound(b"{} ", _projection().source), season="2024-25", gameweek=3
        )
