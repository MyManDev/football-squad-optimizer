"""Player vocabulary shared by data, prediction, and optimization."""

from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from typing import Literal, TypeAlias

import pandas as pd

Position: TypeAlias = Literal["GK", "DEF", "MID", "FWD"]
POSITIONS: tuple[Position, ...] = ("GK", "DEF", "MID", "FWD")
REQUIRED_COLUMNS: tuple[str, ...] = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "expected_points",
)

#: Recognised names a projection may carry and need not. Absent fields are never fabricated.
#:
#: The tier exists because the alternative breaks a week rather than narrowing it: a required
#: column means every producer must supply it, so a projection without a start probability
#: would stop being a projection and become an error, and a member whose week the model has no
#: opinion about would get no plan instead of the plan they get today. Absent is not zero and
#: absent is not broken.
#:
#: **A consumer that meets an absent optional column applies its existing rule unchanged.**
#: Reading a missing start probability as zero would bench every player nobody modelled, which
#: is a larger behaviour change than supplying the column at all, and in the wrong direction.
#:
#: ``start_probability`` is the probability the player starts, which the pre-registration
#: writes as ``p_start = p_appearance * q_start_given_appearance``
#: (``docs/participation_model_prereg.md``) -- the composition, not the conditional ``q`` the
#: model fits. The name is the one the component prediction contract already uses
#: (``prediction/components.py``), where the column exists and is deliberately left absent:
#: ``start_component_status`` returns ``"unavailable"`` and no component row estimates it. One
#: quantity keeps one name across the boundary it crosses, so the day that column carries a
#: number it does not have to be renamed to reach the solve.
#:
#: Nothing produces ``start_probability`` into a live projection today, so it is named here
#: and carried by nobody. The only non-absent values it takes are the zeros a blank gameweek
#: writes into every number of its row, which say that a player who is not playing will not
#: start rather than anything a model estimated; ``projection_handoff._carried`` is where that
#: distinction is drawn.
#:
#: ``appearance_probability`` is the chance the player appears at all, substitute included, and
#: it is the one the bench rule actually needs (#531). The exchange argument is short enough to
#: keep here: the game walks the bench and skips a player who did not appear, so a bench player
#: who is absent costs nothing and the first slot should hold whoever is worth most **if** they
#: appear. Between two players the difference between the two orders is ``p1 * p2 * (c1 - c2)``,
#: whose sign is the sign of ``c1 - c2``, so the order is by points given an appearance,
#: ``expected_points / appearance_probability``. Dividing by ``start_probability`` instead would
#: send a likely cameo to the top, which is the opposite of the intent. The component prediction
#: contract already carries both names, and this one already carries numbers.
OPTIONAL_COLUMNS: tuple[str, ...] = ("appearance_probability", "start_probability")

#: Every recognised projection column, required first then optional. The shape ``data/schema``
#: has carried one layer down since it was written, now that the projection needs it too.
CANONICAL_COLUMNS: tuple[str, ...] = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)


def identifier_sort_key(value: object) -> tuple[int, str]:
    """A total order over player ids that mixes integers and text without raising.

    Integers sort ahead of anything else and among themselves numerically, through a
    fixed-width signed spelling rather than by value, so the key is comparable with the
    text branch. Shared rather than duplicated because it is the tiebreak of every
    ordering the decision path freezes, and two spellings of one tiebreak are two orders.
    """

    if isinstance(value, Integral) and not isinstance(value, bool):
        return (0, f"{int(value):+030d}")
    return (1, str(value))


def _decimal(value: object) -> Decimal | None:
    """A finite ``Decimal`` for a real number, or ``None`` for anything else.

    ``None``, ``pd.NA``, a NaN, an infinity, a boolean and a string all return ``None``.
    The caller decides what an unusable value means; this only says it is unusable.
    """

    if value is None or value is pd.NA or isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = Decimal(str(value))
    except (ArithmeticError, InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def order_outfield_bench(bench_outfield: pd.DataFrame) -> pd.DataFrame:
    """Order the outfield bench by what each player is worth given that they appear.

    The argument for the rule is written above :data:`OPTIONAL_COLUMNS` and is not repeated
    here: the game walks the bench and skips a player who did not appear, so the first slot
    should hold whoever is worth most **if** they are there, which is
    ``expected_points / appearance_probability``.

    **The bench goalkeeper is not passed in.** Their slot is fixed by the rules, so their
    chance cannot change any ordering, and letting it in would mean their missing chance
    could drop the whole bench back to the fallback for no reason.

    **The conditional order applies only when every outfield row can be divided.** The
    column must be there and each row must hold a real, finite, strictly positive number.
    Otherwise the whole bench falls back to descending ``expected_points``. Both branches
    break ties on :func:`identifier_sort_key`.

    Falling back as a whole rather than per row is the substantive decision, and it is not
    tidiness. A bench of three outfielders where two are modelled and one is not is an
    ordinary case, because the direct-control route leaves its component inputs absent by
    contract. Ordering that bench per row would put ``(2.0, p=0.5) -> 4.0`` ahead of
    ``(3.0, no p) -> 3.0``, which is right only if the second player's true chance is near
    one; at 0.3 their conditional value is 10.0 and the order is badly inverted. Per row is
    not "use what is available", it is silently substituting ``p = 1`` where nothing is
    known, and the substitution lands on exactly the players no model has an opinion about.
    It is also two quantities in one sort key: a conditional mean beside an unconditional
    one is arithmetically defined and answers no question. Forfeiting a re-ranking among
    three players is the cheaper mistake.

    A value above one is deliberately **not** refused. Nothing validates this column, so a
    rule here could only guess at which numbers are wrong; 1.2 divides as well as 0.9 and
    may be no more wrong. Refusing it would tie a frozen bench order to a threshold no
    contract declares and would hide a producer defect inside a sort. What is refused is
    what cannot be divided by, not what looks implausible.

    Arithmetic is ``Decimal`` throughout. The optimizer holds floats and the official
    scorer holds ``Decimal``, and today they agree because ``Decimal(str(f))`` preserves
    the order of floats. Division does not preserve it: the same pair divided as ``float``
    and as ``Decimal`` can differ in the last place and invert a near tie, which would make
    a decision and its own completion disagree about a bench. One arithmetic in one place
    removes the question. The returned frame's own dtypes are untouched.
    """

    points = [_decimal(value) for value in bench_outfield["expected_points"].tolist()]
    chances: list[Decimal | None] = []
    if "appearance_probability" in bench_outfield.columns:
        chances = [_decimal(value) for value in bench_outfield["appearance_probability"].tolist()]
    conditional = len(chances) == len(points) and all(
        chance is not None and chance > 0 for chance in chances
    )
    identifiers = bench_outfield["player_id"].tolist()

    def key(index: int) -> tuple[Decimal, tuple[int, str]]:
        total = points[index] or Decimal(0)
        chance = chances[index] if conditional else None
        worth = total / chance if chance is not None else total
        return (-worth, identifier_sort_key(identifiers[index]))

    order = sorted(range(len(bench_outfield)), key=key)
    return bench_outfield.iloc[order].reset_index(drop=True).copy(deep=True)


def canonical_columns_present(players: pd.DataFrame) -> list[str]:
    """The required columns, then whichever optional ones this frame actually carries.

    What a narrowing point wants: it must not drop an optional column the producer supplied,
    and it must not invent one the producer left out. Column order is the contract's, not the
    frame's, so two frames carrying the same columns narrow to the same shape.
    """

    return [*REQUIRED_COLUMNS, *(name for name in OPTIONAL_COLUMNS if name in players.columns)]


def sort_players_by_id(players: pd.DataFrame) -> pd.DataFrame:
    """Return the stable player ordering used by the model and its fingerprints."""

    player_ids = players["player_id"].tolist()
    if player_ids and isinstance(player_ids[0], Integral):
        order = sorted(range(len(players)), key=lambda index: int(player_ids[index]))
    else:
        order = sorted(range(len(players)), key=lambda index: str(player_ids[index]))
    return players.iloc[order].reset_index(drop=True).copy(deep=True)
