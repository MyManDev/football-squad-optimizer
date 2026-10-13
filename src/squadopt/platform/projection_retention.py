"""One-release alias (ADR 0011, decision 8): retention lives in
`squadopt.platform.storage.projection_retention`. Removed in the release after the next `site-*`
tag.
"""

from __future__ import annotations

from squadopt.platform.storage.projection_retention import (
    ProjectionRetentionError as ProjectionRetentionError,
)
from squadopt.platform.storage.projection_retention import (
    publish_retained_handoff as publish_retained_handoff,
)
from squadopt.platform.storage.projection_retention import (
    retained_handoff_path as retained_handoff_path,
)

__all__ = ["ProjectionRetentionError", "publish_retained_handoff", "retained_handoff_path"]
