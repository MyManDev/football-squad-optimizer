"""The pinned environment actually pins what the project declares, enforced not remembered.

`docs/architecture/branching.md` carried this as an open gap: "a dependency added to
`pyproject.toml` is not automatically added to `constraints.txt`, and `scipy` arrived that way
in #139 [...] the two are kept in step by hand." Nothing checked it, and by the time this test
was written the gap had produced a second instance: `jsonschema` was declared in both the `api`
and `dev` extras, imported by `src/squadopt/api/views.py` and used by five test modules, and
absent from `constraints.txt` along with its whole runtime subtree. Its *type stubs* were
pinned; the library was not.

What that costs is worth stating precisely, because the obvious claim is the wrong one. No
measurement script imports `jsonschema`, so the committed artifacts were never at risk. What
was at risk is the gate: the 3.13 job installs with `pip install -c constraints.txt -e
".[api,dev]"` and is described as reproducing the measurement environment exactly, while
resolving a schema-validation library freely inside `>=4.23,<5`. A minor release changing
validation strictness could have moved five contract tests with no commit anywhere.

Two halves, because they fail in opposite directions:

- **Every declared dependency is pinned.** This is the gap above.
- **Every pin satisfies the range it is declared with.** The reverse drift: raising a floor in
  `pyproject.toml` above the pin would leave the two files contradicting each other, and the
  3.11 job (declared ranges) and the 3.13 job (pins) would then be installing environments
  that cannot both be right.

There is deliberately **no exceptions tuple**. `test_measurements_index.py` carries one because
it inherited real debt under ADR 0003's grandfather rule; here there is none, and an empty
tuple is an invitation to add the first entry instead of the missing pin.

The reverse direction is not checked and must not be: `constraints.txt` legitimately pins the
whole resolved tree, so most of its lines are transitive dependencies that appear in no
`pyproject.toml` declaration.
"""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
CONSTRAINTS = REPOSITORY_ROOT / "constraints.txt"


def _declared() -> list[tuple[str, Requirement]]:
    """Every dependency the project declares, with the extra that declares it.

    Runtime dependencies and every optional-dependency group, because the 3.13 job installs
    ``.[api,dev]`` and therefore resolves all of them.
    """

    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = document["project"]
    declared: list[tuple[str, Requirement]] = [
        ("runtime", Requirement(spec)) for spec in project.get("dependencies", ())
    ]
    for extra, specs in project.get("optional-dependencies", {}).items():
        declared.extend((extra, Requirement(spec)) for spec in specs)
    return declared


def _pins() -> dict[str, str]:
    """Distribution name to pinned version, keyed by PEP 503 normalized name.

    Normalizing matters rather than being tidy: this file holds ``mypy_extensions`` and
    ``import-linter`` side by side, so a raw string comparison would miss real pins.
    """

    pins: dict[str, str] = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "==" not in stripped:
            continue
        name, version = stripped.split("==", 1)
        pins[canonicalize_name(name)] = version.strip()
    return pins


def test_every_declared_dependency_is_pinned() -> None:
    """A declared dependency missing from the pinned environment leaves that job unpinned."""

    pins = _pins()
    missing = sorted(
        f"{requirement.name} (declared in {extra})"
        for extra, requirement in _declared()
        if canonicalize_name(requirement.name) not in pins
    )
    assert not missing, (
        "These dependencies are declared in pyproject.toml but not pinned in constraints.txt:\n  "
        + "\n  ".join(missing)
        + "\nAdd the pin. Do not add an exception here -- the point of this test is that the "
        "pinned environment pins everything the project asks for."
    )


def test_every_pin_satisfies_its_declared_range() -> None:
    """The two files must not contradict each other about what is installable."""

    pins = _pins()
    conflicts = []
    for extra, requirement in _declared():
        pinned = pins.get(canonicalize_name(requirement.name))
        if pinned is None:
            continue  # the other test owns this failure
        if requirement.specifier and not requirement.specifier.contains(
            Version(pinned), prereleases=True
        ):
            conflicts.append(
                f"{requirement.name} is pinned at {pinned} but declared "
                f"{requirement.specifier} in {extra}"
            )
    assert not conflicts, (
        "constraints.txt and pyproject.toml disagree about what may be installed:\n  "
        + "\n  ".join(sorted(conflicts))
        + "\nThe 3.11 job installs the declared ranges and the 3.13 job installs these pins, "
        "so a contradiction means the two gates are testing different environments."
    )


def test_the_rule_has_something_to_check() -> None:
    """A matcher that silently found nothing would pass both tests above forever.

    The failure this guards against is not hypothetical for this repository: the first
    version of ``test_measurements_index.py``'s matcher read only the first cell of each row
    and reported 8 unlisted artifacts when the real number was 22 -- "the kind of wrong answer
    that looks like a passing check", in its own words.
    """

    declared = _declared()
    pins = _pins()
    assert len(declared) >= 15, f"only {len(declared)} declared dependencies parsed"
    assert len(pins) >= 30, f"only {len(pins)} pins parsed"
    assert canonicalize_name("numpy") in pins
    assert any(requirement.name == "numpy" for _, requirement in declared)
