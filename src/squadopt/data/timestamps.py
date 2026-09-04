"""One canonical spelling for the instants this project has to compare.

Two different things need a trustworthy timestamp: when a snapshot was captured, and
when a gameweek's deadline falls. Comparing them is the entire basis for claiming a
decision used only information available at the time, so an ambiguous instant is not
a cosmetic problem. A naive timestamp or a local-time offset is rejected rather than
assumed to mean UTC, and whatever precision the source supplied is preserved, because
truncating would silently merge two distinct instants.
"""

from datetime import datetime

from squadopt.data.errors import DataSourceError


def normalize_utc_timestamp(value: object, *, label: str) -> str:
    """Return the canonical UTC spelling of one instant.

    ``label`` names the field being checked so a rejection points at the caller's
    own vocabulary rather than at this helper.
    """

    if not isinstance(value, str) or not value.strip():
        raise DataSourceError(
            f"{label} must be a non-empty ISO-8601 timestamp string, got {value!r}."
        )
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise DataSourceError(
            f"{label} must be an ISO-8601 timestamp, got {value!r}: {error}"
        ) from error
    if parsed.tzinfo is None:
        raise DataSourceError(
            f"{label} must state a timezone so it cannot be misread, got {value!r}."
        )
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0.0:
        raise DataSourceError(
            f"{label} must be expressed in UTC, got {value!r} with offset {offset!r}."
        )
    return parsed.isoformat().replace("+00:00", "Z")


def as_instant(value: str) -> datetime:
    """Parse a timestamp already normalized by :func:`normalize_utc_timestamp`.

    Kept separate so ordering comparisons operate on values that have passed
    validation, instead of each call site reaching for its own parser.
    """

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
