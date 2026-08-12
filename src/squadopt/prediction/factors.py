"""Mappings from experiment factors to executable prediction configuration."""

from dataclasses import dataclass, field
from numbers import Integral
from typing import Final

from squadopt.features import FeatureConfig, FeatureConfigurationError
from squadopt.prediction.config import BaselineProjectionConfig

FEATURE_GENERATION_CONTRACT_VERSION: Final = "form_window_v1"
BASELINE_FORM_WINDOW: Final = 5


@dataclass(frozen=True, slots=True)
class FormWindowMapping:
    """Resolve the scalar ``form_window`` factor into matching pipeline configs.

    One trial value controls every baseline lookback that represents recent form.
    ``min_periods`` stays at one as a fixed missing-history policy rather than a
    hidden second factor.
    """

    form_window: int = BASELINE_FORM_WINDOW
    feature_config: FeatureConfig = field(init=False)
    projection_config: BaselineProjectionConfig = field(init=False)

    def __post_init__(self) -> None:
        value = self.form_window
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise FeatureConfigurationError(f"form_window must be an integer, got {value!r}.")
        window = int(value)
        if window < 1:
            raise FeatureConfigurationError(f"form_window must be at least 1, got {window}.")

        object.__setattr__(self, "form_window", window)
        object.__setattr__(
            self,
            "feature_config",
            FeatureConfig(
                minutes_windows=(window,),
                points_windows=(window,),
                per_90_window=window,
                min_periods=1,
            ),
        )
        object.__setattr__(
            self,
            "projection_config",
            BaselineProjectionConfig(
                minutes_window=window,
                per_90_window=window,
            ),
        )
