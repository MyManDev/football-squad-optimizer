"""Retained-recipe boundaries and independent cached-law reprojection checks.

The small fixture executor below is an explicit orchestration test double. The
real physical allocator and all five strict model readers have separate tests.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_composite_weeks import population, serving

from squadopt.features.football_load_inputs import native_joint_law_digest
from squadopt.live import football_composite_basis as module
from squadopt.live.football_artifact import forecast_digest
from squadopt.prediction.football_capabilities import (
    COMPOSITE_ACTIVE_HEADS,
    COMPOSITE_AVAILABILITY_POLICY,
    COMPOSITE_FEATURE_VERSION,
    COMPOSITE_MODEL_VERSION,
    COMPOSITE_REPROJECTION_VERSION,
)
from squadopt.prediction.football_composite_core import CompositeFixtureResult, CompositeReceipt
from squadopt.prediction.football_composite_weeks import (
    compose_composite_weeks,
    composite_native_sources,
)
from squadopt.prediction.football_joint_week_law import (
    VerifiedWeekEvidence,
    joint_week_marginals,
    make_joint_week_law,
    model_week_law,
)


def canonical(value):
    return module._canonical(value)


def digest(value):
    return module._digest(value)


@pytest.mark.parametrize(
    "raw",
    ['{"a":1,"a":2}', '{"a": NaN}', "[1]", '{ "a":1}', '{"a":Infinity}'],
)
def test_retained_json_rejects_duplicates_nonfinite_noncanonical_and_wrong_shape(raw):
    with pytest.raises(ValueError):
        module._document(raw, module.hashlib.sha256(raw.encode()).hexdigest())


def test_retained_json_bound_and_external_digest_are_checked_before_decode(monkeypatch):
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 3)
    with pytest.raises(ValueError, match="bound"):
        module._document('{"a":1}', "1" * 64)
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(ValueError, match="digest"):
        module._document('{"a":1}', "1" * 64)
    raw = '{"a":1}'
    assert module._document(raw, module.hashlib.sha256(raw.encode()).hexdigest()) == {"a": 1}


def test_code_selected_source_roundtrip_and_redigested_undeclared_fields():
    inventory, _ = population()
    packed = module._pack_source(inventory)
    assert module._unpack_source(packed, type(inventory)) == inventory
    payload = module.json.loads(packed["payload_json"])
    payload["factory"] = "arbitrary.python.path"
    with pytest.raises(ValueError):
        module._unpack_source(module._pack_document(payload), type(inventory))


@pytest.mark.parametrize(
    "roles",
    [
        (),
        ("load",),
        ("unit", "load", "score", "tactical", "phase"),
        ("load", "unit", "score", "tactical", "tactical"),
    ],
)
def test_missing_duplicate_or_reordered_model_assets_refuse_before_any_reader(roles):
    with pytest.raises(ValueError, match="five ordered"):
        module._models(tuple(module.CompositeModelAsset(r, "{}", digest({})) for r in roles))


@pytest.fixture(scope="module")
def real_assets():
    from tests.unit.test_football_composite_core import models as core_models
    from tests.unit.test_football_observed_tactical import fit, observation
    from tests.unit.test_football_score_replay import fit as score_fit
    from tests.unit.test_football_score_replay import replay
    from tests.unit.test_football_score_state import observation as score_observation

    from squadopt.prediction.football_observed_tactical_serving import (
        export_observed_tactical_serving_model,
    )
    from squadopt.prediction.football_score_serving import export_score_serving_model

    models = core_models.__wrapped__()
    values = {
        "load": canonical(asdict(serving().parameters)),
        "unit": canonical(asdict(models.unit.metadata)),
        "score": export_score_serving_model(
            score_fit(tuple(replay(score_observation(i)) for i in range(3)))
        ).decode(),
        "phase": canonical(asdict(models.phase.metadata)),
        "tactical": export_observed_tactical_serving_model(
            fit(tuple(observation(i) for i in range(3)))
        ).decode(),
    }
    return tuple(
        module.CompositeModelAsset(role, raw, module.hashlib.sha256(raw.encode()).hexdigest())
        for role in module.MODEL_ROLES
        for raw in (values[role],)
    )


def test_each_real_frozen_model_is_restored_and_tactical_type_is_concrete(real_assets):
    models, load = module._models(real_assets)
    assert type(models.tactical) is module.ObservedTacticalServingModel
    assert load.result_sha256 == real_assets[0].sha256
    for role, model in (
        ("unit", models.unit),
        ("score", models.score),
        ("tactical", models.tactical),
        ("phase", models.phase),
    ):
        assert model.artifact_sha256 == next(a.sha256 for a in real_assets if a.role == role)


@pytest.mark.parametrize("role", module.MODEL_ROLES)
def test_redigested_compact_model_fields_are_still_family_validated(real_assets, role):
    changed = []
    for asset in real_assets:
        if asset.role == role:
            value = module.json.loads(asset.payload_json)
            value["undeclared_implementation"] = "not permitted"
            raw = canonical(value)
            asset = replace(asset, payload_json=raw, sha256=digest(value))
        changed.append(asset)
    with pytest.raises(ValueError):
        module._models(tuple(changed))


def test_protocol_compatible_tactical_fake_is_refused(real_assets, monkeypatch):
    from tests.unit.test_football_composite_core import RecipientOracle

    monkeypatch.setattr(
        module, "read_observed_tactical_serving_model", lambda *a, **k: RecipientOracle()
    )
    with pytest.raises(ValueError, match="concrete compact tactical"):
        module._models(real_assets)


@pytest.mark.parametrize("field", ["snapshot_id", "source_fingerprint", "captured_at"])
def test_each_side_duty_capture_must_match_composite_inventory(field):
    from tests.unit.test_football_composite_core import case

    inventory, _ = population()
    x = case()
    values = dict(
        snapshot_id=inventory.source_snapshot_id,
        source_fingerprint=inventory.source_fingerprint,
        captured_at=inventory.captured_at,
    )
    phases = tuple(replace(p, duties=replace(p.duties, **values)) for p in x.phase)
    module._bind_duties((replace(x, phase=phases),), inventory)
    for side in range(2):
        bad = {
            "snapshot_id": "another-real-capture",
            "source_fingerprint": "e" * 64,
            "captured_at": "2026-10-15T01:00:00Z",
        }[field]
        changed = list(phases)
        changed[side] = replace(phases[side], duties=replace(phases[side].duties, **{field: bad}))
        with pytest.raises(ValueError, match="exact retained capture"):
            module._bind_duties((replace(x, phase=tuple(changed)),), inventory)


def test_empty_restored_gameweeks_refuse_before_model_target_indexing(real_assets):
    inventory, _ = population()
    empty = replace(inventory, gameweeks=())
    restored = module._unpack_source(module._pack_source(empty), type(empty))
    models, _ = module._models(real_assets)
    with pytest.raises(ValueError, match="nonempty target gameweek"):
        module._bind_model_targets(models, restored)


@pytest.mark.parametrize("family", ["unit", "score", "tactical", "phase"])
@pytest.mark.parametrize("mismatch", ["season", "week"])
def test_compact_family_target_is_bound_to_first_week(real_assets, family, mismatch):
    inventory, _ = population()

    def assets_with_target(changed_family=None):
        assets = []
        for asset in real_assets:
            if asset.role not in ("unit", "score", "tactical", "phase"):
                assets.append(asset)
                continue
            value = module.json.loads(asset.payload_json)
            value["target_season"] = inventory.season
            field = "target_gameweeks" if asset.role == "score" else "target_gameweek"
            week = inventory.gameweeks[0]
            if asset.role == changed_family:
                if mismatch == "season":
                    value["target_season"] = "2027-28"
                else:
                    week -= 1
            value[field] = [week] if asset.role == "score" else week
            raw = canonical(value)
            assets.append(replace(asset, payload_json=raw, sha256=digest(value)))
        return tuple(assets)

    models, _ = module._models(assets_with_target())
    module._bind_model_targets(models, inventory)
    models, _ = module._models(assets_with_target(family))
    with pytest.raises(ValueError, match="first captured gameweek"):
        module._bind_model_targets(models, inventory)


def changed_asset(assets, role, **changes):
    result = []
    for asset in assets:
        if asset.role == role:
            value = module.json.loads(asset.payload_json)
            value.update(changes)
            asset = replace(asset, payload_json=canonical(value), sha256=digest(value))
        result.append(asset)
    return tuple(result)


@pytest.fixture
def boundary_case(real_assets, monkeypatch):
    """Public recipe path with real codecs, family readers and source/target guards.

    Only the previously validated original component reader and expensive physical
    fixture executor are doubles. The recipe restore, weekly composition, source
    binding, duty binding and model target/fit binding run unchanged.
    """
    from tests.unit.test_football_composite_core import case

    inventory, source_weeks = population()
    inventory = replace(
        inventory,
        gameweeks=(7,),
        calendar=inventory.calendar[:1],
        deadlines=inventory.deadlines[:1],
    )
    source_weeks = tuple(row for row in source_weeks if row.native.gameweek == 7)
    normalized_weeks = []
    for row in source_weeks:
        basis = row.load_week.native
        fixtures = tuple(
            replace(f, minutes=tuple(float(v) for v in f.minutes)) for f in basis.fixtures
        )
        normalized_weeks.append(
            replace(
                row,
                load_week=replace(
                    row.load_week,
                    native=replace(
                        basis,
                        fixtures=fixtures,
                        law_sha256=native_joint_law_digest(
                            fixtures, basis.states, basis.probabilities
                        ),
                    ),
                ),
            )
        )
    source_weeks = tuple(normalized_weeks)
    native = dict(
        season=inventory.season,
        gameweek=7,
        source_snapshot_id=inventory.source_snapshot_id,
        source_fingerprint=inventory.source_fingerprint,
        captured_at_utc=inventory.captured_at,
        training_latest_kickoff="2026-10-14T20:00:00Z",
        model_version=module.JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
        rows=[
            dict(
                gameweek=7, player_id=row.native.player_code, fixture_count=len(row.native.fixtures)
            )
            for row in source_weeks
        ],
    )
    native["fingerprint"] = forecast_digest(native)
    rows = []
    for row in source_weeks:
        for fixture in row.load_week.native.fixtures:
            values = dict(GW=7, fixture=fixture.fixture_id, player_code=row.native.player_code)
            values["zero_probability"] = fixture.probabilities[0]
            for role, offset in (("start", 0), ("cameo", 3)):
                for index in (1, 2, 3):
                    values[f"{role}_minute_probability_{index}"] = fixture.probabilities[
                        offset + index
                    ]
                    values[f"{role}_minute_value_{index}"] = fixture.minutes[offset + index]
            rows.append(values)
    components = dict(
        rows=rows,
        role_metadata={"synthetic_orchestration_fixture": True},
        captured_availability={
            "multipliers": [
                dict(player_code=p.player_code, multiplier=p.captured_eligibility)
                for p in inventory.roster
            ]
        },
    )
    components["fingerprint"] = forecast_digest(components)
    flag = dict(
        native,
        model_version=module.JOINT_ROLE_FLAG_MODEL_VERSION,
        flag_metadata=dict(
            native_forecast_fingerprint=native["fingerprint"],
            native_components_fingerprint=components["fingerprint"],
            model_sha256="a" * 64,
            decision_at=inventory.decision_at,
            weekly_laws=[
                dict(
                    player_code=row.native.player_code,
                    fixture_ids=[f.fixture_id for f in row.native.fixtures],
                    probabilities=list(row.first_week_flag.probabilities),
                )
                for row in source_weeks
            ],
        ),
    )
    flag["fingerprint"] = forecast_digest(flag)
    envelope = envelope_case()[0]
    envelope.update(
        gameweeks=[7],
        source_component_sha256=digest(components),
        source_forecast_sha256=digest(native),
    )
    inventory = replace(
        inventory,
        native_components_sha256=digest(components),
        role_metadata_sha256=digest(components["role_metadata"]),
        captured_eligibility_sha256=digest(components["captured_availability"]),
        first_week_flag_result_sha256=digest(flag),
        native_basis_sha256=digest(envelope),
    )
    weeks = []
    for row in source_weeks:
        old = row.load_week.native
        law = make_joint_week_law(
            season=inventory.season,
            gameweek=7,
            player_code=row.native.player_code,
            position=row.native.position,
            fixtures=old.fixtures,
            states=old.states,
            probabilities=old.probabilities,
            role_metadata_sha256=inventory.role_metadata_sha256,
            sources=composite_native_sources(inventory),
        )
        learned = model_week_law(
            law,
            law.states,
            row.first_week_flag.probabilities,
            kind="flag",
            sources=(("retained_flag_result", inventory.first_week_flag_result_sha256),),
        )
        weeks.append(
            replace(
                row,
                native=law,
                first_week_flag=learned,
                captured_eligibility_source_sha256=inventory.captured_eligibility_sha256,
                load_week=replace(
                    row.load_week,
                    native=replace(
                        old,
                        basis_sha256=inventory.native_basis_sha256,
                        model_version=native["model_version"],
                        native_generated_at=envelope["native_generated_at"],
                    ),
                    provenance=replace(
                        row.load_week.provenance, source_hashes=composite_native_sources(inventory)
                    ),
                ),
            )
        )
    context = case()
    context = replace(
        context,
        native_rows_json=canonical(rows),
        native_basis_sha256=inventory.native_components_sha256,
        score=replace(context.score, gameweek=7, fixture_id=100, decision_at=inventory.decision_at),
        final_minutes=(),
        phase=tuple(
            replace(
                phase,
                duties=replace(
                    phase.duties,
                    snapshot_id=inventory.source_snapshot_id,
                    source_fingerprint=inventory.source_fingerprint,
                    captured_at=inventory.captured_at,
                ),
            )
            for phase in context.phase
        ),
        generated_at=inventory.decision_at,
    )
    assets = real_assets
    for family in ("unit", "score", "tactical", "phase"):
        field = "target_gameweeks" if family == "score" else "target_gameweek"
        assets = changed_asset(assets, family, **{field: [7] if family == "score" else 7})
    monkeypatch.setattr(module.FixtureComponentBasis, "from_documents", lambda *a, **k: None)
    monkeypatch.setattr(module, "compose_fixture", executor)
    return dict(
        native_forecast=native,
        native_components=components,
        flag_forecast=flag,
        flag_components=deepcopy(components),
        native_basis_document=envelope,
        model_assets=assets,
        inventory=inventory,
        weeks=tuple(weeks),
        fixtures=(context,),
        fixture_calendar=pd.DataFrame(
            [
                dict(
                    GW=7,
                    fixture=100,
                    kickoff=inventory.calendar[0].kickoff,
                    club=10,
                    opponent=20,
                    home=1,
                )
            ]
        ),
        roster_clubs={p.player_code: p.club_code for p in inventory.roster},
        roster_positions={p.player_code: p.position for p in inventory.roster},
        deadline_by_gameweek={7: inventory.deadlines[0].deadline_at},
        captured_calendar_sha256=inventory.calendar_sha256,
        generated_at=inventory.decision_at,
        decision_at=inventory.decision_at,
    )


def public_boundary(entry, source, **changes):
    if entry == "build":
        return module.build_composite_documents(**dict(source, **changes))
    served, companion = module.build_composite_documents(**source)
    recipe = companion["recipe"]
    for name, value in changes.items():
        if name == "model_assets":
            recipe["models"] = [asdict(asset) for asset in value]
        elif name == "fixtures":
            recipe["fixtures"] = [module._pack_source(context) for context in value]
        else:
            raise AssertionError("Undeclared test mutation")
    companion["fingerprint"] = forecast_digest(companion)
    return module.CompositeComponentBasis.from_documents(
        served,
        companion,
        **{
            key: source[key]
            for key in (
                "fixture_calendar",
                "roster_clubs",
                "roster_positions",
                "deadline_by_gameweek",
                "captured_calendar_sha256",
            )
        },
    )


@pytest.mark.parametrize("entry", ["build", "read"])
def test_public_recipe_accepts_current_fit_contracts(boundary_case, entry):
    assert public_boundary(entry, boundary_case) is not None


@pytest.mark.parametrize("entry", ["build", "read"])
@pytest.mark.parametrize("family", ["unit", "score", "tactical", "phase"])
def test_public_recipe_calls_family_target_binding(boundary_case, entry, family):
    field = "target_gameweeks" if family == "score" else "target_gameweek"
    assets = changed_asset(
        boundary_case["model_assets"], family, **{field: [6] if family == "score" else 6}
    )
    with pytest.raises(
        ValueError, match=r"^Composite family fit targets must equal its first captured gameweek\.$"
    ):
        public_boundary(entry, boundary_case, model_assets=assets)


@pytest.mark.parametrize("entry", ["build", "read"])
@pytest.mark.parametrize(
    "family,field,contract,reason",
    [
        (
            "unit",
            "fit_contract_version",
            "football_unit_public_replay_physical_duration_fit_v1",
            "v2 physical unit",
        ),
        ("score", "fit_contract", "football_score_state_fit_v1", "v2 replay score"),
        ("score", "fit_contract", "football_score_public_replay_fit_v1", "v2 replay score"),
        ("phase", "fit_contract_version", "football_phase_duty_fit_v1", "v2 phase"),
        ("phase", "fit_contract_version", "football_phase_duty_replay_fit_v1", "v2 phase"),
    ],
)
def test_public_recipe_refuses_legacy_fits_standalone_readers_still_accept(
    boundary_case, entry, family, field, contract, reason
):
    assets = changed_asset(boundary_case["model_assets"], family, **{field: contract})
    models, _ = module._models(assets)
    assert getattr(getattr(models, family).metadata, field) == contract
    with pytest.raises(ValueError, match=rf"^Composite requires (the|a) {reason} fit contract\.$"):
        public_boundary(entry, boundary_case, model_assets=assets)


@pytest.mark.parametrize("entry", ["build", "read"])
@pytest.mark.parametrize("field", ["snapshot_id", "source_fingerprint", "captured_at"])
@pytest.mark.parametrize("side", [0, 1])
def test_public_recipe_calls_exact_duty_capture_binding(boundary_case, entry, field, side):
    context = boundary_case["fixtures"][0]
    phases = list(context.phase)
    bad = {
        "snapshot_id": "another-capture",
        "source_fingerprint": "e" * 64,
        "captured_at": "2026-10-15T01:00:00Z",
    }[field]
    phases[side] = replace(phases[side], duties=replace(phases[side].duties, **{field: bad}))
    with pytest.raises(
        ValueError, match=r"^Composite duties differ from the exact retained capture\.$"
    ):
        public_boundary(entry, boundary_case, fixtures=(replace(context, phase=tuple(phases)),))


def envelope_case():
    inventory, _ = population()
    native = {
        "captured_at_utc": inventory.captured_at,
        "training_latest_kickoff": "2026-10-14T20:00:00Z",
    }
    components = {"retained": "original"}
    envelope = dict(
        version="captured_native_independent_fixture_product_v1",
        calendar_sha256=inventory.calendar_sha256,
        fit_information_cutoff=inventory.captured_at,
        gameweeks=list(inventory.gameweeks),
        joint_policy=(
            "Canonical Cartesian product of unchanged native seven-state fixture laws; "
            "no fitted cross-fixture dependence or availability scaling."
        ),
        native_generated_at="2026-10-16T10:00:00Z",
        native_history_admission_bound="2026-10-14T23:00:00Z",
        native_history_bound_policy=(
            "Existing native eligibility latest kickoff plus three hours, "
            "not a physical final-whistle observation."
        ),
        native_original_fit_generated_at="2026-10-16T08:00:00Z",
        native_retrieved_at="2026-10-16T09:00:00Z",
        original_captured_at=inventory.captured_at,
        players=[p.player_code for p in inventory.roster],
        source_code={"native/source.py": "a" * 64},
        source_component_sha256=digest(components),
        source_forecast_sha256=digest(native),
        source_fingerprint=inventory.source_fingerprint,
        source_snapshot_id=inventory.source_snapshot_id,
    )
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    return envelope, native, components, inventory


def test_native_envelope_binds_declared_integrity_and_clock_order_only():
    envelope, native, components, inventory = envelope_case()
    module._native_envelope(envelope, native, components, inventory, inventory.decision_at)
    # These are declared implementation receipts, never dynamically opened paths.
    envelope["source_code"] = {"a/receipt/that/is/not/opened.py": "f" * 64}
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    module._native_envelope(envelope, native, components, inventory, inventory.decision_at)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_component_sha256", "b" * 64),
        ("source_forecast_sha256", "b" * 64),
        ("source_snapshot_id", "another-capture"),
        ("calendar_sha256", "b" * 64),
        ("players", [42]),
        ("gameweeks", [7]),
        ("joint_policy", "invented dependence"),
        ("native_history_bound_policy", "physical completion observed"),
        ("native_original_fit_generated_at", "2026-10-14T08:00:00Z"),
        ("native_retrieved_at", "2026-10-16T11:00:00Z"),
        ("native_generated_at", "2026-10-17T10:00:00Z"),
        ("native_history_admission_bound", "2026-10-14T22:59:00Z"),
        ("source_code", {}),
        ("source_code", {"native.py": "bad"}),
    ],
)
def test_redigested_native_envelope_cannot_change_original_identity_or_clock(field, value):
    envelope, native, components, inventory = envelope_case()
    envelope[field] = value
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    with pytest.raises(ValueError):
        module._native_envelope(envelope, native, components, inventory, inventory.decision_at)


def receipt(context, rows, marginal_hashes=()):
    return CompositeReceipt(
        "test_orchestration_only",
        digest({}),
        "1" * 64,
        "2" * 64,
        "3" * 64,
        marginal_hashes,
        "2026-10-16T12:00:00Z",
        "2026-10-16T12:00:00Z",
        (),
        (),
        False,
        module.hashlib.sha256(rows.encode()).hexdigest(),
    )


def executor(context, models):
    """Independent nonlinear output oracle, not a fitted-family implementation."""
    rows = []
    for marginal in context.final_minutes:
        p = marginal.probabilities
        minutes = marginal.minutes
        q = sum(p[1:])
        cs = sum(
            prob * module.math.exp(-2 * minute / 100)
            for prob, minute in zip(p, minutes, strict=True)
            if minute >= 60
        )
        rows.append(
            dict(
                GW=context.score.gameweek,
                fixture=context.score.fixture_id,
                player_code=marginal.player_code,
                home=1,
                expected_points=q + 4 * cs,
                appearance_probability=q,
                clean_sheet_probability=cs,
            )
        )
    raw = canonical(rows)
    return CompositeFixtureResult(
        raw,
        receipt(
            context,
            raw,
            tuple((m.player_code, m.final_week_law_sha256) for m in context.final_minutes),
        ),
    )


@pytest.fixture
def cached_basis(monkeypatch):
    inventory, inputs = population()
    weeks = compose_composite_weeks(inputs, serving(), inventory=inventory, first_gameweek=7)

    # Simple frozen-shape contexts for orchestration. No source-reader bypass is
    # represented as real source validation or a physical model proof.
    @module.dataclass(frozen=True)
    class Context:
        score: object
        final_minutes: tuple = ()

    contexts = tuple(
        Context(SimpleNamespace(gameweek=f.gameweek, fixture_id=f.fixture_id))
        for f in inventory.calendar
    )
    monkeypatch.setattr(module, "compose_fixture", executor)
    fixtures = module._fixture_results(contexts, None, weeks.laws)
    native = {
        "rows": [
            dict(
                gameweek=law.gameweek,
                player_id=law.player_code,
                fixture_count=len(law.fixtures),
                home_fixture_count=0,
                expected_points=0.0,
                appearance_probability=0.0,
            )
            for law in weeks.laws
        ]
    }
    state = module._State(
        "{}",
        canonical(native),
        "{}",
        "{}",
        inventory,
        inputs,
        contexts,
        None,
        serving(),
        (),
        weeks,
        fixtures,
        inventory.decision_at,
        inventory.decision_at,
    )
    served = dict(rows=module._weekly_rows(state, weeks, fixtures))
    served["fingerprint"] = forecast_digest(served)
    return module.CompositeComponentBasis(canonical(served), "{}", state)


def test_baseline_returns_exact_detached_values_without_models_or_double_eligibility(
    cached_basis, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("A cached no-news request must not call any model")

    monkeypatch.setattr(module, "compose_fixture", forbidden)
    monkeypatch.setattr(module, "compose_composite_weeks", forbidden)
    result = cached_basis.recompose(())
    assert result.fingerprint == cached_basis.served["fingerprint"]
    assert_frame_equal(result.fixture_rows, cached_basis.fixture_rows)
    assert_frame_equal(result.weekly_rows, cached_basis.weekly_rows)
    source = cached_basis._state.baseline_weeks.laws[0]
    assert (
        result.weekly_rows.iloc[0].appearance_probability
        == joint_week_marginals(source).weekly_appearance
    )
    result.weekly_rows.loc[0, "expected_points"] = 999
    assert cached_basis.weekly_rows.iloc[0].expected_points != 999


def test_news_restarts_from_original_full_week_and_preserves_other_fixtures(
    cached_basis, monkeypatch
):
    calls = []

    def tracked(context, models):
        calls.append(context.score.fixture_id)
        return executor(context, models)

    def forbidden(*args, **kwargs):
        raise AssertionError("LOAD must never rerun for news")

    monkeypatch.setattr(module, "compose_fixture", tracked)
    monkeypatch.setattr(module, "compose_composite_weeks", forbidden)
    claim = VerifiedWeekEvidence("evidence-one", 42, 7, (100,), "absence", "9" * 64)
    original = cached_basis.recompose()
    cached_basis.validate_evidence((claim,))
    assert not calls
    first = cached_basis.recompose((claim,))
    second = cached_basis.recompose((claim,))
    assert calls == [100, 100]
    assert first.fingerprint == second.fingerprint
    assert_frame_equal(first.fixture_rows, second.fixture_rows)
    assert first.fixture_rows.loc[first.fixture_rows.fixture.eq(100), "expected_points"].eq(0).all()
    assert_frame_equal(
        first.fixture_rows.loc[first.fixture_rows.fixture.ne(100)],
        original.fixture_rows.loc[original.fixture_rows.fixture.ne(100)],
    )
    assert first.fixture_receipts[1:] == original.fixture_receipts[1:]
    assert cached_basis.recompose().fingerprint == original.fingerprint
    assert cached_basis._state.baseline_weeks == original.weekly_result


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        (object(),),
        (VerifiedWeekEvidence([], 42, 7, (100,), "absence", "9" * 64),),
        (VerifiedWeekEvidence("bad-player", 999, 7, (100,), "absence", "9" * 64),),
        (VerifiedWeekEvidence("future", 42, 8, (101,), "absence", "9" * 64),),
        (VerifiedWeekEvidence("wrong-fixture", 42, 7, (999,), "absence", "9" * 64),),
    ],
)
def test_invalid_evidence_refuses_without_calling_any_fixture(cached_basis, monkeypatch, evidence):
    monkeypatch.setattr(module, "compose_fixture", lambda *a, **k: pytest.fail("No model call"))
    with pytest.raises(ValueError):
        cached_basis.recompose(evidence)


def rendered_documents(cached_basis):
    state = cached_basis._state
    # Public reader replay tests use an explicit reconstructed-state double.
    module_metadata = dict(
        version=COMPOSITE_REPROJECTION_VERSION,
        active_heads=list(COMPOSITE_ACTIVE_HEADS),
        availability_application=COMPOSITE_AVAILABILITY_POLICY,
        model_artifacts=[
            dict(
                role=role,
                kind="retained_flag_result" if role == "flags" else "compact_model",
                sha256="1" * 64,
                fit_sha256="2" * 64,
            )
            for role in ("flags", *module.MODEL_ROLES)
        ],
        basis_sha256=digest({}),
        fixture_receipts_sha256=digest([]),
        generated_at=state.generated_at,
        decision_at=state.decision_at,
        weekly_laws=[
            dict(
                gameweek=law.gameweek,
                player_code=law.player_code,
                sha256=module.joint_week_law_digest(law),
                appearance_probability=joint_week_marginals(law).weekly_appearance,
                fixture_ids=[f.fixture_id for f in law.fixtures],
            )
            for law in state.baseline_weeks.laws
        ],
    )
    served = dict(
        cached_basis.served,
        captured_at_utc=state.inventory.captured_at,
        model_version=COMPOSITE_MODEL_VERSION,
        feature_contract_version=COMPOSITE_FEATURE_VERSION,
        availability_application=COMPOSITE_AVAILABILITY_POLICY,
        composite_metadata=module_metadata,
    )
    served["fingerprint"] = forecast_digest(served)
    companion = dict(
        contract_version=module.COMPONENT_CONTRACT,
        forecast_fingerprint=served["fingerprint"],
        recipe={},
        rows=cached_basis.fixture_rows.to_dict("records"),
        weekly_result=asdict(state.baseline_weeks),
        fixture_receipts=[],
    )
    companion["fingerprint"] = forecast_digest(companion)
    return served, companion


@pytest.mark.parametrize("target", ["points", "atom", "receipt", "source", "unknown"])
def test_redigested_reader_payload_must_reproduce_every_value(cached_basis, monkeypatch, target):
    served, companion = rendered_documents(cached_basis)
    expected = deepcopy((served, companion))
    monkeypatch.setattr(module, "_restore_recipe", lambda *a, **k: cached_basis._state)
    monkeypatch.setattr(module, "_render", lambda state: expected)
    if target == "points":
        served["rows"][0]["expected_points"] += 1
    elif target == "atom":
        companion["rows"][0]["clean_sheet_probability"] += 0.1
    elif target == "receipt":
        companion["fixture_receipts"] = [{"invented": True}]
    elif target == "source":
        companion["recipe"] = {"changed": True}
    else:
        companion["unknown_field"] = "refused"
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    with pytest.raises(ValueError, match="reproduce every"):
        module.CompositeComponentBasis.from_documents(
            served,
            companion,
            fixture_calendar=pd.DataFrame(),
            roster_clubs={},
            roster_positions={},
            deadline_by_gameweek={},
            captured_calendar_sha256="a" * 64,
        )


def test_external_capture_requirements_cannot_be_omitted(cached_basis):
    served, companion = rendered_documents(cached_basis)
    with pytest.raises(ValueError, match="captured positions"):
        module.CompositeComponentBasis.from_documents(
            served, companion, fixture_calendar=pd.DataFrame(), roster_clubs={}
        )


@pytest.mark.parametrize(
    "cutoff",
    ["2026-10-15T00:00:00Z", "2026-10-15T13:00:00Z", "2026-10-15T16:00:00+03:00"],
)
def test_native_envelope_preserves_earlier_fit_cutoff_and_accepts_equivalent_instants(cutoff):
    envelope, native, components, inventory = envelope_case()
    envelope["fit_information_cutoff"] = cutoff
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    module._native_envelope(envelope, native, components, inventory, inventory.decision_at)
    assert envelope["fit_information_cutoff"] == cutoff
    assert native["captured_at_utc"] == "2026-10-15T13:00:00Z"


@pytest.mark.parametrize(
    "cutoff",
    [
        "2026-10-15T13:00:00.000001Z",  # After capture, before all producer clocks.
        "2026-10-14T23:00:00Z",  # Equal to the native three-hour history bound.
        "2026-10-14T22:59:59Z",  # Before history, otherwise before capture/production.
        "2026-10-15T00:00:00",  # Naive timestamp.
        "NaT",
        "Infinity",
        None,
        False,
        0,
    ],
)
def test_native_envelope_refuses_invalid_fit_clock_after_resigning_only_its_digest(cutoff):
    envelope, native, components, inventory = envelope_case()
    envelope["fit_information_cutoff"] = cutoff
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    with pytest.raises(ValueError):
        module._native_envelope(envelope, native, components, inventory, inventory.decision_at)


def test_native_envelope_requires_fit_cutoff_even_with_a_matching_digest():
    envelope, native, components, inventory = envelope_case()
    del envelope["fit_information_cutoff"]
    inventory = replace(inventory, native_basis_sha256=digest(envelope))
    with pytest.raises(ValueError):
        module._native_envelope(envelope, native, components, inventory, inventory.decision_at)
