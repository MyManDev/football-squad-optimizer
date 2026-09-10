"""Compatibility re-export: ``addressable`` now lives in the data layer.

The create-once writer in ``squadopt.data.atomic`` needs it, and the data layer cannot
import the platform layer, so the helper moved down. This module stays for one release so
the platform callers and their tests keep their import path.
"""

from squadopt.data._long_paths import addressable

__all__: tuple[str, ...] = ("addressable",)
