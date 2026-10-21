"""Read the operator's league menus at the filesystem boundary."""

import json
from pathlib import Path

from squadopt.contracts.league_list import LeagueListError, parse_league_menus


def read_league_menus(path: Path) -> dict[int, str]:
    """Read ids and menus once, preserving the contract's refusal messages."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LeagueListError(f"No league list at {path}.") from error
    except ValueError as error:
        raise LeagueListError(f"{path} does not parse as JSON.") from error
    return parse_league_menus(document)
