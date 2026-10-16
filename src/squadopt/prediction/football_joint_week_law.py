"""Pure composition of one complete player-week minute distribution.

Sources and evidence are verified by callers. This module records their supplied
identities without inventing source clocks or fitting a model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

from squadopt.features.football_load_inputs import (
    POSITIONS,
    LoadFixture,
    native_joint_law_digest,
)

LAW_VERSION = "football_joint_week_law_v1"
ROLE_VERSION = "joint_start_cameo_minutes_v1"
_POLICIES = (
    "native_input_v1",
    "flag_model_result_v1",
    "load_model_result_v1",
    "shared_eligibility_mixture_v1",
    "native_load_ratio_transport_v1",
    "verified_absence_pushforward_v1",
    "same_role_conditional_no_full_match_v1",
)
Sources = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class JointLawStep:
    policy: str
    parents: tuple[str, ...]
    sources: Sources
    fixture_ids: tuple[int, ...] = ()
    eligibility: float | None = None
    created_absent_indices: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class JointWeekLaw:
    season: str
    gameweek: int
    player_code: int
    position: str
    fixtures: tuple[LoadFixture, ...]
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    role_metadata_sha256: str
    original_native_sha256: str
    lineage: tuple[JointLawStep, ...]
    role_version: str = ROLE_VERSION
    version: str = LAW_VERSION


@dataclass(frozen=True, slots=True)
class JointWeekMarginals:
    weekly_appearance: float
    fixture_probabilities: tuple[tuple[float, ...], ...]
    expected_minutes: tuple[float, ...]
    start_probabilities: tuple[float, ...]
    cameo_probabilities: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class VerifiedWeekEvidence:
    """Caller-verified claim, with exact fixture scope and source-byte identity."""

    evidence_id: str
    player_code: int
    gameweek: int
    fixture_ids: tuple[int, ...]
    kind: str
    source_sha256: str


def _digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Joint week law requires lowercase SHA256 identities.")


def _integer(value: int, *, high: int | None = None) -> None:
    if type(value) is not int or value < 1 or (high is not None and value > high):
        raise ValueError("Joint week law requires integer identities in range.")


def _sources(values: Sources) -> None:
    if type(values) is not tuple or not 1 <= len(values) <= 128:
        raise ValueError("Joint week law requires immutable named source identities.")
    names: set[str] = set()
    for pair in values:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("Joint week law sources require name/digest pairs.")
        name, digest = pair
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 256
            or not name.strip()
            or name != name.strip()
            or name in names
        ):
            raise ValueError("Joint week law source names must be nonblank and unique.")
        _digest(digest)
        names.add(name)


def _probability(value: float) -> float:
    if type(value) not in (int, float):
        raise ValueError("Joint week probabilities must be real numbers.")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("Joint week probabilities must be finite.") from error
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("Joint week probabilities must be finite and in [0, 1].")
    return number


def _marginals(
    states: tuple[tuple[int, ...], ...], probabilities: tuple[float, ...], count: int
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(
            math.fsum(p for state, p in zip(states, probabilities, strict=True) if state[j] == k)
            for k in range(7)
        )
        for j in range(count)
    )


def validate_joint_week_law(law: JointWeekLaw) -> None:
    if type(law) is not JointWeekLaw or (law.version, law.role_version) != (
        LAW_VERSION,
        ROLE_VERSION,
    ):
        raise ValueError("Joint week law requires its frozen version and fixed role vocabulary.")
    if (
        not isinstance(law.season, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}", law.season) is None
        or int(law.season[-2:]) != (int(law.season[:4]) + 1) % 100
        or int(law.season[:4]) < 2000
    ):
        raise ValueError("Joint week law season must use consecutive YYYY-YY.")
    _integer(law.gameweek, high=38)
    _integer(law.player_code)
    if law.position not in POSITIONS:
        raise ValueError("Joint week law position is unknown.")
    _digest(law.role_metadata_sha256)
    _digest(law.original_native_sha256)
    native_joint_law_digest(law.fixtures, law.states, law.probabilities)
    if type(law.lineage) is not tuple or not law.lineage or len(law.lineage) > 32:
        raise ValueError("Joint week law requires bounded immutable operation lineage.")
    ids = {f.fixture_id for f in law.fixtures}
    for step in law.lineage:
        if type(step) is not JointLawStep or step.policy not in _POLICIES:
            raise ValueError("Joint week law operation policy is unknown.")
        _sources(step.sources)
        if type(step.parents) is not tuple:
            raise ValueError("Joint week law parent identities must be immutable.")
        expected_parents = (
            0
            if step.policy == "native_input_v1"
            else 3
            if step.policy == "native_load_ratio_transport_v1"
            else 1
        )
        if len(step.parents) != expected_parents:
            raise ValueError("Joint week law operation has an invalid parent inventory.")
        for parent in step.parents:
            _digest(parent)
        if (
            type(step.fixture_ids) is not tuple
            or any(type(i) is not int for i in step.fixture_ids)
            or len(set(step.fixture_ids)) != len(step.fixture_ids)
        ):
            raise ValueError("Joint week law operation scope must be immutable and unique.")
        for fixture in step.fixture_ids:
            _integer(fixture)
            if fixture not in ids:
                raise ValueError("Joint week law operation names an unknown fixture.")
        evidence = step.policy in (
            "verified_absence_pushforward_v1",
            "same_role_conditional_no_full_match_v1",
        )
        if evidence != bool(step.fixture_ids):
            raise ValueError("Only explicit evidence operations require fixture scope.")
        if step.policy == "shared_eligibility_mixture_v1":
            if step.eligibility is None:
                raise ValueError("Shared eligibility needs its exact mixing probability.")
            _probability(step.eligibility)
        elif step.eligibility is not None:
            raise ValueError("Only shared eligibility can declare a mixing probability.")
        created = step.created_absent_indices
        if (
            type(created) is not tuple
            or any(type(i) is not int for i in created)
            or tuple(sorted(set(created))) != created
        ):
            raise ValueError("Created support indices must be ordered immutable integers.")
        if created and step.policy not in (
            "shared_eligibility_mixture_v1",
            "verified_absence_pushforward_v1",
        ):
            raise ValueError("Only structural absence interventions may create support.")
        selected = tuple(j for j, f in enumerate(law.fixtures) if f.fixture_id in step.fixture_ids)
        for index in created:
            if not 0 <= index < len(law.states):
                raise ValueError("Created absent index is outside the state inventory.")
            if step.policy == "shared_eligibility_mixture_v1":
                if index != 0:
                    raise ValueError("Shared eligibility creates only the all-absent cell.")
            elif any(law.states[index][j] != 0 for j in selected):
                raise ValueError("Absence pushforward can create only scoped absent cells.")
    if law.lineage[0].policy != "native_input_v1" or any(
        step.policy == "native_input_v1" for step in law.lineage[1:]
    ):
        raise ValueError("Joint week law lineage must begin at its one native source.")


def joint_week_law_digest(law: JointWeekLaw) -> str:
    validate_joint_week_law(law)
    return hashlib.sha256(
        json.dumps(asdict(law), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _updated(
    law: JointWeekLaw, probabilities: tuple[float, ...], step: JointLawStep
) -> JointWeekLaw:
    marginal = _marginals(law.states, probabilities, len(law.fixtures))
    result = replace(
        law,
        fixtures=tuple(
            replace(f, probabilities=p) for f, p in zip(law.fixtures, marginal, strict=True)
        ),
        probabilities=probabilities,
        lineage=(*law.lineage, step),
    )
    validate_joint_week_law(result)
    return result


def make_joint_week_law(
    *,
    season: str,
    gameweek: int,
    player_code: int,
    position: str,
    fixtures: tuple[LoadFixture, ...],
    states: tuple[tuple[int, ...], ...],
    probabilities: tuple[float, ...],
    role_metadata_sha256: str,
    sources: Sources,
) -> JointWeekLaw:
    """Bind a complete native law, normalizing once within the native tolerance."""
    native_digest = native_joint_law_digest(fixtures, states, probabilities)
    total = math.fsum(probabilities)
    normalized = tuple(p / total for p in probabilities)
    marginal = _marginals(states, normalized, len(fixtures))
    law = JointWeekLaw(
        season,
        gameweek,
        player_code,
        position,
        tuple(replace(f, probabilities=p) for f, p in zip(fixtures, marginal, strict=True)),
        states,
        normalized,
        role_metadata_sha256,
        native_digest,
        (JointLawStep("native_input_v1", (), sources),),
    )
    validate_joint_week_law(law)
    return law


def _native(law: JointWeekLaw) -> None:
    validate_joint_week_law(law)
    if len(law.lineage) != 1:
        raise ValueError("This operation requires the original unadjusted native law.")


def model_week_law(
    native: JointWeekLaw,
    states: tuple[tuple[int, ...], ...],
    probabilities: tuple[float, ...],
    *,
    kind: str,
    sources: Sources,
) -> JointWeekLaw:
    """Bind caller-verified flag or LOAD output, retaining its original native source."""
    _native(native)
    if (
        kind not in ("flag", "load")
        or type(states) is not tuple
        or any(
            type(state) is not tuple or any(type(k) is not int for k in state) for state in states
        )
        or states != native.states
    ):
        raise ValueError(
            "Model result needs exact canonical native states and a declared model kind."
        )
    if type(probabilities) is not tuple or len(probabilities) != len(native.probabilities):
        raise ValueError("Model result needs the full immutable probability inventory.")
    for original, changed in zip(native.probabilities, probabilities, strict=True):
        _probability(changed)
        if (original == 0) != (changed == 0):
            raise ValueError("Fitted model result must preserve native support exactly.")
    return _updated(
        native,
        probabilities,
        JointLawStep(f"{kind}_model_result_v1", (joint_week_law_digest(native),), sources),
    )


def _same_basis(first: JointWeekLaw, second: JointWeekLaw) -> None:
    validate_joint_week_law(second)
    if any(
        getattr(first, name) != getattr(second, name)
        for name in (
            "season",
            "gameweek",
            "player_code",
            "position",
            "states",
            "role_version",
            "role_metadata_sha256",
            "original_native_sha256",
        )
    ) or tuple(replace(f, probabilities=()) for f in first.fixtures) != tuple(
        replace(f, probabilities=()) for f in second.fixtures
    ):
        raise ValueError("Joint laws differ in identity, fixture order, minutes or role metadata.")


def apply_shared_eligibility(
    native: JointWeekLaw, eligibility: float, *, sources: Sources
) -> JointWeekLaw:
    """Mix one shared eligibility event into the week, never one event per fixture."""
    _native(native)
    e = _probability(eligibility)
    values = [e * p for p in native.probabilities]
    values[0] = math.fsum((1 - e, values[0]))
    if e > 0 and any(p > 0 and q <= 0 for p, q in zip(native.probabilities, values, strict=True)):
        raise ValueError("Shared eligibility multiplication lost positive support numerically.")
    created = tuple(
        i
        for i, (p, q) in enumerate(zip(native.probabilities, values, strict=True))
        if p == 0 and q > 0
    )
    return _updated(
        native,
        tuple(values),
        JointLawStep(
            "shared_eligibility_mixture_v1",
            (joint_week_law_digest(native),),
            sources,
            eligibility=e,
            created_absent_indices=created,
        ),
    )


def transport_load(
    native: JointWeekLaw, loaded: JointWeekLaw, offset: JointWeekLaw, *, sources: Sources
) -> JointWeekLaw:
    """Transport the fitted LOAD multiplier onto a flagged/shared-eligibility law.

    The ratio cancels the original fitted normalization. Unsupported native cells
    cannot acquire an extrapolated multiplier. This is an inference policy.
    """
    _native(native)
    _same_basis(native, loaded)
    _same_basis(native, offset)
    native_hash = joint_week_law_digest(native)
    if loaded.lineage[-1].policy != "load_model_result_v1" or loaded.lineage[-1].parents != (
        native_hash,
    ):
        raise ValueError("LOAD result must bind this exact original native law.")
    if offset.lineage[-1].policy not in (
        "flag_model_result_v1",
        "shared_eligibility_mixture_v1",
    ) or offset.lineage[-1].parents != (native_hash,):
        raise ValueError(
            "LOAD offset must be one flag or shared-eligibility operation on this native law."
        )
    for p, load_probability, q in zip(
        native.probabilities, loaded.probabilities, offset.probabilities, strict=True
    ):
        if (p == 0) != (load_probability == 0) or (q > 0 and p == 0):
            raise ValueError("LOAD transport cannot extrapolate beyond native supported cells.")
    if loaded.probabilities == native.probabilities:
        probabilities = offset.probabilities
    else:
        supported = tuple(i for i, q in enumerate(offset.probabilities) if q > 0)
        logits = tuple(
            math.log(offset.probabilities[i])
            + math.log(loaded.probabilities[i])
            - math.log(native.probabilities[i])
            for i in supported
        )
        largest = max(logits)
        positive = tuple(math.exp(value - largest) for value in logits)
        total = math.fsum(positive)
        values = [0.0] * len(offset.probabilities)
        for index, value in zip(supported, positive, strict=True):
            values[index] = value / total
            if not math.isfinite(values[index]) or values[index] <= 0:
                raise ValueError("LOAD transport lost positive offset support numerically.")
        probabilities = tuple(values)
    return _updated(
        offset,
        probabilities,
        JointLawStep(
            "native_load_ratio_transport_v1",
            (native_hash, joint_week_law_digest(loaded), joint_week_law_digest(offset)),
            sources,
        ),
    )


def _absence(law: JointWeekLaw, j: int) -> tuple[float, ...]:
    destinations = {state: index for index, state in enumerate(law.states)}
    mass: list[list[float]] = [[] for _ in law.states]
    for state, probability in zip(law.states, law.probabilities, strict=True):
        target = (*state[:j], 0, *state[j + 1 :])
        mass[destinations[target]].append(probability)
    return tuple(math.fsum(values) for values in mass)


def _no_full_match(law: JointWeekLaw, j: int) -> tuple[float, ...]:
    if math.fsum(p for s, p in zip(law.states, law.probabilities, strict=True) if s[j] != 0) <= 0:
        raise ValueError("No positive effective appearance basis for no_full_match.")
    indices = {state: i for i, state in enumerate(law.states)}
    result = list(law.probabilities)
    for state in law.states:
        if state[j] != 0:
            continue
        for bins in ((1, 2, 3), (4, 5, 6)):
            cells = tuple(indices[(*state[:j], k, *state[j + 1 :])] for k in bins)
            short, long, full = (law.probabilities[i] for i in cells)
            if full <= 0:
                continue
            shorter = math.fsum((short, long))
            if shorter <= 0:
                raise ValueError("No same-role shorter support in an affected conditional slice.")
            total = math.fsum((short, long, full))
            for index, old in zip(cells[:2], (short, long), strict=True):
                result[index] = total * (old / shorter)
                if old > 0 and result[index] <= 0:
                    raise ValueError(
                        "No-full-match redistribution lost shorter support numerically."
                    )
            result[cells[2]] = 0.0
    return tuple(result)


def apply_verified_week_evidence(
    law: JointWeekLaw, evidence: tuple[VerifiedWeekEvidence, ...], *, first_gameweek: int
) -> JointWeekLaw:
    """Apply caller-verified first-week claims atomically in native fixture order.

    Absence is a deterministic pushforward with an explicit support exception.
    No-full-match preserves the joint absence/start/cameo vector and uses only
    already-positive same-role destinations in each other-fixture state slice.
    """
    validate_joint_week_law(law)
    _integer(first_gameweek, high=38)
    if type(evidence) is not tuple:
        raise ValueError("Verified evidence must be an immutable tuple.")
    if not evidence:
        return law
    if law.gameweek != first_gameweek:
        raise ValueError("Verified evidence applies only to the first decision week.")
    by_fixture = {f.fixture_id: j for j, f in enumerate(law.fixtures)}
    jobs: dict[int, VerifiedWeekEvidence] = {}
    ids: set[str] = set()
    for item in evidence:
        if type(item) is not VerifiedWeekEvidence or item.kind not in ("absence", "no_full_match"):
            raise ValueError("Verified evidence kind or frozen type is invalid.")
        if (
            not isinstance(item.evidence_id, str)
            or not 1 <= len(item.evidence_id) <= 128
            or not item.evidence_id.strip()
            or item.evidence_id != item.evidence_id.strip()
            or item.evidence_id in ids
        ):
            raise ValueError("Verified evidence identities must be nonblank and unique.")
        _integer(item.player_code)
        _integer(item.gameweek, high=38)
        if (item.player_code, item.gameweek) != (law.player_code, law.gameweek):
            raise ValueError("Verified evidence names another person or week.")
        _digest(item.source_sha256)
        if (
            type(item.fixture_ids) is not tuple
            or not item.fixture_ids
            or any(type(i) is not int for i in item.fixture_ids)
            or len(set(item.fixture_ids)) != len(item.fixture_ids)
        ):
            raise ValueError("Verified evidence requires exact unique nonempty fixture scope.")
        for fixture in item.fixture_ids:
            _integer(fixture)
            if fixture not in by_fixture or by_fixture[fixture] in jobs:
                raise ValueError("Verified evidence has an unknown or overlapping fixture scope.")
            jobs[by_fixture[fixture]] = item
        ids.add(item.evidence_id)
    result = law
    for j, item in sorted(jobs.items()):
        probabilities = _absence(result, j) if item.kind == "absence" else _no_full_match(result, j)
        created = tuple(
            i
            for i, (p, q) in enumerate(zip(result.probabilities, probabilities, strict=True))
            if p == 0 and q > 0
        )
        policy = (
            "verified_absence_pushforward_v1"
            if item.kind == "absence"
            else "same_role_conditional_no_full_match_v1"
        )
        result = _updated(
            result,
            probabilities,
            JointLawStep(
                policy,
                (joint_week_law_digest(result),),
                (("evidence:" + item.evidence_id, item.source_sha256),),
                (law.fixtures[j].fixture_id,),
                created_absent_indices=created,
            ),
        )
    return result


def joint_week_marginals(law: JointWeekLaw) -> JointWeekMarginals:
    validate_joint_week_law(law)
    marginal = _marginals(law.states, law.probabilities, len(law.fixtures))
    return JointWeekMarginals(
        math.fsum(p for state, p in zip(law.states, law.probabilities, strict=True) if any(state)),
        marginal,
        tuple(
            math.fsum(p * m for p, m in zip(values, fixture.minutes, strict=True))
            for values, fixture in zip(marginal, law.fixtures, strict=True)
        ),
        tuple(math.fsum(values[1:4]) for values in marginal),
        tuple(math.fsum(values[4:]) for values in marginal),
    )


def joint_week_law_document(law: JointWeekLaw) -> dict[str, Any]:
    """Return a detached JSON document with the exact digest field inventory."""
    validate_joint_week_law(law)
    return dict(json.loads(json.dumps(asdict(law), allow_nan=False)))


def _object(document: object, cls: Any) -> dict[str, Any]:
    if type(document) is not dict or set(document) != {f.name for f in fields(cls)}:
        raise ValueError("Joint week document has an unexpected field inventory.")
    return dict(document)


def _array(document: object, maximum: int) -> tuple[Any, ...]:
    if type(document) is not list or len(document) > maximum:
        raise ValueError("Joint week document requires bounded JSON arrays.")
    return tuple(document)


def read_joint_week_law_document(document: object) -> JointWeekLaw:
    """Read an exact bounded JSON object; the outer reader rejects duplicate keys."""
    values = _object(document, JointWeekLaw)
    fixtures = []
    for raw in _array(values["fixtures"], 3):
        fixture = _object(raw, LoadFixture)
        fixture["probabilities"] = _array(fixture["probabilities"], 7)
        fixture["minutes"] = _array(fixture["minutes"], 7)
        fixtures.append(LoadFixture(**fixture))
    lineage = []
    for raw in _array(values["lineage"], 32):
        step = _object(raw, JointLawStep)
        step["parents"] = _array(step["parents"], 3)
        step["sources"] = tuple(_array(pair, 2) for pair in _array(step["sources"], 128))
        step["fixture_ids"] = _array(step["fixture_ids"], 3)
        step["created_absent_indices"] = _array(step["created_absent_indices"], 343)
        lineage.append(JointLawStep(**step))
    values.update(
        fixtures=tuple(fixtures),
        states=tuple(_array(row, 3) for row in _array(values["states"], 343)),
        probabilities=_array(values["probabilities"], 343),
        lineage=tuple(lineage),
    )
    law = JointWeekLaw(**values)
    validate_joint_week_law(law)
    return law


def _validate_evidence_document(item: VerifiedWeekEvidence) -> None:
    if type(item) is not VerifiedWeekEvidence or item.kind not in ("absence", "no_full_match"):
        raise ValueError("Verified evidence kind or frozen type is invalid.")
    if (
        not isinstance(item.evidence_id, str)
        or not 1 <= len(item.evidence_id) <= 128
        or item.evidence_id != item.evidence_id.strip()
    ):
        raise ValueError("Verified evidence identity is invalid.")
    _integer(item.player_code)
    _integer(item.gameweek, high=38)
    _digest(item.source_sha256)
    if (
        type(item.fixture_ids) is not tuple
        or not 1 <= len(item.fixture_ids) <= 3
        or any(type(i) is not int for i in item.fixture_ids)
        or len(set(item.fixture_ids)) != len(item.fixture_ids)
    ):
        raise ValueError("Verified evidence requires exact unique nonempty fixture scope.")
    for fixture in item.fixture_ids:
        _integer(fixture)


def verified_week_evidence_document(item: VerifiedWeekEvidence) -> dict[str, Any]:
    _validate_evidence_document(item)
    return dict(json.loads(json.dumps(asdict(item))))


def read_verified_week_evidence_document(document: object) -> VerifiedWeekEvidence:
    values = _object(document, VerifiedWeekEvidence)
    values["fixture_ids"] = _array(values["fixture_ids"], 3)
    item = VerifiedWeekEvidence(**values)
    _validate_evidence_document(item)
    return item
