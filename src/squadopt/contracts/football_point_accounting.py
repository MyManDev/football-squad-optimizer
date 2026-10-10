"""Raw football point algebra for explicitly supplied unconditional moments.

The caller owns source admission, scoring weights, distributions, eligibility and
the level at which clipping occurs. In particular, ``residual_expected_points``
is already unconditional: a native conditional residual is converted with q * r
by the caller. An independently declared zero-minute contribution can remain in
that residual, but this module does not define its autosub or appearance policy.
"""

from dataclasses import dataclass, field
from math import fsum, isfinite, ulp
from numbers import Real


def _number(value: object, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite real number, not a Boolean.")
    if not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number, not {type(value).__name__}.")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite real number.") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be finite.")
    if nonnegative and result < 0:
        raise ValueError(f"{name} must be nonnegative.")
    return result


def _product(left: float, right: float, name: str) -> float:
    result = left * right
    if not isfinite(result):
        raise ValueError(f"{name} overflowed finite point support.")
    return result


@dataclass(frozen=True, slots=True)
class PointCoefficients:
    """Caller-selected point weights, with no inferred season or rules policy."""

    short_play: float
    long_play: float
    goals: float
    assists: float
    clean_sheet: float
    defcon: float

    def __post_init__(self) -> None:
        for name in ("short_play", "long_play", "goals", "assists", "clean_sheet", "defcon"):
            object.__setattr__(
                self, name, _number(getattr(self, name), f"coefficient.{name}", nonnegative=True)
            )


@dataclass(frozen=True, slots=True)
class ComponentMoments:
    """One declared scoring scope's first moments, before external eligibility.

    q denotes positive credited-minute appearance. p60 and the clean-sheet moment
    include their own qualifying appearance mass; DEFCON is an unconditional
    award-event probability. Goals and assists are unconditional expected counts,
    which need not be at most q. The signed residual is already unconditional.
    An explicit support_roundoff budget can admit tiny differences in nested
    moments from binary arithmetic. It never changes supplied values or admits
    an activity at an exactly zero appearance or clean-sheet support boundary.
    """

    appearance_probability: float
    p60: float
    goals: float
    assists: float
    clean_sheet_probability: float
    defcon_probability: float
    residual_expected_points: float
    support_roundoff: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "appearance_probability",
            "p60",
            "clean_sheet_probability",
            "defcon_probability",
        ):
            value = _number(getattr(self, name), f"moment.{name}", nonnegative=True)
            if value > 1:
                raise ValueError(f"moment.{name} must lie in [0, 1].")
            object.__setattr__(self, name, value)
        for name in ("goals", "assists"):
            object.__setattr__(
                self, name, _number(getattr(self, name), f"moment.{name}", nonnegative=True)
            )
        object.__setattr__(
            self,
            "residual_expected_points",
            _number(self.residual_expected_points, "moment.residual_expected_points"),
        )
        budget = _number(self.support_roundoff, "moment.support_roundoff", nonnegative=True)
        if budget > 4 * ulp(1.0):
            raise ValueError("moment.support_roundoff cannot exceed four ulps of 1.0.")
        object.__setattr__(self, "support_roundoff", budget)
        if self.appearance_probability == 0 and (
            self.p60 != 0 or self.clean_sheet_probability != 0 or self.defcon_probability != 0
        ):
            raise ValueError(
                "Zero appearance_probability requires zero p60, CS and DEFCON support."
            )
        if self.p60 == 0 and self.clean_sheet_probability != 0:
            raise ValueError("Zero p60 requires zero clean_sheet_probability support.")
        if self.p60 - self.appearance_probability > budget:
            raise ValueError("moment.p60 cannot exceed appearance_probability.")
        if self.clean_sheet_probability - self.p60 > budget:
            raise ValueError("moment.clean_sheet_probability cannot exceed p60.")
        if self.defcon_probability - self.appearance_probability > budget:
            raise ValueError("moment.defcon_probability cannot exceed appearance_probability.")
        if self.appearance_probability == 0 and (self.goals != 0 or self.assists != 0):
            raise ValueError("Goal and assist counts require positive-minute appearance support.")


@dataclass(frozen=True, slots=True)
class RawPointResult:
    """Immutable input and contribution receipt, with no clipping or averaging."""

    moments: ComponentMoments
    coefficients: PointCoefficients
    short_play_points: float = field(init=False)
    long_play_points: float = field(init=False)
    goal_points: float = field(init=False)
    assist_points: float = field(init=False)
    clean_sheet_points: float = field(init=False)
    defcon_points: float = field(init=False)
    residual_points: float = field(init=False)
    raw_expected_points: float = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.moments, ComponentMoments):
            raise ValueError("moments must be a validated ComponentMoments record.")
        if not isinstance(self.coefficients, PointCoefficients):
            raise ValueError("coefficients must be a validated PointCoefficients record.")
        m, c = self.moments, self.coefficients
        terms = (
            ("short_play_points", c.short_play, m.appearance_probability - m.p60),
            ("long_play_points", c.long_play, m.p60),
            ("goal_points", c.goals, m.goals),
            ("assist_points", c.assists, m.assists),
            ("clean_sheet_points", c.clean_sheet, m.clean_sheet_probability),
            ("defcon_points", c.defcon, m.defcon_probability),
        )
        for name, coefficient, moment in terms:
            object.__setattr__(self, name, _product(coefficient, moment, name))
        object.__setattr__(self, "residual_points", m.residual_expected_points)
        try:
            total = fsum(
                (
                    self.short_play_points,
                    self.long_play_points,
                    self.goal_points,
                    self.assist_points,
                    self.clean_sheet_points,
                    self.defcon_points,
                    self.residual_points,
                )
            )
        except OverflowError as exc:
            raise ValueError("Raw point summation overflowed finite point support.") from exc
        if not isfinite(total):
            raise ValueError("Raw point summation must remain finite.")
        object.__setattr__(self, "raw_expected_points", total)


def raw_points(moments: ComponentMoments, coefficients: PointCoefficients) -> RawPointResult:
    """Score supplied moments once, without applying q to counts or the residual."""
    return RawPointResult(moments, coefficients)


def clip_points(raw: float) -> float:
    """Explicit nonnegative clipping at the caller's declared scoring scope.

    Clipping a mixture's mean and averaging clipped conditional values generally
    differ. This function performs neither mixture operation nor normalization.
    """
    return max(0.0, _number(raw, "raw points"))


__all__ = (
    "ComponentMoments",
    "PointCoefficients",
    "RawPointResult",
    "clip_points",
    "raw_points",
)
