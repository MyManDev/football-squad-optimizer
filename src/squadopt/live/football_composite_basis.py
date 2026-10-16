"""Required immutable composite recipe and source-bound deterministic reprojection.

Source authenticity belongs to the capture/producer. These checks bind retained
bytes, declared clocks and all current inputs, then reproduce the served result.
There is no model fitting, source fetching, polymorphic loading or path access.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast

import pandas as pd

from squadopt.features.football_score_replay import REPLAY_FIT_VERSION as SCORE_REPLAY_FIT_VERSION
from squadopt.live.football_artifact import forecast_digest
from squadopt.live.football_composite_codec import composite_source_bytes, read_composite_source
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.prediction.football import (
    JOINT_ROLE_FLAG_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
from squadopt.prediction.football_capabilities import (
    COMPOSITE_ACTIVE_HEADS,
    COMPOSITE_AVAILABILITY_POLICY,
    COMPOSITE_FEATURE_VERSION,
    COMPOSITE_MODEL_VERSION,
    COMPOSITE_REPROJECTION_VERSION,
)
from squadopt.prediction.football_composite_contract import composite_weekly_chances
from squadopt.prediction.football_composite_core import (
    CompositeFixtureInput,
    CompositeFixtureResult,
    CompositeModels,
    FinalMinuteMarginal,
    compose_fixture,
)
from squadopt.prediction.football_composite_weeks import (
    CompositeWeekInput,
    CompositeWeekInventory,
    CompositeWeeksResult,
    compose_composite_weeks,
)
from squadopt.prediction.football_joint_week_law import (
    JointWeekLaw,
    VerifiedWeekEvidence,
    apply_verified_week_evidence,
    joint_week_law_digest,
    joint_week_marginals,
)
from squadopt.prediction.football_observed_load import (
    ObservedLoadServingModel,
    read_observed_load_serving_result,
)
from squadopt.prediction.football_observed_tactical_serving import (
    ObservedTacticalServingModel,
    read_observed_tactical_serving_model,
)
from squadopt.prediction.football_phase_serving import read_phase_serving_model
from squadopt.prediction.football_score_serving import read_score_serving_model
from squadopt.prediction.football_unit_serving import UNIT_SERVING_VERSION, read_unit_serving_model
from squadopt.prediction.football_unit_strength import UNIT_PHYSICAL_FIT_VERSION

COMPONENT_CONTRACT = "football_composite_components_v1"
RECIPE_VERSION = "football_composite_retained_recipe_v1"
MAX_COMPANION_BYTES = 128 * 1024 * 1024
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MODEL_ROLES = ("load", "unit", "score", "tactical", "phase")
T = TypeVar("T")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Composite source requires a lowercase SHA256 identity.")
    return value


def _clock(value: str) -> datetime:
    if type(value) is not str:
        raise ValueError("Composite source clock requires a timestamp string.")
    clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Composite source clock requires an explicit offset.")
    return clock


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(dict(pairs)) != len(pairs):
        raise ValueError("Composite retained JSON repeats a field.")
    return dict(pairs)


def _fields(value: Any, names: tuple[str, ...]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(names):
        raise ValueError("Composite retained document fields differ.")
    return cast(dict[str, Any], value)


def _document(raw: str, expected: str) -> dict[str, Any]:
    if type(raw) is not str or not 0 < len(raw.encode()) <= MAX_DOCUMENT_BYTES:
        raise ValueError("Composite retained document exceeds its bound.")
    if hashlib.sha256(raw.encode()).hexdigest() != _sha(expected):
        raise ValueError("Composite retained document digest differs.")
    value = json.loads(raw, object_pairs_hook=_object)
    if type(value) is not dict or _canonical(value) != raw:
        raise ValueError("Composite retained document must be a canonical object.")
    return cast(dict[str, Any], value)


def _pack_document(value: Mapping[str, Any]) -> dict[str, str]:
    raw = _canonical(dict(value))
    _document(raw, hashlib.sha256(raw.encode()).hexdigest())
    return {"payload_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def _unpack_document(value: Any) -> dict[str, Any]:
    item = _fields(value, ("payload_json", "sha256"))
    return _document(item["payload_json"], item["sha256"])


def _pack_source(value: object) -> dict[str, str]:
    raw = composite_source_bytes(value)
    return {"payload_json": raw.decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def _unpack_source(value: Any, kind: type[T]) -> T:
    item = _fields(value, ("payload_json", "sha256"))
    if type(item["payload_json"]) is not str:
        raise ValueError("Composite typed source requires retained text.")
    return read_composite_source(
        item["payload_json"].encode(), expected_sha256=item["sha256"], source_type=kind
    )


@dataclass(frozen=True, slots=True)
class CompositeModelAsset:
    role: str
    payload_json: str
    sha256: str


@dataclass(frozen=True)
class CompositeReprojectionResult:
    fixture_rows: pd.DataFrame
    weekly_rows: pd.DataFrame
    fingerprint: str
    fixture_receipts: tuple[dict[str, Any], ...]
    weekly_result: CompositeWeeksResult


@dataclass(frozen=True)
class _State:
    recipe_json: str
    native_forecast_json: str
    native_components_json: str
    flag_forecast_json: str
    inventory: CompositeWeekInventory
    weeks: tuple[CompositeWeekInput, ...]
    fixtures: tuple[CompositeFixtureInput, ...]
    models: CompositeModels
    load: ObservedLoadServingModel
    assets: tuple[CompositeModelAsset, ...]
    baseline_weeks: CompositeWeeksResult
    baseline_fixtures: tuple[CompositeFixtureResult, ...]
    generated_at: str
    decision_at: str


def _models(
    assets: tuple[CompositeModelAsset, ...],
) -> tuple[CompositeModels, ObservedLoadServingModel]:
    if (
        type(assets) is not tuple
        or any(type(a) is not CompositeModelAsset for a in assets)
        or tuple(a.role for a in assets) != MODEL_ROLES
    ):
        raise ValueError("Composite requires each of the five ordered compact model assets.")
    for asset in assets:
        _document(asset.payload_json, asset.sha256)
    load, unit, score, tactical, phase = assets
    result = CompositeModels(
        read_unit_serving_model(unit.payload_json.encode(), expected_sha256=unit.sha256),
        read_score_serving_model(score.payload_json.encode(), expected_sha256=score.sha256),
        read_observed_tactical_serving_model(
            tactical.payload_json.encode(), expected_sha256=tactical.sha256
        ),
        read_phase_serving_model(phase.payload_json.encode(), expected_sha256=phase.sha256),
    )
    if type(result.tactical) is not ObservedTacticalServingModel:
        raise ValueError("Composite requires the concrete compact tactical model.")
    return result, read_observed_load_serving_result(load.payload_json.encode(), sha256=load.sha256)


def _native_envelope(
    envelope: dict[str, Any],
    native: dict[str, Any],
    components: dict[str, Any],
    inventory: CompositeWeekInventory,
    generated_at: str,
) -> None:
    names = (
        "version",
        "calendar_sha256",
        "fit_information_cutoff",
        "gameweeks",
        "joint_policy",
        "native_generated_at",
        "native_history_admission_bound",
        "native_history_bound_policy",
        "native_original_fit_generated_at",
        "native_retrieved_at",
        "original_captured_at",
        "players",
        "source_code",
        "source_component_sha256",
        "source_fingerprint",
        "source_forecast_sha256",
        "source_snapshot_id",
    )
    _fields(envelope, names)
    if (
        envelope["version"] != "captured_native_independent_fixture_product_v1"
        or envelope["joint_policy"]
        != (
            "Canonical Cartesian product of unchanged native seven-state fixture laws; "
            "no fitted cross-fixture dependence or availability scaling."
        )
        or envelope["native_history_bound_policy"]
        != (
            "Existing native eligibility latest kickoff plus three hours, "
            "not a physical final-whistle observation."
        )
        or envelope["calendar_sha256"] != inventory.calendar_sha256
        or envelope["source_component_sha256"] != _digest(components)
        or envelope["source_forecast_sha256"] != _digest(native)
        or envelope["source_fingerprint"] != inventory.source_fingerprint
        or envelope["source_snapshot_id"] != inventory.source_snapshot_id
        or envelope["original_captured_at"] != inventory.captured_at
        or _clock(envelope["fit_information_cutoff"]) > _clock(native["captured_at_utc"])
        or envelope["gameweeks"] != list(inventory.gameweeks)
        or envelope["players"] != [p.player_code for p in inventory.roster]
        or _digest(envelope) != inventory.native_basis_sha256
    ):
        raise ValueError(
            "Composite weekly native reconstruction envelope differs from its originals."
        )
    if not (
        _clock(envelope["native_history_admission_bound"])
        < _clock(envelope["fit_information_cutoff"])
        <= _clock(envelope["native_original_fit_generated_at"])
        <= _clock(envelope["native_retrieved_at"])
        <= _clock(envelope["native_generated_at"])
        <= _clock(generated_at)
    ):
        raise ValueError("Composite native acquisition/generation declarations are inconsistent.")
    if _clock(envelope["native_history_admission_bound"]) != (
        _clock(native["training_latest_kickoff"]) + timedelta(hours=3)
    ):
        raise ValueError("Composite native history admission bound differs from retained history.")
    if type(envelope["source_code"]) is not dict or not envelope["source_code"]:
        raise ValueError("Composite native source implementation receipts are missing.")
    for name, digest in envelope["source_code"].items():
        if type(name) is not str or not name.strip():
            raise ValueError("Composite implementation receipt name is invalid.")
        _sha(digest)


def _bind_duties(
    fixtures: tuple[CompositeFixtureInput, ...], inventory: CompositeWeekInventory
) -> None:
    for context in fixtures:
        for phase in context.phase:
            if (
                phase.duties.snapshot_id != inventory.source_snapshot_id
                or phase.duties.source_fingerprint != inventory.source_fingerprint
                or _clock(phase.duties.captured_at) != _clock(inventory.captured_at)
            ):
                raise ValueError("Composite duties differ from the exact retained capture.")


def _bind_model_targets(models: CompositeModels, inventory: CompositeWeekInventory) -> None:
    if type(models.tactical) is not ObservedTacticalServingModel:
        raise ValueError("Composite requires the concrete compact tactical model.")
    if not inventory.gameweeks:
        raise ValueError("Composite requires a nonempty target gameweek inventory.")
    target = inventory.season, inventory.gameweeks[0]
    if models.unit.metadata.contract_version != UNIT_SERVING_VERSION:
        raise ValueError("Composite requires an explicit target-bound unit serving artifact.")
    if models.unit.metadata.fit_contract_version != UNIT_PHYSICAL_FIT_VERSION:
        raise ValueError("Composite requires the v2 physical unit fit contract.")
    if models.score.metadata.fit_contract != SCORE_REPLAY_FIT_VERSION:
        raise ValueError("Composite requires the v2 replay score fit contract.")
    if models.phase.metadata.fit_contract_version not in (
        "football_phase_duty_fit_v2",
        "football_phase_duty_replay_fit_v2",
    ):
        raise ValueError("Composite requires a v2 phase fit contract.")
    targets = (
        (models.unit.metadata.target_season, models.unit.metadata.target_gameweek),
        (models.score.metadata.target_season, min(models.score.metadata.target_gameweeks)),
        (models.tactical.metadata.target_season, models.tactical.metadata.target_gameweek),
        (models.phase.metadata.target_season, models.phase.metadata.target_gameweek),
    )
    if any(value != target for value in targets):
        raise ValueError("Composite family fit targets must equal its first captured gameweek.")


def _bind_sources(
    native: dict[str, Any],
    components: dict[str, Any],
    flag: dict[str, Any],
    flag_components: dict[str, Any],
    envelope: dict[str, Any],
    inventory: CompositeWeekInventory,
    weeks: tuple[CompositeWeekInput, ...],
    fixtures: tuple[CompositeFixtureInput, ...],
    *,
    fixture_calendar: pd.DataFrame,
    roster_clubs: Mapping[int, int],
    roster_positions: Mapping[int, str],
    deadline_by_gameweek: Mapping[int, str],
    captured_calendar_sha256: str,
    generated_at: str,
    decision_at: str,
) -> None:
    if (
        native.get("model_version") != JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION
        or flag.get("model_version") != JOINT_ROLE_FLAG_MODEL_VERSION
    ):
        raise ValueError("Composite originals require retained native and fitted flag contracts.")
    for forecast, companion in ((native, components), (flag, flag_components)):
        FixtureComponentBasis.from_documents(
            forecast, companion, fixture_calendar=fixture_calendar, roster_clubs=roster_clubs
        )
    for key in (
        "season",
        "gameweek",
        "source_snapshot_id",
        "captured_at_utc",
        "source_fingerprint",
        "training_rows",
        "training_latest_kickoff",
        "archive_hashes",
        "training_selection",
        "role_metadata",
    ):
        if native.get(key) != flag.get(key):
            raise ValueError(
                "Composite original native and flag capture/training identities differ."
            )
    fm = flag["flag_metadata"]
    if (
        fm["native_forecast_fingerprint"] != native["fingerprint"]
        or fm["native_components_fingerprint"] != components["fingerprint"]
    ):
        raise ValueError("Composite retained flags identify another original native forecast.")
    if (
        inventory.season != native["season"]
        or inventory.source_snapshot_id != native["source_snapshot_id"]
        or inventory.source_fingerprint != native["source_fingerprint"]
        or inventory.captured_at != native["captured_at_utc"]
        or inventory.native_components_sha256 != _digest(components)
        or inventory.role_metadata_sha256 != _digest(components["role_metadata"])
        or inventory.captured_eligibility_sha256 != _digest(components["captured_availability"])
        or inventory.first_week_flag_result_sha256 != _digest(flag)
        or inventory.calendar_sha256 != _sha(captured_calendar_sha256)
        or inventory.decision_at != decision_at
        or not _clock(inventory.captured_at) <= _clock(generated_at) <= _clock(decision_at)
        or _clock(fm["decision_at"]) > _clock(generated_at)
    ):
        raise ValueError("Composite inventory differs from the retained source bytes or clocks.")
    declared_roster = {p.player_code: p.club_code for p in inventory.roster}
    positions = {p.player_code: p.position for p in inventory.roster}
    if declared_roster != dict(roster_clubs) or positions != dict(roster_positions):
        raise ValueError("Composite inventory differs from the captured complete roster.")
    availability = {
        r["player_code"]: r["multiplier"]
        for r in components["captured_availability"]["multipliers"]
    }
    if {p.player_code: p.captured_eligibility for p in inventory.roster} != availability:
        raise ValueError("Composite captured eligibility differs from the original declaration.")
    if components["captured_availability"] != flag_components["captured_availability"]:
        raise ValueError("Composite original captured availability declarations differ.")
    deadlines = {d.gameweek: d.deadline_at for d in inventory.deadlines}
    if set(deadlines) != set(inventory.gameweeks) or any(
        _clock(value) != _clock(deadline_by_gameweek[gw]) for gw, value in deadlines.items()
    ):
        raise ValueError("Composite deadlines differ from the captured calendar.")
    calendar = fixture_calendar.loc[fixture_calendar.GW.isin(inventory.gameweeks)]
    expected_calendar = {
        (
            int(r["GW"]),
            int(r["fixture"]),
            _clock(pd.Timestamp(r["kickoff"]).isoformat()),
            int(r["club"]),
            int(r["opponent"]),
        )
        for r in calendar.to_dict(orient="records")
        if int(r["home"]) == 1
    }
    if expected_calendar != {
        (f.gameweek, f.fixture_id, _clock(f.kickoff), f.home_club_code, f.away_club_code)
        for f in inventory.calendar
    }:
        raise ValueError("Composite typed calendar does not cover the exact captured fixtures.")
    _native_envelope(envelope, native, components, inventory, generated_at)
    originals = {(r["GW"], r["fixture"], r["player_code"]): r for r in components["rows"]}
    flag_laws = {r["player_code"]: r for r in fm["weekly_laws"]}
    for row in weeks:
        law = row.native
        nb = row.load_week.native
        # The captured LOAD basis retains original unnormalized atom bytes. The
        # joint-law constructor validates 1e-12 then normalizes once; comparing
        # that derived marginal bitwise with an original float is incorrect.
        for fixture in nb.fixtures:
            original = originals[law.gameweek, fixture.fixture_id, law.player_code]
            probabilities = (
                original["zero_probability"],
                *(
                    original[f"{role}_minute_probability_{b}"]
                    for role in ("start", "cameo")
                    for b in (1, 2, 3)
                ),
            )
            minutes = (
                0.0,
                *(
                    original[f"{role}_minute_value_{b}"]
                    for role in ("start", "cameo")
                    for b in (1, 2, 3)
                ),
            )
            if fixture.probabilities != probabilities or fixture.minutes != minutes:
                raise ValueError(
                    "Composite weekly native atoms differ from original component rows."
                )
        states = tuple(itertools.product(range(7), repeat=len(law.fixtures)))
        product = tuple(
            math.prod(f.probabilities[s] for f, s in zip(nb.fixtures, state, strict=True))
            for state in states
        )
        total = math.fsum(product)
        if (
            law.states != states
            or len(law.probabilities) != len(product)
            or not math.isclose(total, 1, rel_tol=0, abs_tol=1e-12)
            or law.probabilities != tuple(p / total for p in product)
        ):
            raise ValueError(
                "Composite original native joint law differs from its declared product."
            )
        for attribute, key in (
            ("fit_information_cutoff", "fit_information_cutoff"),
            ("history_completed_by", "native_history_admission_bound"),
            ("retrieved_at", "native_retrieved_at"),
            ("native_generated_at", "native_generated_at"),
        ):
            if getattr(nb, attribute, None) != envelope[key]:
                raise ValueError(
                    "Composite LOAD native declaration differs from retained envelope."
                )
        if nb.model_version != native["model_version"] or _clock(
            row.load_week.provenance.generated_at
        ) > _clock(generated_at):
            raise ValueError("Composite LOAD source generation or native model differs.")
        if law.gameweek == native["gameweek"]:
            learned = row.first_week_flag
            declared = flag_laws[law.player_code]
            if (
                learned is None
                or learned.states != states
                or list(learned.probabilities) != declared["probabilities"]
                or [f.fixture_id for f in learned.fixtures] != declared["fixture_ids"]
            ):
                raise ValueError(
                    "Composite first-week probabilities differ from retained fitted flags."
                )
    expected_fixtures = tuple((f.gameweek, f.fixture_id) for f in inventory.calendar)
    if tuple((f.score.gameweek, f.score.fixture_id) for f in fixtures) != expected_fixtures:
        raise ValueError("Composite contexts require every captured fixture in calendar order.")
    _bind_duties(fixtures, inventory)
    for context in fixtures:
        selected = [r for r in components["rows"] if r["fixture"] == context.score.fixture_id]
        if (
            json.loads(context.native_rows_json) != selected
            or context.native_basis_sha256 != inventory.native_components_sha256
            or context.score.native_model_version != native["model_version"]
            or context.final_minutes != ()
            or context.generated_at != generated_at
            or context.score.decision_at != decision_at
        ):
            raise ValueError(
                "Composite fixture context differs from its original native rows/scope."
            )


def _fixture_results(
    contexts: tuple[CompositeFixtureInput, ...],
    models: CompositeModels,
    laws: tuple[JointWeekLaw, ...],
    *,
    previous: tuple[CompositeFixtureResult, ...] = (),
    changed: frozenset[int] | None = None,
) -> tuple[CompositeFixtureResult, ...]:
    marginals: dict[int, list[FinalMinuteMarginal]] = {}
    for law in laws:
        values = joint_week_marginals(law)
        digest = joint_week_law_digest(law)
        for f, probabilities in zip(law.fixtures, values.fixture_probabilities, strict=True):
            marginals.setdefault(f.fixture_id, []).append(
                FinalMinuteMarginal(law.player_code, probabilities, f.minutes, digest)
            )
    results = []
    for index, context in enumerate(contexts):
        fixture = context.score.fixture_id
        if changed is not None and fixture not in changed:
            results.append(previous[index])
        else:
            supplied = tuple(sorted(marginals[fixture], key=lambda p: p.player_code))
            results.append(compose_fixture(replace(context, final_minutes=supplied), models))
    return tuple(results)


def _weekly_rows(
    state: _State, weeks: CompositeWeeksResult, fixtures: tuple[CompositeFixtureResult, ...]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for fixture in fixtures:
        for row in json.loads(fixture.rows_json):
            grouped.setdefault((row["GW"], row["player_code"]), []).append(row)
    originals = {
        (r["gameweek"], r["player_id"]): r for r in json.loads(state.native_forecast_json)["rows"]
    }
    output = []
    for law in weeks.laws:
        key = law.gameweek, law.player_code
        selected = grouped.get(key, [])
        if {r["fixture"] for r in selected} != {f.fixture_id for f in law.fixtures}:
            raise ValueError("Composite fixture outputs lack exact weekly player coverage.")
        row = dict(originals[key])
        row.update(
            expected_points=math.fsum(r["expected_points"] for r in selected),
            appearance_probability=joint_week_marginals(law).weekly_appearance,
            fixture_count=len(selected),
            home_fixture_count=sum(r["home"] for r in selected),
        )
        output.append(row)
    return output


def _asset_receipts(state: _State) -> list[dict[str, str]]:
    original = json.loads(state.flag_forecast_json)
    models = state.models
    if type(models.tactical) is not ObservedTacticalServingModel:
        raise ValueError("Composite tactical asset requires its concrete compact type.")
    fits = (
        state.load.parameters.model_sha256,
        models.unit.metadata.original_fit_sha256,
        models.score.metadata.original_metadata_sha256,
        models.tactical.metadata.original_metadata_sha256,
        models.phase.metadata.original_metadata_sha256,
    )
    return [
        dict(
            role="flags",
            kind="retained_flag_result",
            sha256=_digest(original),
            fit_sha256=original["flag_metadata"]["model_sha256"],
        ),
        *(
            dict(role=a.role, kind="compact_model", sha256=a.sha256, fit_sha256=h)
            for a, h in zip(state.assets, fits, strict=True)
        ),
    ]


def _render(state: _State) -> tuple[dict[str, Any], dict[str, Any]]:
    served = json.loads(state.native_forecast_json)
    companion = json.loads(state.native_components_json)
    weekly = _weekly_rows(state, state.baseline_weeks, state.baseline_fixtures)
    receipts = [asdict(r.receipt) for r in state.baseline_fixtures]
    metadata = dict(
        version=COMPOSITE_REPROJECTION_VERSION,
        active_heads=list(COMPOSITE_ACTIVE_HEADS),
        availability_application=COMPOSITE_AVAILABILITY_POLICY,
        model_artifacts=_asset_receipts(state),
        basis_sha256=hashlib.sha256(state.recipe_json.encode()).hexdigest(),
        fixture_receipts_sha256=_digest(receipts),
        generated_at=state.generated_at,
        decision_at=state.decision_at,
        weekly_laws=[
            dict(
                gameweek=law.gameweek,
                player_code=law.player_code,
                sha256=joint_week_law_digest(law),
                appearance_probability=joint_week_marginals(law).weekly_appearance,
                fixture_ids=[f.fixture_id for f in law.fixtures],
            )
            for law in state.baseline_weeks.laws
        ],
    )
    for document in (served, companion):
        document.pop("fingerprint", None)
        document.pop("flag_metadata", None)
        document.update(
            model_version=COMPOSITE_MODEL_VERSION,
            feature_contract_version=COMPOSITE_FEATURE_VERSION,
            availability_application=COMPOSITE_AVAILABILITY_POLICY,
            composite_metadata=metadata,
        )
    served["rows"] = weekly
    served["fingerprint"] = forecast_digest(served)
    companion.update(
        contract_version=COMPONENT_CONTRACT,
        forecast_fingerprint=served["fingerprint"],
        rows=[r for f in state.baseline_fixtures for r in json.loads(f.rows_json)],
        recipe=json.loads(state.recipe_json),
        fixture_receipts=receipts,
        weekly_result=asdict(state.baseline_weeks),
    )
    companion["captured_availability"] = {
        **companion["captured_availability"],
        "application": COMPOSITE_AVAILABILITY_POLICY,
    }
    companion["fingerprint"] = forecast_digest(companion)
    composite_weekly_chances(served)
    if len(_canonical(companion).encode()) > MAX_COMPANION_BYTES:
        raise ValueError("Composite companion exceeds its total byte bound.")
    return served, companion


def _restore_recipe(
    recipe: dict[str, Any],
    *,
    fixture_calendar: pd.DataFrame,
    roster_clubs: Mapping[int, int],
    roster_positions: Mapping[int, str],
    deadline_by_gameweek: Mapping[int, str],
    captured_calendar_sha256: str,
) -> _State:
    _fields(
        recipe,
        (
            "version",
            "native_forecast",
            "native_components",
            "flag_forecast",
            "flag_components",
            "native_basis_document",
            "models",
            "inventory",
            "weeks",
            "fixtures",
            "generated_at",
            "decision_at",
        ),
    )
    if recipe["version"] != RECIPE_VERSION:
        raise ValueError("Composite retained recipe version differs.")
    native, components, flag, flag_components, envelope = (
        _unpack_document(recipe[key])
        for key in (
            "native_forecast",
            "native_components",
            "flag_forecast",
            "flag_components",
            "native_basis_document",
        )
    )
    if type(recipe["models"]) is not list or len(recipe["models"]) != 5:
        raise ValueError("Composite compact model inventory is incomplete.")
    assets = tuple(
        CompositeModelAsset(**_fields(value, ("role", "payload_json", "sha256")))
        for value in recipe["models"]
    )
    models, load = _models(assets)
    inventory = _unpack_source(recipe["inventory"], CompositeWeekInventory)
    _bind_model_targets(models, inventory)
    if (
        type(recipe["weeks"]) is not list
        or not 0 < len(recipe["weeks"]) <= 10000
        or type(recipe["fixtures"]) is not list
        or not 0 < len(recipe["fixtures"]) <= 1140
    ):
        raise ValueError("Composite source population exceeds its bounds.")
    weeks = tuple(_unpack_source(value, CompositeWeekInput) for value in recipe["weeks"])
    fixtures = tuple(_unpack_source(value, CompositeFixtureInput) for value in recipe["fixtures"])
    _bind_sources(
        native,
        components,
        flag,
        flag_components,
        envelope,
        inventory,
        weeks,
        fixtures,
        fixture_calendar=fixture_calendar,
        roster_clubs=roster_clubs,
        roster_positions=roster_positions,
        deadline_by_gameweek=deadline_by_gameweek,
        captured_calendar_sha256=captured_calendar_sha256,
        generated_at=recipe["generated_at"],
        decision_at=recipe["decision_at"],
    )
    baseline = compose_composite_weeks(
        weeks, load, inventory=inventory, first_gameweek=inventory.gameweeks[0]
    )
    results = _fixture_results(fixtures, models, baseline.laws)
    return _State(
        _canonical(recipe),
        _canonical(native),
        _canonical(components),
        _canonical(flag),
        inventory,
        weeks,
        fixtures,
        models,
        load,
        assets,
        baseline,
        results,
        recipe["generated_at"],
        recipe["decision_at"],
    )


def build_composite_documents(
    *,
    native_forecast: Mapping[str, Any],
    native_components: Mapping[str, Any],
    flag_forecast: Mapping[str, Any],
    flag_components: Mapping[str, Any],
    native_basis_document: Mapping[str, Any],
    model_assets: tuple[CompositeModelAsset, ...],
    inventory: CompositeWeekInventory,
    weeks: tuple[CompositeWeekInput, ...],
    fixtures: tuple[CompositeFixtureInput, ...],
    fixture_calendar: pd.DataFrame,
    roster_clubs: Mapping[int, int],
    roster_positions: Mapping[int, str],
    deadline_by_gameweek: Mapping[int, str],
    captured_calendar_sha256: str,
    generated_at: str,
    decision_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build both required documents from immutable already-acquired source values."""
    recipe = dict(
        version=RECIPE_VERSION,
        native_forecast=_pack_document(native_forecast),
        native_components=_pack_document(native_components),
        flag_forecast=_pack_document(flag_forecast),
        flag_components=_pack_document(flag_components),
        native_basis_document=_pack_document(native_basis_document),
        models=[asdict(a) for a in model_assets],
        inventory=_pack_source(inventory),
        weeks=[_pack_source(w) for w in weeks],
        fixtures=[_pack_source(f) for f in fixtures],
        generated_at=generated_at,
        decision_at=decision_at,
    )
    if len(_canonical(recipe).encode()) > MAX_COMPANION_BYTES:
        raise ValueError("Composite source recipe exceeds its total byte bound.")
    return _render(
        _restore_recipe(
            recipe,
            fixture_calendar=fixture_calendar,
            roster_clubs=roster_clubs,
            roster_positions=roster_positions,
            deadline_by_gameweek=deadline_by_gameweek,
            captured_calendar_sha256=captured_calendar_sha256,
        )
    )


@dataclass(frozen=True, slots=True)
class CompositeComponentBasis(FixtureComponentBasis):
    _state: _State

    @classmethod
    def from_documents(
        cls,
        served: Mapping[str, object],
        companion: Mapping[str, object],
        *,
        fixture_calendar: pd.DataFrame,
        roster_clubs: Mapping[int, int],
        roster_positions: Mapping[int, str] | None = None,
        deadline_by_gameweek: Mapping[int, str] | None = None,
        captured_calendar_sha256: str | None = None,
    ) -> CompositeComponentBasis:
        if (
            roster_positions is None
            or deadline_by_gameweek is None
            or captured_calendar_sha256 is None
        ):
            raise ValueError(
                "Composite basis requires verified captured positions, deadlines "
                "and raw calendar hash."
            )
        for document in (served, companion):
            if document.get("fingerprint") != forecast_digest(dict(document)):
                raise ValueError("Composite document fingerprint differs.")
        if companion.get("contract_version") != COMPONENT_CONTRACT or companion.get(
            "forecast_fingerprint"
        ) != served.get("fingerprint"):
            raise ValueError("Composite companion is absent or belongs to another forecast.")
        raw = _canonical(dict(companion))
        if len(raw.encode()) > MAX_COMPANION_BYTES:
            raise ValueError("Composite companion exceeds its total byte bound.")
        composite_weekly_chances(served)
        state = _restore_recipe(
            cast(dict[str, Any], companion["recipe"]),
            fixture_calendar=fixture_calendar,
            roster_clubs=roster_clubs,
            roster_positions=roster_positions,
            deadline_by_gameweek=deadline_by_gameweek,
            captured_calendar_sha256=captured_calendar_sha256,
        )
        expected_served, expected_companion = _render(state)
        if _canonical(dict(served)) != _canonical(expected_served) or raw != _canonical(
            expected_companion
        ):
            raise ValueError(
                "Composite retained recipe does not reproduce every served row and receipt."
            )
        return cls(_canonical(dict(served)), raw, state)

    @property
    def fixture_rows(self) -> pd.DataFrame:
        rows = pd.DataFrame(
            [r for f in self._state.baseline_fixtures for r in json.loads(f.rows_json)]
        )
        rows.attrs.update(season=self._state.inventory.season, joint_role=True, composite=True)
        return rows

    @property
    def weekly_rows(self) -> pd.DataFrame:
        return pd.DataFrame(cast(list[dict[str, Any]], self.served["rows"]))

    def _evidence_laws(
        self, evidence: tuple[VerifiedWeekEvidence, ...]
    ) -> tuple[JointWeekLaw, ...]:
        if type(evidence) is not tuple or any(
            type(e) is not VerifiedWeekEvidence for e in evidence
        ):
            raise ValueError("Composite reprojection needs immutable verified evidence.")
        if not evidence:
            return self._state.baseline_weeks.laws
        if any(
            type(e.evidence_id) is not str
            or type(e.player_code) is not int
            or type(e.gameweek) is not int
            for e in evidence
        ):
            raise ValueError("Composite evidence requires strict identity fields.")
        codes = {p.player_code for p in self._state.inventory.roster}
        first = self._state.inventory.gameweeks[0]
        if len({e.evidence_id for e in evidence}) != len(evidence) or any(
            e.player_code not in codes or e.gameweek != first for e in evidence
        ):
            raise ValueError(
                "Composite evidence repeats identity or leaves the first-week population."
            )
        by_player = {p: tuple(e for e in evidence if e.player_code == p) for p in codes}
        return tuple(
            apply_verified_week_evidence(
                law,
                by_player[law.player_code] if law.gameweek == first else (),
                first_gameweek=first,
            )
            for law in self._state.baseline_weeks.laws
        )

    def validate_evidence(self, evidence: tuple[VerifiedWeekEvidence, ...]) -> None:
        """Check evidence support on retained pre-evidence laws without calling any model."""
        self._evidence_laws(evidence)

    def recompose(
        self, evidence: tuple[VerifiedWeekEvidence, ...] = ()
    ) -> CompositeReprojectionResult:
        """Always restart from the original retained laws; LOAD and fitting never rerun."""
        laws = self._evidence_laws(evidence)
        state = self._state
        if not evidence:
            return CompositeReprojectionResult(
                self.fixture_rows,
                self.weekly_rows,
                cast(str, self.served["fingerprint"]),
                tuple(asdict(f.receipt) for f in state.baseline_fixtures),
                state.baseline_weeks,
            )
        changed = frozenset(
            f.fixture_id
            for original, law in zip(state.baseline_weeks.laws, laws, strict=True)
            if original != law
            for f in law.fixtures
        )
        weeks = replace(
            state.baseline_weeks,
            laws=laws,
            receipts=tuple(
                replace(receipt, final_sha256=joint_week_law_digest(law))
                for receipt, law in zip(state.baseline_weeks.receipts, laws, strict=True)
            ),
            evidence_sha256=_digest(tuple(asdict(e) for e in evidence)),
        )
        fixtures = _fixture_results(
            state.fixtures, state.models, laws, previous=state.baseline_fixtures, changed=changed
        )
        rows = [r for f in fixtures for r in json.loads(f.rows_json)]
        weekly = _weekly_rows(state, weeks, fixtures)
        receipts = tuple(asdict(f.receipt) for f in fixtures)
        fingerprint = _digest(
            dict(
                basis_sha256=hashlib.sha256(state.recipe_json.encode()).hexdigest(),
                evidence=[asdict(e) for e in evidence],
                weekly_rows=weekly,
                fixture_rows=rows,
                fixture_receipts=receipts,
                weekly_result=asdict(weeks),
            )
        )
        frame = pd.DataFrame(rows)
        frame.attrs.update(season=state.inventory.season, joint_role=True, composite=True)
        return CompositeReprojectionResult(
            frame, pd.DataFrame(weekly), fingerprint, receipts, weeks
        )
