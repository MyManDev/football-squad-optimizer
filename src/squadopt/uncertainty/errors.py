"""Domain exceptions for projection uncertainty calibration."""


class UncertaintyError(Exception):
    """Base exception for the uncertainty package."""


class UncertaintyConfigurationError(UncertaintyError):
    """Raised when uncertainty configuration is internally inconsistent."""


class UncertaintyValidationError(UncertaintyError):
    """Raised when folds, projections, or realized outcomes violate the contract."""
