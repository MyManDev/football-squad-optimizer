"""Per-mode plan choice for one league member, priced on shared scenario paths.

The transfer menu (`plan_transfer_menu`) supplies proven alternatives; the mode selector
(`select_plan`) prices every alternative on the same joint scenario paths and names each
mode's winner. This module is the bridge between the two for a *league member*: their
menu, their rival, one selection.

Two rules are load-bearing:

- **The rival is a real member of the member's own league** — another entry's public
  post-deadline eleven — never the system's own squad. Member advice must be invariant
  to what the system holds (`tests/unit/test_league_views.py` pins this), so the rival
  candidates given to `choose_rival` must come from the league capture, which cannot
  contain the ledger's paper entry.
- **Probabilities are internal ordering signals, not claims.** The scenario model prices
  a named rival at the shared projection with an *unmeasured* edge (the crowd's measured
  +7.19 does not transfer to an arbitrary member), and the windowed-claim line is closed
  (`docs/windowed_rank_note.md`). So `ModeAdvice` deliberately has no probability field:
  what a mode may publish is its expected-points price tag, and everything else stays in
  `MemberModeSelection.diagnostics`, which is never serialized into a site payload.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from squadopt.application.entries import EntryPicks
from squadopt.experiments.plan_selection import (
    CandidatePlan,
    select_plan,
    selection_to_dict,
)
from squadopt.live.transfers import TransferDecision
from squadopt.planning import TransferPlanResult
from squadopt.scenarios import RivalSquad
from squadopt.scenarios.paths import ScenarioPathSet

MEMBER_MODE_SELECTION_CONTRACT_VERSION: Final = "member_mode_selection_v1"

#: The site's mode slugs, keyed by the experiment layer's mode names. The two vocabularies
#: are one concept spelled for different consumers (Python identifiers vs URL segments);
#: this mapping is the single place they meet.
MODE_SLUGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "saf_puan": "saf-puan",
        "garantici": "garantici",
        "agresif": "agresif",
        "asiri_agresif": "asiri-agresif",
    }
)

PURE_POINTS_MODE: Final = "saf_puan"


class ModeSelectionError(ValueError):
    """Raised when a mode selection is asked for something it cannot honestly answer."""


@dataclass(frozen=True, slots=True)
class ModeAdvice:
    """One mode's chosen plan, priced in expected points only.

    ``expected_points_cost`` is what following this mode gives up against the pure-points
    pick on the same paths — the only number of these that belongs on a site page.
    There is deliberately no probability field; see the module docstring.
    """

    mode: str
    """The site slug (`MODE_SLUGS` value), not the experiment layer's key."""
    plan_index: int
    """0-based index into the menu this advice chose from."""
    decision: TransferDecision
    expected_window_score: float
    expected_points_cost: float
    rival_label: str | None

    def __post_init__(self) -> None:
        if self.mode not in MODE_SLUGS.values():
            raise ModeSelectionError(f"Unknown mode slug {self.mode!r}.")
        if self.plan_index < 0:
            raise ModeSelectionError("plan_index must be non-negative.")


@dataclass(frozen=True, slots=True)
class MemberModeSelection:
    """Every computed mode's advice for one member, plus the internal diagnostics."""

    contract_version: str
    gameweek: int
    advice: tuple[ModeAdvice, ...]
    diagnostics: Mapping[str, object]
    """Internal only — carries the raw selection record including probabilities.
    Nothing here may reach a published payload; the site ships price tags."""

    def by_mode(self) -> Mapping[str, ModeAdvice]:
        return MappingProxyType({item.mode: item for item in self.advice})


def rival_squad_from_picks(picks: EntryPicks, *, label: str) -> RivalSquad:
    """A member's public eleven as the fixed rival the scenario scorer prices."""

    return RivalSquad(
        label=label,
        starter_ids=tuple(picks.starting_xi),
        captain_id=picks.captain,
    )


def choose_rival(
    entry_id: int,
    ranks: Mapping[int, int],
    candidates: Mapping[int, RivalSquad],
) -> RivalSquad | None:
    """The standings neighbour the competitive modes are priced against.

    The rule, pinned by test rather than left to a run's mood: the nearest ranked member
    *above* (the one this member is chasing); the leader, having nobody above, takes the
    nearest member below (the one they are defending against). A member outside the
    standings, or with no ranked candidate but themselves, gets ``None`` — and the caller
    computes the pure-points mode only, rather than inventing a rival.

    ``candidates`` must not contain the member's own entry or the system's squad; the
    provider builds it from the league capture, which contains neither.
    """

    if entry_id in candidates:
        raise ModeSelectionError(
            f"Entry {entry_id} appears in its own rival candidates; a member is never "
            "their own rival."
        )
    own_rank = ranks.get(entry_id)
    if own_rank is None:
        return None
    ranked = sorted(
        (rank, candidate_id)
        for candidate_id, rank in ranks.items()
        if candidate_id != entry_id and candidate_id in candidates
    )
    if not ranked:
        return None
    above = [(rank, candidate_id) for rank, candidate_id in ranked if rank < own_rank]
    _, candidate_id = above[-1] if above else ranked[0]
    return candidates[candidate_id]


def select_member_modes(
    menu: Sequence[tuple[TransferPlanResult, TransferDecision]],
    paths: ScenarioPathSet,
    rival: RivalSquad | None,
    *,
    rival_edge_points_per_week: float = 0.0,
) -> MemberModeSelection:
    """Price the member's menu on the paths and name each mode's plan.

    ``rival_edge_points_per_week`` defaults to zero because no per-member edge has been
    measured; the default is recorded in the diagnostics as the unmeasured assumption it
    is. Without a rival the rival-aware modes are absent rather than faked — the same
    honesty `select_plan` already enforces.

    The window is one week for now: the menu's plans are single-deadline plans, and the
    windowed crowd-relative machinery stays a diagnostic. A wider path set is refused
    here rather than half-supported.
    """

    if not menu:
        raise ModeSelectionError("A mode selection needs at least one menu entry.")
    if len(paths.target.gameweeks) != 1:
        raise ModeSelectionError(
            "Member mode selection prices one deadline; a wider window is not published."
        )
    gameweek = int(paths.target.gameweeks[0])
    candidates = tuple(
        CandidatePlan(label=f"plan_{index + 1:02d}", plan=result)
        for index, (result, _) in enumerate(menu)
    )
    index_by_label = {candidate.label: index for index, candidate in enumerate(candidates)}
    selection = select_plan(
        candidates,
        paths,
        rival,
        rival_edge_points_per_week=rival_edge_points_per_week,
    )
    scores = {
        (verdict.mode, verdict.candidate): float(verdict.expected_window_score)
        for verdict in selection.verdicts
    }
    pure_label = selection.recommended[PURE_POINTS_MODE]
    pure_score = scores[(PURE_POINTS_MODE, pure_label)]
    advice: list[ModeAdvice] = []
    for mode_name, winner_label in selection.recommended.items():
        winner_index = index_by_label[winner_label]
        rival_aware = mode_name != PURE_POINTS_MODE and rival is not None
        advice.append(
            ModeAdvice(
                mode=MODE_SLUGS[mode_name],
                plan_index=winner_index,
                decision=menu[winner_index][1],
                expected_window_score=scores[(mode_name, winner_label)],
                expected_points_cost=pure_score - scores[(mode_name, winner_label)],
                rival_label=rival.label if rival_aware and rival is not None else None,
            )
        )
    diagnostics: dict[str, object] = {
        "selection": selection_to_dict(selection),
        "rival_edge_points_per_week": float(rival_edge_points_per_week),
        "rival_edge_note": (
            "The per-member rival edge is unmeasured; zero is an assumption, so the "
            "selection's probabilities are internal ordering signals, never published."
        ),
    }
    return MemberModeSelection(
        contract_version=MEMBER_MODE_SELECTION_CONTRACT_VERSION,
        gameweek=gameweek,
        advice=tuple(advice),
        diagnostics=MappingProxyType(diagnostics),
    )
