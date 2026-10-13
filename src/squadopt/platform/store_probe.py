"""One-release alias (ADR 0011, decision 8): the probe lives in
`squadopt.platform.storage.store_probe`. Removed in the release after the next `site-*` tag.
"""

from __future__ import annotations

from squadopt.platform.storage.store_probe import (
    StoreProbeResult as StoreProbeResult,
)
from squadopt.platform.storage.store_probe import (
    probe_store as probe_store,
)

__all__ = ["StoreProbeResult", "probe_store"]
