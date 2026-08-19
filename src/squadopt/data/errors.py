"""Exception hierarchy and error formatting for the data layer.

The data layer never reuses optimization exceptions: a data problem must be
distinguishable from an optimizer input problem, because the two are raised by
different owners at different pipeline stages.
"""

from collections.abc import Iterable

# Enough offending values to diagnose a problem without printing a whole column.
MAX_ERROR_EXAMPLES = 10


def format_examples(values: Iterable[object]) -> str:
    """Render a short, deterministic sample of offending values for an error.

    Validation messages have to name the actual bad data. A generic "invalid
    data" message forces the reader back into a debugger, so every rejection
    carries examples and, when truncated, the total count.
    """

    collected = list(values)
    rendered = ", ".join(repr(value) for value in collected[:MAX_ERROR_EXAMPLES])
    if len(collected) > MAX_ERROR_EXAMPLES:
        rendered += f", ... ({len(collected)} total)"
    return rendered


class DataError(Exception):
    """Base exception for the data layer."""


class DataSourceError(DataError):
    """Raised when a local data source cannot be located or read."""


class DataValidationError(DataError):
    """Base exception for data that violates the canonical schema contract."""


class MissingColumnsError(DataValidationError):
    """Raised when required canonical columns are absent."""


class DuplicateRecordsError(DataValidationError):
    """Raised when the canonical player-gameweek key is not unique."""


class InvalidValueError(DataValidationError):
    """Raised when a column contains values the canonical schema forbids."""


class SnapshotError(DataError):
    """Base exception for the captured-snapshot store."""


class SnapshotExistsError(SnapshotError):
    """Raised when a write would overwrite an already-captured snapshot.

    Separate from a generic source error because it is not a failure to read the
    world: it is the store refusing to let recorded history be rewritten.
    """


class SnapshotIntegrityError(SnapshotError):
    """Raised when a snapshot on disk does not match its own recorded digests.

    A replayed decision is only evidence if the bytes it replays are provably the
    bytes that were captured, so a mismatch is an error rather than a warning.
    """
