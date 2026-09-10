"""Compatibility entry point for the installed gameweek publisher."""

import sys
from pathlib import Path

from squadopt.platform import weekly_publish as _implementation

_implementation.REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
