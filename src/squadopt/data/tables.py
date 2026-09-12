"""Write an export table in the bytes every machine agrees on.

`DataFrame.to_csv` defaults its line terminator to `os.linesep`, so the same table writes
`\\r\\n` on Windows and `\\n` on Linux. A digest over the raw file bytes then identifies the
operating system as much as the table. Every table whose `table_sha256` is recorded is
written through here so the terminator is settled once, for every platform.

Rounding the values is the caller's job; how far a value must be rounded to survive a
LAPACK last-bit difference is measured in `squadopt.backtest.export_precision`. A hash means
"the same table" only when both halves are settled.
"""

from pathlib import Path
from typing import Final

import pandas as pd

# The line terminator every export is written with, on every platform. Explicit because
# pandas defaults to os.linesep and a digest over the file bytes would otherwise identify
# the operating system as much as the table.
EXPORT_LINE_TERMINATOR: Final = "\n"


def write_export_table(table: pd.DataFrame, path: Path) -> None:
    """Write one export table in the bytes every machine agrees on.

    The parent directory is created if it is missing, which lets a caller name an output
    path without preparing it first.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, lineterminator=EXPORT_LINE_TERMINATOR)
