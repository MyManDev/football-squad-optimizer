"""The Node the web suite needs is a repository fact, not something a contributor discovers.

Both CI jobs that touch `web/` pin `node-version: 22`, and the README, two runbooks and
`docs/architecture/branching.md` all say Node 22. `web/package.json` said nothing, so npm
had no opinion: `npm ci` on any newer Node installed cleanly and the suite then failed in a
way that names neither Node nor npm. Measured on 2026-09-13 against `15edba9` on macOS:
under Node 26.8.2 the jsdom environment does not come up, `window.localStorage` is
undefined, and **118 of 589 tests fail**; under Node 22.23.2 the same tree is **588 passed,
0 failed**. Nothing in those 118 failures points at the Node version, which is what makes
this worth a guard rather than a sentence in a document.

`engines` alone only warns. `web/.npmrc` sets `engine-strict=true` so the install refuses
instead, and the refusal is the point: it arrives before the pages, the clock and an hour
of someone's afternoon are spent on a suite that cannot pass.

The third fact -- that the declaration and the workflows keep saying the same thing -- is
why this is a test and not a comment. The version in `package.json` is a copy of the one in
the workflows, and copies drift. When the pin moves, it moves here too, deliberately.
"""

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = REPOSITORY_ROOT / "web" / "package.json"
NPMRC = REPOSITORY_ROOT / "web" / ".npmrc"
WORKFLOWS = (
    REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "deploy-pages.yml",
)


def _declared_major() -> str:
    """The major version `web/package.json` declares, e.g. ``"22"`` from ``"22.x"``."""

    engines = json.loads(PACKAGE_JSON.read_text(encoding="utf-8")).get("engines")
    assert isinstance(engines, dict), "web/package.json declares no 'engines' object"
    declared = engines.get("node")
    assert isinstance(declared, str) and declared.strip(), "'engines.node' is not text"
    major = re.match(r"^(\d+)\.x$", declared.strip())
    assert major is not None, (
        f"'engines.node' is {declared!r}. It is written as '<major>.x' so that it names the "
        "same thing the workflows pin -- a major line -- and not a range whose agreement "
        "with them would be a matter of opinion."
    )
    return major.group(1)


def _workflow_majors() -> tuple[tuple[Path, str], ...]:
    """Every `node-version:` a workflow pins, with the file that pins it."""

    found: list[tuple[Path, str]] = []
    for workflow in WORKFLOWS:
        for pin in re.finditer(
            r"^\s*node-version:\s*\"?(\d+)\"?\s*$",
            workflow.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            found.append((workflow, pin.group(1)))
    assert found, "no workflow pins a node-version any more"
    return tuple(found)


def test_the_declared_node_is_the_node_every_workflow_installs() -> None:
    """What npm enforces locally is what CI runs, in both workflows.

    Driven from the workflows rather than from a constant on purpose: the workflows are what
    actually build and deploy the site, so this fails if the declaration and the pins ever
    part company -- which is the state it was written to end.
    """

    declared = _declared_major()
    for workflow, pinned in _workflow_majors():
        assert pinned == declared, (
            f"{workflow.name} installs Node {pinned} while web/package.json declares "
            f"{declared}.x. A contributor whose npm obeys the declaration would then be on a "
            "different Node from the one that gates the merge."
        )


def test_the_declaration_refuses_rather_than_warns() -> None:
    """`npm ci` on the wrong Node must fail, not print a warning and carry on.

    Without `engine-strict`, `engines` is advisory: npm prints a line into an install that
    succeeds, and the 118 failures arrive later wearing no version label at all.
    """

    assert NPMRC.is_file(), "web/.npmrc is missing, so 'engines' only warns"
    settings = [
        line.split("#", 1)[0].strip().replace(" ", "")
        for line in NPMRC.read_text(encoding="utf-8").splitlines()
    ]
    assert "engine-strict=true" in settings, (
        "web/.npmrc does not set engine-strict=true, so a wrong-Node install still succeeds."
    )
