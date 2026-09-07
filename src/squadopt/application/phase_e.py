"""Reviewed calibration identities and internal member-transfer diagnostics."""

from collections.abc import Callable, Sequence
from typing import Final

from squadopt.live.transfers import HeldSquad
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.models import ScenarioValidationError
from squadopt.scenarios.transfer_decisions import (
    TransferDecisionCandidate,
    TransferPlanLike,
    TransferScenarioSelection,
    TransferStartState,
    evaluate_transfer_candidates,
    transfer_candidate_from_plan,
)

# Pairs of (Phase C model_version, component sampler contract version). The foundation
# sampler's contract string is the component inputs contract; a candidate sampler names its
# own, so a pin for one sampler never admits a draw from another.
# Populate only in a reviewed change citing the binding Phase D artifact whose
# verdict.status is calibrated_internal. This does not enable a live decision path.
PHASE_E_CALIBRATED_VERSIONS: Final[tuple[tuple[str, str], ...]] = ()

TransferAdviceEvaluator = Callable[
    [Sequence[TransferPlanLike], ComponentScenarioDraw | None], TransferScenarioSelection
]
TransferAdviceDiagnostic = Callable[
    [TransferDecisionCandidate, TransferStartState, TransferAdviceEvaluator], None
]


def run_transfer_advice_diagnostic(
    plan: TransferPlanLike,
    held: HeldSquad,
    *,
    gameweek: int,
    transfer_hit_cost_points: float,
    diagnostic: TransferAdviceDiagnostic | None,
) -> None:
    """Offer a pinned, internal evaluator around the already-solved control.

    The hook supplies alternative planner results and one shared draw to ``evaluate`` and
    owns recording its returned diagnostic. Neither this function nor that result replaces
    the member's advice: a full-pool calibration pin is not member-transfer promotion.
    With no pin or hook, even adaptation and the hook's menu/draw work are skipped.
    """

    if not PHASE_E_CALIBRATED_VERSIONS or diagnostic is None:
        return
    if gameweek != held.decided_gameweek + 1:
        raise ScenarioValidationError("Transfer advice must target the held squad's next gameweek.")
    start_state = TransferStartState(
        season=held.season,
        gameweek=gameweek,
        squad_player_ids=held.squad_player_ids,
        bank_tenths=held.bank_tenths,
        free_transfers=held.free_transfers,
    )
    control = transfer_candidate_from_plan(plan, label="control", gameweek=gameweek)

    def evaluate(
        alternatives: Sequence[TransferPlanLike], draw: ComponentScenarioDraw | None
    ) -> TransferScenarioSelection:
        if draw is not None and draw.inputs.provenance.development_contract is not None:
            raise ScenarioValidationError("Development draws cannot evaluate production advice.")
        candidates = (
            control,
            *(
                transfer_candidate_from_plan(
                    alternative, label=f"candidate-{rank}", gameweek=gameweek
                )
                for rank, alternative in enumerate(alternatives, start=1)
            ),
        )
        return evaluate_transfer_candidates(
            candidates,
            draw,
            start_state=start_state,
            transfer_hit_cost_points=transfer_hit_cost_points,
            calibrated_versions=PHASE_E_CALIBRATED_VERSIONS,
        )

    diagnostic(control, start_state, evaluate)
