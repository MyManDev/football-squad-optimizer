"""Small, synthetic player pools for optimizer tests."""

import pandas as pd


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
