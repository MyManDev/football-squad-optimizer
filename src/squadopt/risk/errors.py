"""Domain exceptions for conformal risk-aware optimization."""


class RiskError(Exception):
    """Base exception for the risk package."""


class RiskConfigurationError(RiskError):
    """Raised when a risk configuration is internally inconsistent."""


class RiskValidationError(RiskError):
    """Raised when calibrated projections or screening folds violate the contract."""
