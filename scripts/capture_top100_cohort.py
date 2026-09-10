"""Compatibility entry point for squadopt.platform.cohort_capture."""

import sys
from pathlib import Path

from squadopt.platform import cohort_capture as _implementation

_implementation.REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
