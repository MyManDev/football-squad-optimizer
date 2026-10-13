"""Permanent entry alias (ADR 0011, decision 8): `python -m squadopt.platform.backup_recovery` keeps
working forever, and the module lives in `squadopt.platform.storage.backup_recovery`. This file
runs `main` only as `__main__`.
"""

from __future__ import annotations

from squadopt.platform.storage.backup_recovery import (
    BACKUP_SCHEMA_VERSION as BACKUP_SCHEMA_VERSION,
)
from squadopt.platform.storage.backup_recovery import (
    MANIFEST_NAME as MANIFEST_NAME,
)
from squadopt.platform.storage.backup_recovery import (
    BackupError as BackupError,
)
from squadopt.platform.storage.backup_recovery import (
    BackupReceipt as BackupReceipt,
)
from squadopt.platform.storage.backup_recovery import (
    create_backup as create_backup,
)
from squadopt.platform.storage.backup_recovery import (
    main as main,
)
from squadopt.platform.storage.backup_recovery import (
    restore_backup as restore_backup,
)
from squadopt.platform.storage.backup_recovery import (
    verify_backup as verify_backup,
)

__all__ = [
    "BACKUP_SCHEMA_VERSION",
    "MANIFEST_NAME",
    "BackupError",
    "BackupReceipt",
    "create_backup",
    "main",
    "restore_backup",
    "verify_backup",
]

if __name__ == "__main__":
    raise SystemExit(main())
