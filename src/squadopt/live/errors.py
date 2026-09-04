"""Errors shared by the live path's modules."""

from squadopt.data.errors import DataError


class LedgerError(DataError):
    """Raised when a ledger entry cannot be recorded, read, or trusted."""
