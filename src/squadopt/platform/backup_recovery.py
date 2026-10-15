"""Permanent entry alias (ADR 0011, decision 8): `python -m squadopt.platform.backup_recovery` keeps
working forever. The module lives in `squadopt.platform.storage.backup_recovery`; this file
registers that module under its own dotted name in `sys.modules`, runs `main` only as `__main__`,
and leaves a spawn child that runs it as `__mp_main__` alone.
"""

from __future__ import annotations

import sys

from squadopt.platform.storage import backup_recovery as _moved

if __name__ == "squadopt.platform.backup_recovery":
    sys.modules[__name__] = _moved

if __name__ == "__main__":
    raise SystemExit(_moved.main())
