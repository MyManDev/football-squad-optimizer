"""One-release alias (ADR 0011, decision 8): the store probe lives in
`squadopt.platform.storage.store_probe`, and this name is that module itself, registered under
the old dotted path in `sys.modules`, so a private name or a monkeypatch through either path
reaches the one module. Removed in the first pull request after the next `site-*` release.
"""

from __future__ import annotations

import sys

from squadopt.platform.storage import store_probe as _moved

sys.modules[__name__] = _moved
