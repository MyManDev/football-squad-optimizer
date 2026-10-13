"""The scripts the type gate checks are the scripts the discipline document names.

`docs/architecture/pr_discipline.md` tells a reader which scripts mypy checks, so they can tell
whether a script change was type-checked. The list there is written by hand, while the gate
reads `[tool.mypy] files` in `pyproject.toml`. When three build scripts joined that set, the
document still said "four operator scripts" and "that complete set", and nothing noticed.

Both directions are held: every script in the configured set is named in the mypy bullet, and
the bullet names no script outside it. A script path is compared relative to `scripts/`,
which is how the document writes it. The bullet also cites this test by its path under
`tests/`, and that citation is the guard, not a checked script.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
PR_DISCIPLINE = REPOSITORY_ROOT / "docs" / "architecture" / "pr_discipline.md"

#: A backticked Python file name, with or without a directory.
SCRIPT = re.compile(r"`([A-Za-z0-9_./-]+\.py)`")


def _configured() -> list[str]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    files: list[str] = document["tool"]["mypy"]["files"]
    return files


def _mypy_bullet() -> str:
    text = PR_DISCIPLINE.read_text(encoding="utf-8")
    start = text.index("- **mypy**:")
    end = text.index("\n- ", start)
    return text[start:end]


def test_the_mypy_bullet_names_exactly_the_configured_scripts() -> None:
    configured = {
        path.removeprefix("scripts/") for path in _configured() if path.startswith("scripts/")
    }
    named = {
        path.removeprefix("scripts/")
        for path in SCRIPT.findall(_mypy_bullet())
        if not path.startswith("tests/")
    }

    assert named == configured, (
        f"not named in pr_discipline.md: {sorted(configured - named)}; "
        f"named but not configured: {sorted(named - configured)}"
    )


def test_the_mypy_bullet_names_the_package_the_gate_checks() -> None:
    assert "src/squadopt" in _configured()
    assert "`src/squadopt`" in _mypy_bullet()
