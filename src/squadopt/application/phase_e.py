"""Reviewed calibration identities for the internal Phase E selector."""

from typing import Final

# Pairs of (Phase C model_version, component sampler contract version). The foundation
# sampler's contract string is the component inputs contract; a candidate sampler names its
# own, so a pin for one sampler never admits a draw from another.
# Populate only in a reviewed change citing the binding Phase D artifact whose
# verdict.status is calibrated_internal. This does not enable a live decision path.
PHASE_E_CALIBRATED_VERSIONS: Final[tuple[tuple[str, str], ...]] = ()
