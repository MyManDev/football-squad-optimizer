"""Synthetic player pools for optimizer tests: small ones, and one the size of the real."""

import random

import pandas as pd

# The recorded opening-gameweek pool (``data/ledger/2026-27/gw01/projections.csv``, which
# is not tracked) measures 600 players over 20 clubs: 67 GK, 198 DEF, 263 MID, 72 FWD,
# prices quantised to multiples of five between 40 and 155 with 81.5% at or below 55, and
# expected points from 0.0 to 6.17 in 322 distinct scaled values -- so several dozen
# players share an exact value and the primal-optimal set is large. ``make_full_size_players``
# reproduces that shape, because a 24-player pool solves in milliseconds and cannot say
# anything about whether the live budget is enough for the pool the live path actually gets.
FULL_SIZE_POSITION_COUNTS: tuple[tuple[str, int], ...] = (
    ("GK", 67),
    ("DEF", 198),
    ("MID", 263),
    ("FWD", 72),
)
#: ``(price_tenths, weight)``, the recorded pool's own price histogram.
FULL_SIZE_PRICE_LADDER: tuple[tuple[int, int], ...] = (
    (40, 70),
    (45, 133),
    (50, 173),
    (55, 113),
    (60, 56),
    (65, 25),
    (70, 8),
    (75, 10),
    (80, 6),
    (90, 2),
    (100, 2),
    (120, 2),
)
#: Expected points are quantised onto half-point steps, which makes many squads reach the
#: same objective value and gives the lexicographic tie-break real work to do. The recorded
#: pool's own clustering is looser than this, so the fixture is the harder of the two.
FULL_SIZE_POINT_STEPS = 2
FULL_SIZE_SEED = 9


def make_full_size_players() -> pd.DataFrame:
    """Return a 600-player pool shaped like the recorded opening-gameweek one.

    Deterministic: ``random.Random`` seeded once, and only ``randrange``/``random`` drawn
    from it, so every machine and every run builds the same frame. Prices come from the
    recorded histogram and expectation rises with price, so the budget binds at the optimum
    the way it does on the real pool rather than leaving the knapsack slack.
    """

    rng = random.Random(FULL_SIZE_SEED)
    total_weight = sum(weight for _, weight in FULL_SIZE_PRICE_LADDER)
    records: list[dict[str, object]] = []
    player_id = 0
    for position, count in FULL_SIZE_POSITION_COUNTS:
        for _ in range(count):
            player_id += 1
            draw = rng.randrange(total_weight)
            price = FULL_SIZE_PRICE_LADDER[-1][0]
            for value, weight in FULL_SIZE_PRICE_LADDER:
                if draw < weight:
                    price = value
                    break
                draw -= weight
            centre = 0.6 + 5.0 * (price - 40) / 80.0
            # Three draws summed: a bounded, symmetric wobble around the price's centre.
            jitter = (rng.random() + rng.random() + rng.random() - 1.5) * 1.2
            points = max(0.0, round((centre + jitter) * FULL_SIZE_POINT_STEPS))
            records.append(
                {
                    "player_id": player_id,
                    "name": f"Synthetic {position} {player_id}",
                    "team_id": f"TEAM_{(player_id % 20) + 1}",
                    "position": position,
                    "price_tenths": price,
                    "expected_points": points / FULL_SIZE_POINT_STEPS,
                }
            )
    return pd.DataFrame.from_records(records)


def make_baseline_players() -> pd.DataFrame:
    """Return a feasible default-config pool with positional alternatives."""

    position_counts = {"GK": 3, "DEF": 8, "MID": 8, "FWD": 5}
    position_base_points = {"GK": 5.0, "DEF": 6.0, "MID": 7.0, "FWD": 6.5}
    records: list[dict[str, object]] = []
    player_id = 1
    for position, count in position_counts.items():
        for offset in range(count):
            records.append(
                {
                    "player_id": player_id,
                    "name": f"Synthetic {position} {offset + 1}",
                    "team_id": f"TEAM_{((player_id - 1) % 8) + 1}",
                    "position": position,
                    "price_tenths": 45 + (player_id % 5) * 5,
                    "expected_points": position_base_points[position] + (count - offset) / 10,
                }
            )
            player_id += 1
    return pd.DataFrame.from_records(records)


def make_known_optimum_players() -> pd.DataFrame:
    """Return an eight-player pool whose optimum is easy to calculate by hand."""

    return pd.DataFrame.from_records(
        [
            {
                "player_id": "GK_A",
                "name": "Synthetic GK A",
                "team_id": "T1",
                "position": "GK",
                "price_tenths": 50,
                "expected_points": 5.0,
            },
            {
                "player_id": "GK_B",
                "name": "Synthetic GK B",
                "team_id": "T2",
                "position": "GK",
                "price_tenths": 50,
                "expected_points": 1.0,
            },
            {
                "player_id": "DEF_A",
                "name": "Synthetic DEF A",
                "team_id": "T3",
                "position": "DEF",
                "price_tenths": 50,
                "expected_points": 4.0,
            },
            {
                "player_id": "DEF_B",
                "name": "Synthetic DEF B",
                "team_id": "T4",
                "position": "DEF",
                "price_tenths": 50,
                "expected_points": 1.0,
            },
            {
                "player_id": "MID_A",
                "name": "Synthetic MID A",
                "team_id": "T5",
                "position": "MID",
                "price_tenths": 50,
                "expected_points": 10.0,
            },
            {
                "player_id": "MID_B",
                "name": "Synthetic MID B",
                "team_id": "T6",
                "position": "MID",
                "price_tenths": 50,
                "expected_points": 1.0,
            },
            {
                "player_id": "FWD_A",
                "name": "Synthetic FWD A",
                "team_id": "T7",
                "position": "FWD",
                "price_tenths": 50,
                "expected_points": 6.0,
            },
            {
                "player_id": "FWD_B",
                "name": "Synthetic FWD B",
                "team_id": "T8",
                "position": "FWD",
                "price_tenths": 50,
                "expected_points": 1.0,
            },
        ]
    )


def make_tied_players() -> pd.DataFrame:
    """Return a symmetric pool with many primary-optimal solutions."""

    players = make_known_optimum_players()
    players.loc[:, "expected_points"] = 5.0
    return players
