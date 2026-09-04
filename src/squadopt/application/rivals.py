"""Where rivals come from, behind one seam the product can grow into.

The product's competitive modes — Garantici, Agresif, Asiri Agresif — play against rivals
in the manager's own league. Where those rivals come from will change over the season:
today the only source that needs no new data is the ownership template (the crowd's
most-owned eleven, built from the capture); once the league payloads exist, a manager's
league number resolves to real named rivals through the FPL API.

This module is the seam between those stages. :class:`LeagueRivalProvider` is the shape
every source presents — a label saying where the rivals came from, and the rivals — and
:class:`TemplateRivalProvider` is its first implementation. A real league provider becomes
one more class here, built on a captured league payload, and nothing that consumes rivals
has to notice the difference.

Deliberately not here: the fetch. Capturing a league payload is a data-source concern
(`data/sources/`), owned by the data side, with the same snapshot discipline every other
capture follows. This layer consumes captures; it does not make them.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, Protocol

import pandas as pd

from squadopt.application.league import ownership_by_player
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, player_snapshot
from squadopt.optimization import OptimizationConfig
from squadopt.scenarios.evaluation import RivalSquad
from squadopt.scenarios.models import ScenarioValidationError
from squadopt.scenarios.rivals import (
    TEMPLATE_RIVAL_LABEL,
    template_rival_diagnostics,
    template_rival_from_ownership,
)

TEMPLATE_RIVAL_SOURCE: Final = "ownership-template"


class LeagueRivalProvider(Protocol):
    """One source of rivals: a label for provenance, and the rivals themselves."""

    @property
    def source(self) -> str:
        """Where these rivals came from, for display and for artifacts."""
        ...

    def rivals(self) -> tuple[RivalSquad, ...]:
        """The rivals this source currently knows, in a stable order."""
        ...


@dataclass(frozen=True)
class TemplateRivalProvider:
    """The crowd as a single rival, built from a capture's ownership figures.

    Needs nothing beyond a stored capture: the player pool comes from the bootstrap
    payload, ownership from ``selected_by_percent``, both keyed by the persistent player
    code. The provider is deterministic — the same capture always yields the same rival.
    """

    snapshot: CapturedSnapshot
    optimization_config: OptimizationConfig | None = None

    @property
    def source(self) -> str:
        return TEMPLATE_RIVAL_SOURCE

    def rivals(self) -> tuple[RivalSquad, ...]:
        return (self._build()[0],)

    def diagnostics(self) -> dict[str, object]:
        """The template's composition plus the capture it was built from."""

        rival, pool = self._build()
        return {
            **dict(template_rival_diagnostics(pool, rival)),
            "snapshot_id": self.snapshot.metadata.snapshot_id,
            "captured_at_utc": self.snapshot.metadata.captured_at_utc,
        }

    def _build(self) -> tuple[RivalSquad, pd.DataFrame]:
        if BOOTSTRAP_PAYLOAD not in self.snapshot.payloads:
            raise ScenarioValidationError(f"The capture carries no {BOOTSTRAP_PAYLOAD!r} payload.")
        bootstrap = self.snapshot.payloads[BOOTSTRAP_PAYLOAD]
        pool = player_snapshot(bootstrap).loc[:, ["player_id", "position"]].copy()
        ownership = ownership_by_player(self.snapshot)
        pool["ownership"] = [float(ownership.get(int(player), 0.0)) for player in pool["player_id"]]
        rival = template_rival_from_ownership(
            pool,
            label=TEMPLATE_RIVAL_LABEL,
            optimization_config=self.optimization_config,
        )
        return rival, pool


def iter_rivals(providers: Iterator[LeagueRivalProvider]) -> Iterator[RivalSquad]:
    """Flatten several sources into one rival stream, provenance preserved in labels."""

    for provider in providers:
        yield from provider.rivals()


__all__ = [
    "TEMPLATE_RIVAL_SOURCE",
    "LeagueRivalProvider",
    "TemplateRivalProvider",
    "iter_rivals",
]
