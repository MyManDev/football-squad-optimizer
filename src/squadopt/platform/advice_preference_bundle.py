"""Sequential preference computation inside one already admitted backend job."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from squadopt.application.advice_menu import MenuRequest
from squadopt.contracts.llmopt_run import job_capacity
from squadopt.contracts.preference_bundle import (
    BUNDLE_SWITCH,
    PreferenceBundle,
    PreferenceSelection,
)
from squadopt.contracts.preferences import DecisionPreferences, FrozenPlanWeek
from squadopt.contracts.priority_preferences import PriorityProgram, PriorityReference
from squadopt.optimization.work_budget import (
    WorkBudget,
    WorkBudgetExhausted,
    current_work_budget,
    work_budget,
)
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_documents import validate_advice_document
from squadopt.platform.advice_job_spec import AdviceJobSpec, AdviceJobSpecStore
from squadopt.platform.advice_queue import AdviceComputeRefused
from squadopt.platform.advice_switches import SwitchIdentity, switch_identity
from squadopt.platform.capture_context import AdviceCaptureContext
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.public_entry_inputs import PUBLIC_ENTRY_SWITCH

ComputeComponent = Callable[
    [AdviceJob, AdviceJobSpec, PriorityProgram | None, PriorityReference | None], bytes
]


def _key(spec: AdviceJobSpec, switches: SwitchIdentity) -> str:
    context = spec.context
    return advice_cache_key(
        advice_contract_version=context.advice_contract_version,
        capture_snapshot_id=context.capture_snapshot_id,
        season=context.season,
        gameweek=context.gameweek,
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        projection_handoff_fingerprint=context.projection_handoff_fingerprint,
        repository_commit=context.repository_commit,
        configuration_fingerprint=context.configuration_fingerprint,
        rival_entry_id=spec.rival_entry_id,
        strategy_uses_rival=False,
        switches=switches,
    )


def _net(payload: Mapping[str, Any], window: int) -> float:
    rows = payload.get("plan_weeks")
    if not isinstance(rows, list) or len(rows) != window:
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "The main plan is incomplete.")
    try:
        value = sum(
            float(row["expected_points"]) - float(row["transfer_hit_points"]) for row in rows
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AdviceComputeRefused(
            "REQUEST_UNREADABLE", "The computed score is unreadable."
        ) from error
    if not math.isfinite(value):
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "The computed score is not finite.")
    return value


def _reference(payload: Mapping[str, Any], spec: AdviceJobSpec) -> PriorityReference:
    rows = payload["plan_weeks"]
    try:
        weeks = tuple(
            FrozenPlanWeek(
                week=row["gameweek"] - spec.context.gameweek + 1,
                transfers_in=tuple(item["player_id"] for item in row["transfers_in"]),
                transfers_out=tuple(item["player_id"] for item in row["transfers_out"]),
                chip=row.get("chip"),
                starting_xi=tuple(item["player_id"] for item in row["lineup"]["starting_xi"]),
                captain=row["lineup"]["captain"]["player_id"],
            )
            for row in rows
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AdviceComputeRefused(
            "REQUEST_UNREADABLE", "The cached reference is incomplete."
        ) from error
    # Unknown old proof stays unproved. The fixed-path certificate cannot upgrade it.
    return PriorityReference(weeks, proved=payload.get("solver_status") == "OPTIMAL")


def compute_preference_bundle(
    job: AdviceJob,
    spec: AdviceJobSpec,
    request: MenuRequest,
    capture: AdviceCaptureContext,
    cache: AdviceCacheRepository | None,
    specs: AdviceJobSpecStore,
    compute: ComputeComponent,
) -> bytes:
    parent = current_work_budget()
    if parent is None or cache is None:
        raise AdviceComputeRefused("RUN_STORE_UNAVAILABLE", "Preference execution is unavailable.")
    identity = spec.switch(BUNDLE_SWITCH)
    encoded, base_key = identity.get("request"), identity.get("base_key")
    if not isinstance(encoded, str) or not isinstance(base_key, str):
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "Invalid preference execution identity.")
    bundle = PreferenceBundle.parse(json.loads(encoded))
    base_switches = {
        name: dict(value) for name, value in spec.switches.items() if name != BUNDLE_SWITCH
    }
    if _key(spec, base_switches) != base_key:
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "The main reference identity changed.")
    raw = cache.get(base_key)
    if raw is None:
        raise AdviceComputeRefused("RUN_BASE_REQUIRED", "Compute the main plan first.")
    validate_advice_document(raw)
    document = json.loads(raw)
    main = document["payload"]
    for name, expected in (
        ("league_id", spec.league_id),
        ("entry_id", spec.entry_id),
        ("window", spec.window),
        ("gameweek", spec.context.gameweek),
        ("season", spec.context.season),
        ("mode", spec.strategy),
    ):
        if main.get(name) != expected:
            raise AdviceComputeRefused("REQUEST_UNREADABLE", "The cached main plan has changed.")
    if DecisionPreferences.parse(main.get("preferences", {})) != request.preferences:
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "The main preferences have changed.")
    baseline = _net(main, spec.window)
    exhausted = False

    def component(
        selection: PreferenceSelection,
        program: PriorityProgram | None = None,
    ) -> dict[str, Any]:
        nonlocal exhausted
        preferences = selection.expand(request.preferences)
        switches = switch_identity(
            capture.switches,
            top100_weight=request.top100_weight,
            managers_word=request.managers_word,
            model=str(spec.switch("model").get("name", "current")),
            chip=selection.chip,
            preferences=preferences,
        )
        if PUBLIC_ENTRY_SWITCH in spec.switches:
            switches[PUBLIC_ENTRY_SWITCH] = dict(spec.switch(PUBLIC_ENTRY_SWITCH))
        child_spec = replace(spec, switches=switches)
        key = _key(child_spec, switches)
        if program is None:
            held = cache.get(key)
            if held is not None:
                validate_advice_document(held)
                return {
                    "status": "done",
                    "payload": json.loads(held)["payload"],
                    "error_code": None,
                }
        allowance = job_capacity(spec.window)
        if parent.remaining < allowance:
            exhausted = True
            return {"status": "exhausted", "payload": None, "error_code": "RUN_BUDGET_EXHAUSTED"}
        child_budget = WorkBudget(allowance)
        try:
            if program is None:
                specs.put(key, child_spec)
            with work_budget(child_budget):
                result = compute(
                    replace(job, cache_key=key, request_fingerprint=key),
                    child_spec,
                    program,
                    _reference(main, spec) if program is not None else None,
                )
            validate_advice_document(result)
            if program is None:
                cache.put(key, result)
            return {"status": "done", "payload": json.loads(result)["payload"], "error_code": None}
        except WorkBudgetExhausted:
            exhausted = True
            return {"status": "exhausted", "payload": None, "error_code": "RUN_BUDGET_EXHAUSTED"}
        except AdviceComputeRefused as error:
            return {
                "status": "failed",
                "payload": None,
                "error_code": error.code,
                **(
                    {"infeasibility": error.infeasibility}
                    if error.infeasibility is not None
                    else {}
                ),
            }
        finally:
            parent.cp_used += child_budget.cp_used
            parent.native_reserved += child_budget.native_reserved
            parent.calls += child_budget.calls

    components: list[dict[str, Any]] = [
        component(selection)
        if selection is not None
        else {"status": "unavailable", "payload": None, "error_code": "PLAN_NOT_FOUND"}
        for selection in bundle.slots
    ]
    selected: dict[str, Any] | None = None
    applied: list[int] = []
    accepted = 0
    if bundle.program is not None:
        selection = PreferenceSelection.parse({"preferences": {}, "chip": request.chip})
        selected = component(selection, bundle.program)
    else:
        for index, price in enumerate(bundle.prices):
            if price.outcome == "same":
                accepted |= 1 << index
            elif type(price.outcome) is int:
                result = components[price.outcome]
                if result["status"] == "done":
                    cost = max(0.0, baseline - _net(result["payload"], spec.window))
                    if price.ceiling is None or cost - price.ceiling / 10 <= 1e-9:
                        accepted |= 1 << index
        choice = next((row for row in bundle.choices if row.accepted == accepted), None)
        if bundle.choices and choice is None:
            raise AdviceComputeRefused("REQUEST_UNREADABLE", "Missing preference combination.")
        if choice is not None and choice.selection is not None:
            selected = component(choice.selection)
            if selected["status"] == "done":
                applied = list(choice.applied)
    document["payload"] = {
        **main,
        "preference_bundle_result": {
            "contract_version": "llmopt_preference_result_v1",
            "request": bundle.payload(),
            "components": components,
            "selected": selected,
            "applied": applied,
            "accepted": accepted,
            "budget_exhausted": exhausted,
        },
    }
    encoded_result = json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    validate_advice_document(encoded_result)
    return encoded_result
