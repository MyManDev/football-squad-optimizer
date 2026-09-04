"""Tests for the single source of the release version (#180).

The point of `__version__` reading installed metadata is that there is exactly one place the
number lives. These tests exist to keep it that way rather than to assert a particular value.
"""

import re
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

import squadopt

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+].+)?$")


def _declared_version() -> str:
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def test_the_package_reports_the_installed_distributions_version() -> None:
    """Not a copy of it — the same object the metadata returns."""

    assert squadopt.__version__ == distribution_version(squadopt.DISTRIBUTION_NAME)


def test_the_distribution_name_is_not_the_import_name() -> None:
    """`squadopt` is what you import; `football-squad-optimizer` is what is installed.

    Asking `importlib.metadata` for the import name raises, which is the mistake this pins.
    """

    assert squadopt.DISTRIBUTION_NAME == "football-squad-optimizer"
    assert squadopt.__name__ == "squadopt"


def test_the_declared_version_is_semantic() -> None:
    assert SEMVER.match(_declared_version()), _declared_version()


def test_the_installed_version_matches_the_declared_one() -> None:
    declared = _declared_version()
    if squadopt.__version__ != declared:
        pytest.fail(
            f"pyproject.toml declares {declared} but the installed distribution reports "
            f"{squadopt.__version__}. Reading the number from one place means an editable "
            "install goes stale after a bump; refresh it with "
            "`python -m pip install -e . --no-deps`."
        )


def test_the_version_is_not_written_down_a_second_time() -> None:
    """A literal version string under `src/` would be a second place to drift from."""

    declared = _declared_version()
    offenders = [
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "src").rglob("*.py")
        if f'"{declared}"' in path.read_text(encoding="utf-8")
        or f"'{declared}'" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


def test_the_changelog_documents_the_declared_version() -> None:
    """A release whose number is not in the changelog is a release nobody can read."""

    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {_declared_version()}" in changelog


def test_the_changelog_does_not_claim_the_version_is_an_operational_identifier() -> None:
    """The measured conclusion on #180: identity per decision, not per release."""

    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for recorded in ("model_version", "prediction_fingerprint", "repository_commit"):
        assert recorded in changelog
