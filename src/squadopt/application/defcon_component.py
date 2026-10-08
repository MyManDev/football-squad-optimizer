"""Offline adapter for the fixed, unpromoted 2026-27 DEFCON augmentation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from squadopt.data.snapshots import (
    CapturedSnapshot,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.data.timestamps import as_instant
from squadopt.live.recommendation import InSeasonProjection, infer_season, read_inputs
from squadopt.live.rules import read_season_rules
from squadopt.prediction.defcon_component import (
    DEFCON_CANDIDATE_VERSIONS,
    DEFCON_COMPONENT_CONTRACT_VERSION,
    DEFCON_SEASON,
    FixtureAppearance,
    expected_defcon_term,
    fit_defcon_rates,
)


class DefconInputError(ValueError):
    """An identity, duplicate key or forbidden season invalidates the inventory."""


class DefconMissingInputs(ValueError):
    """This week cannot be paired under the fixed declaration."""


def integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DefconMissingInputs("A required nonnegative integer is absent or invalid.")
    return value


def decode(content: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DefconInputError("A JSON key is duplicated.")
            result[key] = value
        return result

    return json.loads(content, object_pairs_hook=unique)


def payload(snapshot: CapturedSnapshot, name: str) -> Any:
    content = snapshot.payloads.get(name)
    if content is None or payload_checksum(content) != snapshot.metadata.checksums.get(name):
        raise DefconMissingInputs("A required payload is absent or fails its captured checksum.")
    return decode(content)


def identity(snapshot: CapturedSnapshot) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    if snapshot.metadata.source != "fpl-live":
        raise DefconInputError("Only fpl-live input is admitted.")
    metadata = snapshot.metadata
    fingerprint = snapshot_fingerprint(
        source=metadata.source,
        captured_at_utc=metadata.captured_at_utc,
        schema_version=metadata.schema_version,
        checksums=metadata.checksums,
    )
    if (
        metadata.schema_version != "snapshot_v1"
        or metadata.fingerprint != fingerprint
        or (
            metadata.snapshot_id
            != build_snapshot_id(
                source=metadata.source,
                captured_at_utc=metadata.captured_at_utc,
                fingerprint=fingerprint,
            )
        )
    ):
        raise DefconInputError("The decision capture metadata fails its identity binding.")
    bootstrap = payload(snapshot, BOOTSTRAP_PAYLOAD)
    if infer_season(snapshot) != DEFCON_SEASON:
        raise DefconInputError("Only 2026-27 is admitted; 2025-26 input is forbidden.")
    if not isinstance(bootstrap.get("elements"), list):
        raise DefconInputError("The roster is absent or invalid.")
    elements: dict[int, dict[str, Any]] = {}
    codes: set[int] = set()
    for element in bootstrap["elements"]:
        try:
            identifier = integer(element["id"], minimum=1)
            code = integer(element["code"], minimum=1)
            integer(element["team"], minimum=1)
        except (KeyError, TypeError, DefconMissingInputs) as error:
            raise DefconInputError("The roster has an invalid element, code or club.") from error
        if identifier in elements or code in codes:
            raise DefconInputError("The roster has duplicate element ids or persistent codes.")
        if type(element["element_type"]) is not int or element["element_type"] not in (1, 2, 3, 4):
            raise DefconInputError("The published roster contains an invalid position.")
        elements[identifier] = element
        codes.add(code)
    if not elements:
        raise DefconInputError("The roster is empty.")
    return bootstrap, elements


def fixture_map(snapshot: CapturedSnapshot) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for fixture in payload(snapshot, FIXTURES_PAYLOAD):
        identifier = integer(fixture["id"], minimum=1)
        if identifier in result:
            raise DefconInputError("A fixture id is duplicated.")
        result[identifier] = fixture
    return result


def fixture_counts(
    fixtures: Mapping[int, dict[str, Any]], elements: Mapping[int, dict[str, Any]], week: int
) -> dict[int, int]:
    return {
        element["code"]: sum(
            fixture.get("event") == week
            and element["team"] in (fixture["team_h"], fixture["team_a"])
            for fixture in fixtures.values()
        )
        for element in elements.values()
    }


def settled(
    bootstrap: Mapping[str, Any], fixtures: Mapping[int, dict[str, Any]], week: int
) -> bool:
    events = [event for event in bootstrap["events"] if event["id"] == week]
    if not events:
        return False
    if len(events) != 1:
        raise DefconInputError("A required event is duplicated.")
    played = [fixture for fixture in fixtures.values() if fixture.get("event") == week]
    return (
        events[0].get("finished") is True
        and events[0].get("data_checked") is True
        and all(
            fixture.get("finished") is True and fixture.get("finished_provisional") is True
            for fixture in played
        )
    )


@dataclass(frozen=True, slots=True)
class ParsedHistory:
    rows: tuple[FixtureAppearance, ...]
    unmapped_elements: tuple[int, ...]
    schema_crosschecks: int
    excluded_rows: tuple[dict[str, Any], ...] = ()
    schema_disagreements: tuple[dict[str, Any], ...] = ()


def history_week(
    snapshot: CapturedSnapshot,
    *,
    week: int,
    bootstrap: Mapping[str, Any],
    elements: Mapping[int, dict[str, Any]],
    fixtures: Mapping[int, dict[str, Any]],
    award_points: Mapping[str, int],
    deadline_utc: str | None = None,
) -> ParsedHistory:
    """Read awarded labels and exclude invalid fit fixtures from both counts."""
    if not settled(bootstrap, fixtures, week):
        raise DefconMissingInputs("A required prior or realized week is not settled.")
    if deadline_utc is not None and as_instant(snapshot.metadata.captured_at_utc) >= as_instant(
        deadline_utc
    ):
        raise DefconMissingInputs("Fit settlement was captured at or after the target deadline.")
    rows: list[FixtureAppearance] = []
    unmapped: list[int] = []
    excluded: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    seen: set[int] = set()
    crosschecks = 0
    for entry in payload(snapshot, live_payload(week))["elements"]:
        element_id = integer(entry["id"], minimum=1)
        if element_id in seen:
            raise DefconInputError("An event-live element is duplicated.")
        seen.add(element_id)
        if element_id not in elements:
            unmapped.append(element_id)
            continue
        element = elements[element_id]
        code = element["code"]
        position = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[element["element_type"]]
        local: set[int] = set()
        player_rows: list[FixtureAppearance] = []
        player_excluded = False
        try:
            total_minutes = integer(entry["stats"]["minutes"])
            if not isinstance(entry.get("explain"), list):
                raise DefconMissingInputs("Fixture explanations are absent.")
            if total_minutes > 0 and not entry["explain"]:
                raise DefconMissingInputs("Positive gameweek minutes have no fixture explanation.")
        except (DefconMissingInputs, KeyError, TypeError) as error:
            if deadline_utc is None:
                raise DefconMissingInputs("Realized fixture minutes are invalid.") from error
            excluded.append(
                {"gameweek": week, "player_code": code, "fixture": None, "reason": str(error)}
            )
            continue
        for explanation in entry["explain"]:
            fixture_id = explanation.get("fixture")
            try:
                fixture_id = integer(fixture_id, minimum=1)
                if fixture_id in local:
                    raise DefconInputError("A player-fixture explanation is duplicated.")
                local.add(fixture_id)
                fixture = fixtures.get(fixture_id)
                if fixture is None or fixture.get("event") != week:
                    raise DefconMissingInputs("An explanation names an inconsistent fixture.")
                kickoff = fixture.get("kickoff_time")
                if not isinstance(kickoff, str):
                    raise DefconMissingInputs("A required fixture kickoff is absent.")
                if as_instant(kickoff) >= as_instant(snapshot.metadata.captured_at_utc):
                    raise DefconMissingInputs("A settled fixture does not precede its capture.")
                if deadline_utc is not None and as_instant(kickoff) >= as_instant(deadline_utc):
                    raise DefconMissingInputs("A fit fixture is at or after the target deadline.")
                stats: dict[str, dict[str, Any]] = {}
                for stat in explanation["stats"]:
                    key = stat["identifier"]
                    if key in stats:
                        raise DefconInputError("An explanation statistic is duplicated.")
                    stats[key] = stat
                if "minutes" not in stats:
                    raise DefconMissingInputs("A fixture minutes explanation is absent.")
                minutes = integer(stats["minutes"]["value"])
                award = stats.get("defensive_contribution")
                points = 0
                if award is not None:
                    points = integer(award["points"])
                    value = integer(award["value"])
                    if (
                        integer(award["points_modification"]) != 0
                        or points not in (0, award_points[position])
                        or (points > 0 and minutes == 0)
                    ):
                        raise DefconMissingInputs(
                            "An award is modified or differs from captured rules."
                        )
                    if week <= 5 and position != "GK":
                        threshold = 10 if position == "DEF" else 12
                        crosschecks += 1
                        if (value >= threshold) != (points > 0):
                            disagreements.append(
                                {
                                    "gameweek": week,
                                    "player_code": code,
                                    "fixture": fixture_id,
                                    "reason": "award_value_threshold_disagreement",
                                }
                            )
                player_rows.append(
                    FixtureAppearance(
                        DEFCON_SEASON, week, fixture_id, code, position, kickoff, minutes, points
                    )
                )
            except (DefconMissingInputs, KeyError, TypeError) as error:
                if deadline_utc is None:
                    raise DefconMissingInputs("Realized fixture explanation is invalid.") from error
                player_excluded = True
                excluded.append(
                    {
                        "gameweek": week,
                        "player_code": code,
                        "fixture": fixture_id,
                        "reason": str(error),
                    }
                )
        if not player_excluded and sum(row.minutes for row in player_rows) != total_minutes:
            if deadline_utc is None:
                raise DefconMissingInputs(
                    "Fixture minutes do not sum to the reported gameweek minutes."
                )
            excluded.extend(
                {
                    "gameweek": week,
                    "player_code": code,
                    "fixture": row.fixture,
                    "reason": "fixture_minutes_total_mismatch",
                }
                for row in player_rows
            )
            player_rows = []
        if (
            week <= 5
            and total_minutes > 0
            and len(local) == 1
            and not player_excluded
            and position != "GK"
        ):
            count = integer(entry["stats"]["defensive_contribution"])
            threshold = 10 if position == "DEF" else 12
            crosschecks += 1
            if (count >= threshold) != (sum(row.awarded_points for row in player_rows) > 0):
                disagreements.append(
                    {
                        "gameweek": week,
                        "player_code": code,
                        "fixture": next(iter(local)),
                        "reason": "count_award_disagreement",
                    }
                )
        rows.extend(player_rows)
    return ParsedHistory(
        tuple(rows), tuple(sorted(unmapped)), crosschecks, tuple(excluded), tuple(disagreements)
    )


def candidate_handoff(
    snapshot: CapturedSnapshot, base: InSeasonProjection, *, declaration_sha256: str
) -> InSeasonProjection:
    """Return unconditional base plus DEFCON; production project applies availability."""
    if base.season != DEFCON_SEASON:
        raise DefconInputError("Only 2026-27 is admitted; 2025-26 handoffs are forbidden.")
    bootstrap, elements = identity(snapshot)
    if base.source_snapshot_id != snapshot.metadata.snapshot_id:
        raise DefconMissingInputs("The published handoff and decision capture disagree.")
    if base.model_version not in DEFCON_CANDIDATE_VERSIONS or base.augmentation_fingerprint:
        raise DefconMissingInputs("The published default is not an admissible original base.")
    if len(declaration_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in declaration_sha256
    ):
        raise DefconInputError("A declaration SHA-256 is required.")
    codes = {element["code"] for element in elements.values()}
    if set(base.expected_points) != codes:
        raise DefconInputError("The published handoff roster differs from its decision capture.")
    inputs = read_inputs(snapshot, season=DEFCON_SEASON, gameweek=base.gameweek)
    deadline = inputs.deadline.deadline_utc
    if as_instant(snapshot.metadata.captured_at_utc) >= as_instant(deadline):
        raise DefconMissingInputs("The decision capture is not before its own target deadline.")
    rules = read_season_rules(snapshot, season=DEFCON_SEASON)
    awards = {
        ("GK" if p == "GKP" else p): v for p, v in rules.scoring.defensive_contribution.items()
    }
    fixtures = fixture_map(snapshot)
    counts = fixture_counts(fixtures, elements, base.gameweek)
    positions = {
        element["code"]: {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[element["element_type"]]
        for element in elements.values()
    }
    required = frozenset(
        positions[code] for code in codes if positions[code] != "GK" and counts[code]
    )
    if required and base.appearance_probability is None:
        raise DefconMissingInputs("The legacy handoff has no published appearance mapping.")
    histories = [
        history_week(
            snapshot,
            week=week,
            bootstrap=bootstrap,
            elements=elements,
            fixtures=fixtures,
            award_points=awards,
            deadline_utc=deadline,
        )
        for week in range(1, base.gameweek)
    ]
    rows = tuple(row for history in histories for row in history.rows)
    rates = fit_defcon_rates(
        rows,
        target_gameweek=base.gameweek,
        deadline_utc=deadline,
        award_points=awards,
        required_positions=required,
    )
    terms = {
        code: expected_defcon_term(
            player_code=code,
            position=positions[code],
            appearance_probability=(base.appearance_probability or {}).get(code),
            fixture_count=counts[code],
            award_points=awards[positions[code]],
            rates=rates,
        )
        for code in sorted(codes)
    }
    hashes = {
        name: snapshot.metadata.checksums[name]
        for name in (
            BOOTSTRAP_PAYLOAD,
            FIXTURES_PAYLOAD,
            *(live_payload(w) for w in range(1, base.gameweek)),
        )
    }
    version = DEFCON_CANDIDATE_VERSIONS[base.model_version]
    binding = {
        "contract_version": DEFCON_COMPONENT_CONTRACT_VERSION,
        "base_fingerprint": base.fingerprint,
        "declaration_sha256": declaration_sha256,
        "candidate_version": version,
        "input_hashes": hashes,
    }
    augmentation = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prior_minutes = {
        code: sum(row.minutes for row in rows if row.player_code == code) / (base.gameweek - 1)
        for code in sorted(codes)
    }
    return replace(
        base,
        model_version=version,
        expected_points={code: base.expected_points[code] + terms[code] for code in codes},
        augmentation_fingerprint=augmentation,
        diagnostics={
            **dict(base.diagnostics),
            "defcon_component": {
                **binding,
                "rates": rates.document(),
                "terms": {str(code): terms[code] for code in sorted(codes)},
                "prior_minutes": {str(code): prior_minutes[code] for code in sorted(codes)},
                "fixture_counts": {str(code): counts[code] for code in sorted(codes)},
                "unmapped_history": {
                    str(w): list(h.unmapped_elements)
                    for w, h in zip(range(1, base.gameweek), histories, strict=True)
                },
                "development_schema_crosschecks": sum(h.schema_crosschecks for h in histories),
                "excluded_fit_rows": [row for h in histories for row in h.excluded_rows],
                "development_schema_disagreements": [
                    row for h in histories for row in h.schema_disagreements
                ],
                "zero_term_player_codes": sorted(
                    code
                    for code in codes
                    if positions[code] != "GK"
                    and counts[code]
                    and code not in (base.appearance_probability or {})
                ),
            },
        },
    )
