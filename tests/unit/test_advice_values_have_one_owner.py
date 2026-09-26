"""The advice path's shared values are written once, where they are owned.

A test that compared module-level constants would not see a value restated inside a schema
dict or an ``if`` test, which is where the copies were. So this one reads the source text.
"""

from pathlib import Path

from squadopt.planning.chip_strategy import CHIP_STRATEGY_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "squadopt"


def test_the_chip_strategy_version_is_written_once_in_the_package() -> None:
    written = {
        path.relative_to(PACKAGE_ROOT).as_posix(): count
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if (count := path.read_text(encoding="utf-8").count(CHIP_STRATEGY_VERSION))
    }

    assert written == {"planning/chip_strategy.py": 1}
