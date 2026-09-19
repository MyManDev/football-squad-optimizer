"""Shared log paths for component writers and readers."""

from pathlib import Path
from typing import Final

LOG_ROOT_NAME: Final = Path("data/logs")
"""Workspace-relative log root. A root is never component-qualified by its holder."""


def component_log_directory(log_root: Path, component: str) -> Path:
    """The directory holding ``component``'s daily files under an *unqualified* ``log_root``.

    Writers and readers both go through here, so the component name is appended in exactly
    one place. A caller that hands over ``<workspace>/data/logs/season_tick`` has already
    done this join and would silently read and write ``season_tick/season_tick``; what a
    caller holds is the root above every component, and this is what qualifies it.
    """

    if not isinstance(component, str) or not component.strip():
        raise ValueError("component must be a non-empty string.")
    return Path(log_root) / component
