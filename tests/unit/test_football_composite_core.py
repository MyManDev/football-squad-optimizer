"""Synthetic complete fixtures, independent mass/score oracles and refusal boundaries."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import timedelta

import pytest
from scipy.stats import nbinom
from tests.unit.test_football_observed_tactical import projection as tactical_projection
from tests.unit.test_football_phase_duties import _fit as phase_fit
from tests.unit.test_football_score_projection import history
from tests.unit.test_football_score_replay import replay
from tests.unit.test_football_score_state import fit as score_fit
from tests.unit.test_football_score_state import observation
from tests.unit.test_football_unit_pooled import fit as unit_fit
from tests.unit.test_football_unit_replay import current_projection

from squadopt.features.football_phase_inputs import PhaseDutyCapture, PhaseDutyPlayer, PhaseSource
from squadopt.features.football_score_projection import ScoreDurationForecast
from squadopt.features.football_score_replay import validate_score_replay_basis
from squadopt.features.football_score_state_inputs import (
    CLOCK_VERSION,
    COMPOSITE_OFFSET_VERSION,
    validate_score_fixture,
    validate_training_score_header,
)
from squadopt.prediction.football_composite_core import (
    CompositeFixtureInput,
    CompositeModels,
    CompositePhaseContext,
    CompositeScoreContext,
    CompositeUnitContext,
    FinalMinuteMarginal,
    composite_bytes,
    composite_input_digest,
)
from squadopt.prediction.football_composite_core import (
    compose_fixture as compose,
)
from squadopt.prediction.football_minutes_role import ROLE_MINUTE_VERSION
from squadopt.prediction.football_observed_tactical import (
    ObservedTacticalRecipient,
    ObservedTacticalRecipientSide,
)
from squadopt.prediction.football_phase_serving import (
    export_phase_serving_model,
    read_phase_serving_model,
)
from squadopt.prediction.football_score_serving import (
    export_score_serving_model,
    read_score_serving_model,
)
from squadopt.prediction.football_unit_serving import (
    export_unit_serving_model,
    read_unit_serving_model,
)


def stamp(value):
    return value.isoformat()


def compose_fixture(x, models, *, bypass=False):
    return compose(x, models, bypass=bypass, include_stage_payloads=True)


def restore(exported, reader):
    return reader(exported, expected_sha256=hashlib.sha256(exported).hexdigest())


@dataclass(frozen=True)
class RecipientReceipt:
    artifact_sha256: str = "a" * 64
    original_metadata_sha256: str = "b" * 64


@dataclass(frozen=True)
class RecipientResult:
    home: ObservedTacticalRecipientSide
    away: ObservedTacticalRecipientSide
    projection_sha256: str
    control: bool = False
    serving_receipt: RecipientReceipt = RecipientReceipt()


class RecipientOracle:
    """A transparent share-only test double; production receives compact fitted models."""

    artifact_sha256 = "a" * 64

    def predict_recipients(self, p, *, control=False):
        sides = tuple(
            ObservedTacticalRecipientSide(
                side.club,
                tuple(
                    ObservedTacticalRecipient(
                        player.profile.player_code,
                        side.club,
                        player.profile.fpl_position,
                        player.native_goal_share,
                        player.native_assist_share,
                    )
                    for player in side.players
                ),
            )
            for side in (p.home, p.away)
        )
        return RecipientResult(*sides, hashlib.sha256(composite_bytes(p)).hexdigest())


@pytest.fixture(scope="module")
def models():
    return CompositeModels(
        restore(
            export_unit_serving_model(
                unit_fit(), original_fit_sha256="1" * 64, target_season="2026-27", target_gameweek=6
            ),
            read_unit_serving_model,
        ),
        restore(export_score_serving_model(score_fit()), read_score_serving_model),
        RecipientOracle(),
        restore(export_phase_serving_model(phase_fit()), read_phase_serving_model),
    )


def case():
    unit = current_projection()
    unit = replace(unit, gameweek=6, catalog=replace(unit.catalog, gameweek=6))
    decision = unit.decision_cutoff
    generated = decision
    kickoff = unit.kickoff
    original = tactical_projection(current=True, missing=True)
    probability = (0.1, 0.1, 0.2, 0.5, 0.1, 0.0, 0.0)
    minutes = (0.0, 30.0, 75.0, 90.0, 15.0, 65.0, 90.0)
    expected = sum(p * m for p, m in zip(probability, minutes, strict=True))
    native = []
    sides = []
    final = []
    for home, side, rate, opposing in (
        (
            True,
            original.home,
            unit.causal_baseline_own_goal_rate,
            unit.causal_baseline_opponent_goal_rate,
        ),
        (
            False,
            original.away,
            unit.causal_baseline_opponent_goal_rate,
            unit.causal_baseline_own_goal_rate,
        ),
    ):
        players = []
        for i, player in enumerate(side.players, 1):
            code = i if home else 100 + i
            position = "FWD" if i == 12 else player.profile.fpl_position
            profile = replace(player.profile, player_code=code, fpl_position=position)
            players.append(
                replace(
                    player,
                    profile=profile,
                    minutes=expected,
                    native_goal_share=1 / 12,
                    native_assist_share=1 / 12,
                )
            )
            final.append(FinalMinuteMarginal(code, probability, minutes, "c" * 64))
            row = dict(
                player_code=code,
                club=side.club,
                opponent=3 - side.club,
                home=int(home),
                fixture=800,
                GW=6,
                kickoff=stamp(kickoff),
                position=position,
                model_version="football_joint_role_retained_history_v1",
                team_goal_rate=rate,
                opponent_goal_rate=opposing,
                expected_minutes=expected,
                appearance_probability=0.9,
                p60=0.7,
                zero_probability=0.1,
                start_probability=0.8,
                cameo_probability=0.1,
                unknown_role_probability=0.0,
                expected_minutes_if_appearance=expected / 0.9,
                minute_role_status="fitted_known_start_labels",
                minute_role_version=ROLE_MINUTE_VERSION,
                known_start_label_rows=10,
                unknown_start_label_rows=0,
                minute_prior_rows=10.0,
                goals=rate * 0.9 / 12,
                assists=rate * 0.9 * 0.7 / 12,
                goals_share=1 / 12,
                assists_share=1 / 12,
                defcon_rate90=8.0,
                defcon_dispersion=4.0,
                residual_if_appearance=-0.2,
                clean_sheet_probability=0.2,
                defcon_probability=0.1,
                raw_expected_points=1.234,
                expected_points=1.234,
                availability_multiplier=0.5,
            )
            for role, offset in (("start", 0), ("cameo", 3)):
                for b in (1, 2, 3):
                    row[f"{role}_minute_probability_{b}"] = probability[offset + b]
                    row[f"{role}_minute_value_{b}"] = minutes[offset + b]
            row.update(minute_probability_0=0.1, minute_value_0=0)
            for b in (1, 2, 3):
                mass = probability[b] + probability[b + 3]
                row[f"minute_probability_{b}"] = mass
                row[f"minute_value_{b}"] = (
                    probability[b] * minutes[b] + probability[b + 3] * minutes[b + 3]
                ) / mass
            native.append(row)
        sides.append(replace(side, players=tuple(players), base_goal_rate=rate))
    tactical = replace(
        original,
        gameweek=6,
        fixture=800,
        kickoff=stamp(kickoff),
        decision_at=stamp(decision),
        feature_cutoff=stamp(decision - timedelta(minutes=1)),
        generated_at=stamp(generated),
        native_source=replace(original.native_source, sha256="f" * 64),
        home=sides[0],
        away=sides[1],
        roster=tuple(
            sorted(
                (p.profile.player_code, s.club, p.profile.fpl_position)
                for s in sides
                for p in s.players
            )
        ),
    )
    phases = []
    for i, side in enumerate(sides):
        duties = PhaseDutyCapture(
            "2026-27",
            "synthetic-capture",
            "d" * 64,
            stamp(decision - timedelta(hours=1)),
            stamp(kickoff),
            True,
            "synthetic-only",
            tuple(
                PhaseDutyPlayer(p.profile.player_code, s.club, None, None, None)
                for s in sides
                for p in s.players
            ),
        )
        source = PhaseSource(
            "synthetic-projection",
            "synthetic",
            "synthetic-v1",
            "e" * 64,
            stamp(decision - timedelta(hours=1)),
            stamp(decision - timedelta(hours=1)),
            "projection",
            True,
            "synthetic-only",
        )
        phases.append(
            CompositePhaseContext(
                "2026-27",
                6,
                800,
                side.club,
                3 - side.club,
                i == 0,
                stamp(kickoff),
                stamp(decision),
                duties,
                source,
            )
        )
    score = CompositeScoreContext(
        "2026-27",
        6,
        800,
        stamp(decision),
        stamp(decision + timedelta(hours=1)),
        stamp(kickoff),
        1,
        2,
        unit.causal_baseline_own_goal_rate,
        unit.causal_baseline_opponent_goal_rate,
        CLOCK_VERSION,
        "f" * 64,
        "football_joint_role_retained_history_v1",
        "prospective",
        stamp(decision - timedelta(hours=2)),
        "synthetic-native",
        "a" * 64,
        "synthetic-coverage",
        "synthetic-calendar",
    )
    return CompositeFixtureInput(
        json.dumps(native, indent=2),
        "f" * 64,
        "e" * 64,
        tuple(final),
        CompositeUnitContext(
            **{k: v for k, v in vars(unit).items() if k not in ("home", "states")}
        ),
        score,
        ScoreDurationForecast(
            "2026-27",
            6,
            800,
            stamp(decision - timedelta(hours=1)),
            stamp(decision - timedelta(minutes=30)),
            stamp(decision),
            history(),
        ),
        tactical,
        tuple(phases),
        stamp(generated),
    )


def stage(result, name):
    return json.loads(next(s.payload_json for s in result.receipt.stages if s.name == name))


def test_full_bypass_is_exact_original_json_and_executes_no_stage():
    x = case()
    result = compose_fixture(x, None, bypass=True)
    assert result.rows_json is x.native_rows_json
    assert result.receipt.stages == ()
    assert result.receipt.active_heads == ()
    assert (
        result.receipt.final_rows_sha256 == hashlib.sha256(x.native_rows_json.encode()).hexdigest()
    )


def test_complete_chain_preserves_atoms_mass_and_independent_fpl_formula(models):
    x = case()
    before = composite_input_digest(x)
    result = compose_fixture(x, models)
    rows = json.loads(result.rows_json)
    score = stage(result, "score_process_on_unit_means")["result"]["prediction"]
    assert score["fixture"]["native_model_version"] == COMPOSITE_OFFSET_VERSION
    assert result.receipt.tactical_rate_head == "not_evaluated"
    for club, physical in ((1, score["home_physical_goals"]), (2, score["away_physical_goals"])):
        side = [r for r in rows if r["club"] == club]
        assert math.fsum(r["goals"] for r in side) == pytest.approx(physical * 0.9)
        assert math.fsum(r["assists"] for r in side) == pytest.approx(physical * 0.9 * 0.7)
    for r in rows:
        p = next(p for p in x.final_minutes if p.player_code == r["player_code"])
        cs = sum(
            prob * r[f"score_survival_{i}"]
            for i, (prob, m) in enumerate(zip(p.probabilities, p.minutes, strict=True))
            if m >= 60
        )
        threshold = 10 if r["position"] == "DEF" else 12
        dc = (
            0
            if r["position"] == "GK"
            else sum(
                prob * nbinom.sf(threshold - 1, 4, 4 / (4 + 8 * m / 90))
                for prob, m in zip(p.probabilities, p.minutes, strict=True)
            )
        )
        raw = (
            0.9
            + 0.7
            + {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[r["position"]] * r["goals"]
            + 3 * r["assists"]
            + {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[r["position"]] * cs
            + 2 * dc
            - 0.18
        )
        assert r["clean_sheet_probability"] == pytest.approx(cs, abs=1e-14)
        assert r["raw_expected_points"] == pytest.approx(raw, abs=1e-14)
        assert r["appearance_probability"] == pytest.approx(0.9)  # No second captured .5.
    assert composite_input_digest(x) == before


def test_absence_rebuilds_point_unit_and_full_club_allocation(models):
    x = case()
    original = compose_fixture(x, models)
    changed = replace(
        x,
        final_minutes=tuple(
            replace(
                p, probabilities=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), final_week_law_sha256="d" * 64
            )
            if p.player_code == 11
            else p
            for p in x.final_minutes
        ),
    )
    result = compose_fixture(changed, models)
    points = stage(result, "final_law_point_units")["result"]
    assert 12 in {p["player_id"] for p in points[0]["unit"]["players"]}
    assert 11 not in {p["player_id"] for p in points[0]["unit"]["players"]}
    rows = {r["player_code"]: r for r in json.loads(result.rows_json)}
    assert rows[11]["expected_points"] == 0
    assert rows[11]["goals"] == rows[11]["assists"] == 0
    assert result.receipt.final_rows_sha256 != original.receipt.final_rows_sha256


@pytest.mark.parametrize(
    "damage",
    [
        "minutes",
        "cameo90",
        "missing_player",
        "late_generation",
        "fraction",
        "assist_fraction",
        "native_identity",
        "law_hash",
        "nan",
        "unknown_role",
    ],
)
def test_bad_scope_support_or_original_source_refuses(models, damage):
    x = case()
    if damage in ("minutes", "cameo90", "law_hash", "nan"):
        p = x.final_minutes[0]
        changes = {
            "minutes": dict(minutes=(0.0, 31.0, 75.0, 90.0, 15.0, 65.0, 90.0)),
            "cameo90": dict(probabilities=(0.1, 0.1, 0.2, 0.4, 0.1, 0.0, 0.1)),
            "law_hash": dict(final_week_law_sha256="bad"),
            "nan": dict(probabilities=(float("nan"), 0.1, 0.2, 0.5, 0.1, 0.0, 0.0)),
        }[damage]
        x = replace(x, final_minutes=(replace(p, **changes), *x.final_minutes[1:]))
    elif damage == "missing_player":
        x = replace(x, final_minutes=x.final_minutes[:-1])
    elif damage == "late_generation":
        x = replace(x, generated_at=x.score.kickoff)
    elif damage in ("fraction", "assist_fraction"):
        x = replace(
            x,
            tactical=replace(
                x.tactical,
                home=replace(
                    x.tactical.home,
                    **{"scored_fraction" if damage == "fraction" else "assist_fraction": 0.8},
                ),
            ),
        )
    else:
        rows = json.loads(x.native_rows_json)
        rows[0]["fixture" if damage == "native_identity" else "minute_role_status"] = (
            999 if damage == "native_identity" else "unavailable_no_known_start_labels"
        )
        x = replace(x, native_rows_json=json.dumps(rows))
    with pytest.raises(ValueError):
        compose_fixture(x, models)


def test_score_offset_can_never_be_relabelled_as_training():
    old = observation(0)
    current = replace(
        old.input, native_model_version=COMPOSITE_OFFSET_VERSION, native_basis_kind="prospective"
    )
    validate_score_fixture(current)
    with pytest.raises(ValueError, match="historical training"):
        validate_training_score_header(replace(old, input=current))
    with pytest.raises(ValueError, match="prospective inference"):
        validate_score_fixture(replace(current, native_basis_kind="out_of_fold"))
    with pytest.raises(ValueError, match="native model contract"):
        validate_score_replay_basis(
            replace(replay().basis, native_model_version=COMPOSITE_OFFSET_VERSION)
        )


def test_no_full_match_preserves_roles_but_recomputes_exposure_and_score(models):
    x = case()
    original = compose_fixture(x, models)
    p = x.final_minutes[1]
    shorter = p.probabilities[1] + p.probabilities[2]
    probabilities = (
        p.probabilities[0],
        p.probabilities[1] * (1 + 0.5 / shorter),
        p.probabilities[2] * (1 + 0.5 / shorter),
        0.0,
        *p.probabilities[4:],
    )
    modified = replace(p, probabilities=probabilities, final_week_law_sha256="d" * 64)
    result = compose_fixture(
        replace(x, final_minutes=(x.final_minutes[0], modified, *x.final_minutes[2:])), models
    )
    before = {r["player_code"]: r for r in json.loads(original.rows_json)}
    after = {r["player_code"]: r for r in json.loads(result.rows_json)}
    assert after[2]["start_probability"] == pytest.approx(before[2]["start_probability"])
    assert after[2]["appearance_probability"] == before[2]["appearance_probability"]
    assert after[2]["expected_minutes"] < before[2]["expected_minutes"]
    assert after[2]["clean_sheet_probability"] != before[2]["clean_sheet_probability"]
    assert (
        stage(result, "unit_paired_whole_fixture_means")["result"]["own_goal_rate"]
        == stage(original, "unit_paired_whole_fixture_means")["result"]["own_goal_rate"]
    )
    assert any(after[i]["goals"] != before[i]["goals"] for i in range(1, 13) if i != 2)


def test_stage_receipts_hash_exact_reconstructable_inputs_and_results(models):
    x = case()
    result = compose_fixture(x, models)
    for receipt in result.receipt.stages:
        payload = json.loads(receipt.payload_json)
        assert receipt.input_sha256 == hashlib.sha256(composite_bytes(payload["input"])).hexdigest()
        assert (
            receipt.result_sha256 == hashlib.sha256(composite_bytes(payload["result"])).hexdigest()
        )
    unit = stage(result, "unit_paired_whole_fixture_means")["input"]
    source_ids = {s["source_id"] for s in unit["catalog"]["sources"]}
    assert {s.source_id for s in x.unit.catalog.sources} < source_ids
    assert unit["catalog"]["reference_source_id"] == x.unit.catalog.reference_source_id
    assert unit["catalog"]["projection_source_id"].startswith("composite-point:")
    assert result.receipt.original_native_basis_sha256 == x.native_basis_sha256


def test_default_compact_receipts_preserve_all_stage_hashes_and_results(models):
    x = case()
    compact = compose(x, models)
    verbose = compose_fixture(x, models)
    assert compact.rows_json == verbose.rows_json
    assert compact.receipt == replace(
        verbose.receipt, stages=tuple(replace(s, payload_json=None) for s in verbose.receipt.stages)
    )
    assert all(s.payload_json is None for s in compact.receipt.stages)
    assert len(composite_bytes(compact.receipt)) < 8000


@pytest.mark.parametrize("damage", ["replay", "snapshot", "fingerprint", "capture_time"])
def test_phase_sources_cannot_replay_or_mix_captures(models, damage):
    x = case()
    changes = {
        "replay": {"snapshot_id": "git:" + "a" * 40},
        "snapshot": {"snapshot_id": "another-current-capture"},
        "fingerprint": {"source_fingerprint": "9" * 64},
        "capture_time": {"captured_at": stamp(x.unit.decision_cutoff - timedelta(hours=2))},
    }[damage]
    phases = list(x.phase)
    indexes = (0, 1) if damage == "replay" else (1,)
    for i in indexes:
        phases[i] = replace(phases[i], duties=replace(phases[i].duties, **changes))
    with pytest.raises(ValueError, match="phase source"):
        compose_fixture(replace(x, phase=tuple(phases)), models)


def test_point_xi_uses_start_atoms_when_appearance_ranks_differ(models):
    x = case()
    laws = {
        11: (0.1, 0.1, 0.1, 0.1, 0.6, 0.0, 0.0),
        12: (0.2, 0.1, 0.2, 0.5, 0.0, 0.0, 0.0),
    }
    x = replace(
        x,
        final_minutes=tuple(
            replace(p, probabilities=laws[p.player_code]) if p.player_code in laws else p
            for p in x.final_minutes
        ),
    )
    result = compose_fixture(x, models)
    selected = {
        p["player_id"]
        for p in stage(result, "final_law_point_units")["result"][0]["unit"]["players"]
    }
    assert 12 in selected and 11 not in selected


def test_core_itself_refuses_unit_replay_before_calling_a_serving_model():
    from tests.unit.test_football_unit_replay import replay_catalog

    from squadopt.prediction.football_composite_core import _validate

    x = case()
    _validate(x)
    catalog = replay_catalog()
    assert catalog.replay is not None
    x = replace(x, unit=replace(x.unit, catalog=catalog))
    with pytest.raises(ValueError, match="without replay"):
        _validate(x)


def test_phase_offsets_are_the_nonidentity_tactical_recipient_shares(models):
    class WeightedRecipients(RecipientOracle):
        def predict_recipients(self, p, *, control=False):
            original = super().predict_recipients(p, control=control)
            sides = []
            for side in (original.home, original.away):
                goals = [r.goal_share * (1 + r.player_code % 3) for r in side.players]
                assists = [r.assist_share * (1 + r.player_code % 5) for r in side.players]
                sides.append(
                    replace(
                        side,
                        players=tuple(
                            replace(
                                r,
                                goal_share=g / math.fsum(goals),
                                assist_share=a / math.fsum(assists),
                            )
                            for r, g, a in zip(side.players, goals, assists, strict=True)
                        ),
                    )
                )
            return replace(original, home=sides[0], away=sides[1])

    x = case()
    result = compose_fixture(x, replace(models, tactical=WeightedRecipients()))
    recipients = stage(result, "tactical_recipient_heads_only")["result"]
    for orientation, club in (("home", 1), ("away", 2)):
        expected = {p["player_code"]: p for p in recipients[orientation]["players"]}
        native = getattr(x.tactical, orientation)
        assert any(
            expected[p.profile.player_code]["goal_share"] != p.native_goal_share
            for p in native.players
        )
        states = stage(result, f"phase_coupling_{club}")["input"]["projection"]["states"]
        for state in states:
            for p in state["players"]:
                marginal = next(m for m in x.final_minutes if m.player_code == p["player_code"])
                minutes = math.fsum(
                    q * m for q, m in zip(marginal.probabilities, marginal.minutes, strict=True)
                )
                for head in ("goal", "assist"):
                    assert p[head + "_weight90"] == pytest.approx(
                        90 * expected[p["player_code"]][head + "_share"] / minutes
                    )


def test_native_artifact_envelope_model_version_does_not_require_row_injection(models):
    x = case()
    original = json.loads(x.native_rows_json)
    rows = [{k: v for k, v in row.items() if k != "model_version"} for row in original]
    exact = json.dumps(rows, indent=2)
    x = replace(x, native_rows_json=exact)
    assert compose_fixture(x, None, bypass=True).rows_json is exact
    result = compose_fixture(x, models)
    assert all(
        row["model_version"] == "football_composite_v1" for row in json.loads(result.rows_json)
    )
    assert result.receipt.original_native_rows_sha256 == hashlib.sha256(exact.encode()).hexdigest()
    original[0]["model_version"] = "unsupported-model"
    with pytest.raises(ValueError, match="fixture scope differs"):
        compose_fixture(replace(x, native_rows_json=json.dumps(original)), models)
    with pytest.raises(ValueError, match="original prospective source contexts"):
        compose_fixture(
            replace(x, score=replace(x.score, native_model_version="unsupported-model")), models
        )


@pytest.mark.parametrize(
    "damage",
    [
        "decision",
        "opponent",
        "replay_offset",
        "unmapped_roster",
        "duplicate_json",
        "duplicate_final",
        "baseline",
        "late_phase",
        "late_unit",
    ],
)
def test_cross_family_source_mismatch_refuses_before_stages(models, damage):
    x = case()
    if damage == "decision":
        x = replace(x, score=replace(x.score, decision_at=x.score.deadline_at))
    elif damage == "opponent":
        x = replace(x, phase=(replace(x.phase[0], opponent=99), x.phase[1]))
    elif damage == "replay_offset":
        x = replace(x, score=replace(x.score, native_model_version=COMPOSITE_OFFSET_VERSION))
    elif damage == "unmapped_roster":
        x = replace(
            x,
            unit=replace(
                x.unit,
                catalog=replace(
                    x.unit.catalog,
                    mappings=tuple(m for m in x.unit.catalog.mappings if m.player_id != 12),
                ),
            ),
        )
    elif damage == "duplicate_json":
        x = replace(
            x,
            native_rows_json=x.native_rows_json.replace(
                '"player_code": 1,', '"player_code": 1, "player_code": 1,', 1
            ),
        )
    elif damage == "duplicate_final":
        x = replace(x, final_minutes=(*x.final_minutes, x.final_minutes[0]))
    elif damage == "baseline":
        x = replace(x, unit=replace(x.unit, causal_baseline_own_goal_rate=5.0))
    elif damage == "late_phase":
        x = replace(
            x,
            phase=(
                replace(x.phase[0], source=replace(x.phase[0].source, captured_at=x.score.kickoff)),
                x.phase[1],
            ),
        )
    elif damage == "late_unit":
        x = replace(x, unit=replace(x.unit, captured_at=x.unit.kickoff))
    with pytest.raises(ValueError):
        compose_fixture(x, models)


@pytest.mark.parametrize("target", ["root", "score", "tactical"])
def test_original_native_artifact_identity_must_match_across_families(models, target):
    x = case()
    if target == "root":
        x = replace(x, native_basis_sha256="0" * 64)
    elif target == "score":
        x = replace(x, score=replace(x.score, native_basis_sha256="0" * 64))
    else:
        x = replace(
            x,
            tactical=replace(
                x.tactical, native_source=replace(x.tactical.native_source, sha256="0" * 64)
            ),
        )
    with pytest.raises(ValueError, match="original native artifact identities"):
        compose_fixture(x, models)


@pytest.mark.parametrize(
    "target", ["duties", "duration_generation", "duration_capture", "tactical"]
)
def test_source_available_before_decision_but_after_assembly_refuses(models, target):
    x = case()
    generated = x.unit.decision_cutoff - timedelta(minutes=10)
    later = stamp(generated + timedelta(minutes=5))
    x = replace(
        x,
        unit=replace(
            x.unit,
            captured_at=generated,
            catalog=replace(
                x.unit.catalog,
                sources=tuple(
                    replace(
                        s, published_at=generated, captured_at=generated, effective_at=generated
                    )
                    for s in x.unit.catalog.sources
                ),
            ),
        ),
        generated_at=stamp(generated),
        tactical=replace(x.tactical, generated_at=stamp(generated)),
        duration=replace(x.duration, generated_at=stamp(generated)),
    )
    compose_fixture(x, models)
    if target == "duties":
        x = replace(
            x,
            phase=(
                replace(x.phase[0], duties=replace(x.phase[0].duties, captured_at=later)),
                x.phase[1],
            ),
        )
    elif target == "duration_generation":
        x = replace(x, duration=replace(x.duration, generated_at=later))
    elif target == "duration_capture":
        x = replace(x, duration=replace(x.duration, source_captured_at=later))
    else:
        x = replace(
            x,
            tactical=replace(
                x.tactical, roster_source=replace(x.tactical.roster_source, retrieved_at=later)
            ),
        )
    with pytest.raises(ValueError):
        compose_fixture(x, models)
