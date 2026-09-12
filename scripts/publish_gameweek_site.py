"""Compatibility entry point for the installed gameweek publisher."""

import sys

from squadopt.platform import weekly_publish as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
