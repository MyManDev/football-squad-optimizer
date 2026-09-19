"""Acquire one week's club news and print the capture id.

A shim, like its siblings: the implementation is
``squadopt.platform.club_news_acquire`` and this only fixes the repository root so the
default registry and snapshot paths resolve from the checkout rather than the shell's
working directory.
"""

import sys
from pathlib import Path

from squadopt.platform import club_news_acquire as _implementation

_implementation.REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
