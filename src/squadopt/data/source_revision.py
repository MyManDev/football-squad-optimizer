"""Which commit produced this build, resolved once, for everyone who stamps it.

Four places used to answer this question and they answered it differently: four precedence
orders, four copies of the same pattern, two roots in one of them and one in another, a
modified checkout refused by one and ignored by three, a declared value cross-checked by one
and trusted by the rest. They disagreed about the same tree, which is the failure this module
exists to end: a provenance stamp is only worth reading if every stamp means the same thing.

What is deliberately *not* unified is the failure policy, because the callers are not asking
one question. Three of them use the revision as an **identity**: it is hashed into the
backend's cache key, pinned by the run manifest's ``^[0-9a-f]{40}$``, and declared by the
weekly journal a resume reads back. An identity with a missing ingredient is a key that
collides across builds, so those refuse. The fourth uses it as a **description**: the advice
record's provenance, a footnote on the only evidence of what a member was told. Refusing to
write that record because git is missing would destroy the evidence to protect the footnote.
So this module offers two named outcomes over one resolution, :func:`source_revision` and
:func:`require_source_revision`, and the caller picks which question it is asking.

The second half is the one that was actually wrong everywhere. A revision derived from a
checkout whose files do not match it is not a revision, it is a guess that formats like one.
Measured on a modified checkout, three of the four returned a full SHA that described none of
the bytes on disk. So a resolved revision carries :class:`CheckoutState` -- what the checkout
said, when there was one to ask -- and the caller decides what to do about a tree that does
not match. This module does not itself require a clean tree: a container image carries no
checkout at all, and refusing there would refuse a correct deployment.

Absent is not broken, here as everywhere else. :attr:`SourceRevision.matches_checkout` is
``None`` when there is no checkout to ask, never ``False``; ``False`` is reserved for a
checkout that was read and did not match.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from squadopt.data.errors import SourceRevisionError

#: Where the environment states the commit, for a build that carries no checkout. The
#: container image is the case: its build stamps this in, because there is no ``.git`` to ask.
REVISION_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_REPOSITORY_COMMIT"

#: The one pattern. Used with ``fullmatch`` throughout, so it needs no anchors, and it is
#: applied to *every* candidate before acceptance rather than only to the one that wins.
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")

#: The checkout this package was imported from: ``<root>/src/squadopt/data/source_revision.py``
#: has the repository root four parents up. This is the default question "which commit
#: produced this build" is asked of, because the build is the code that is running, not
#: whatever directory a command was pointed at.
PACKAGE_ROOT: Final = Path(__file__).resolve().parents[3]

ORIGIN_DECLARED: Final = "declared"
ORIGIN_ENVIRONMENT: Final = "environment"
ORIGIN_CHECKOUT: Final = "checkout"


@dataclass(frozen=True, slots=True)
class CheckoutState:
    """What the source checkout said: the commit it is on, and whether it was modified.

    ``modified`` counts untracked files, exactly as ``git status --porcelain`` reports them
    and exactly as the weekly run has always counted them. A file nobody committed is still
    a file the build may have read.
    """

    head: str
    modified: bool


@dataclass(frozen=True, slots=True)
class SourceRevision:
    """A resolved revision, where it came from, and what the checkout said about it."""

    commit: str
    #: ``declared``, ``environment`` or ``checkout`` -- which source supplied the commit.
    origin: str
    #: The checkout that was read, or ``None`` when there was none to read.
    checkout: CheckoutState | None

    @property
    def matches_checkout(self) -> bool | None:
        """Whether the files on disk are this commit, unmodified.

        ``None`` means there was no checkout to ask, which is the ordinary case for a
        container image and is emphatically not the same answer as ``False``. ``False`` means
        a checkout was read and the bytes in it are not this commit: either it is sitting on
        a different HEAD than the declared value, or it is modified. Either way a stamp of
        this commit would describe a tree that does not exist, which is the whole of what the
        callers who publish a description or hold a workspace to release discipline need to
        know in order to decline.
        """

        if self.checkout is None:
            return None
        return self.checkout.head == self.commit and not self.checkout.modified


def source_revision(
    *, declared: str | None = None, workspace: Path | None = None
) -> SourceRevision | None:
    """The commit this build was produced from, or ``None`` when nothing can name it.

    One resolution order, for every caller: ``declared``, then the environment, then the
    checkout. Every candidate is validated before it is accepted, and a malformed one is
    refused rather than passed over, because an operator who typed a commit wrong wants to
    hear about it, not to receive a different build's identity in silence.

    What this deliberately does not do is overrule a declaration it disagrees with. Both
    declaring mechanisms exist to name a commit that the surrounding directory cannot: an
    image with no ``.git`` in it, an exported tree, a run whose manifest should carry the
    deploying commit rather than the developer's. Refusing them whenever a checkout happens
    to be present would break the only case they were added for. The disagreement is not
    hidden either -- it is exactly what ``matches_checkout`` reports -- so a caller that can
    say what it should mean says so itself. Two do: the advice record declines to publish a
    revision the tree contradicts, and the weekly run, whose workspace really is under
    release discipline, refuses outright.

    ``workspace`` names the directory whose checkout is asked, defaulting to the one this
    package was imported from. It must *be* the checkout root: ``git -C`` otherwise walks up
    until it finds any repository at all, which is how a package installed inside an unrelated
    checkout would answer with that project's HEAD.
    """

    root = PACKAGE_ROOT if workspace is None else workspace
    supplied = _validated(declared, "declared source revision")
    from_environment = _validated(
        os.environ.get(REVISION_ENVIRONMENT_VARIABLE), REVISION_ENVIRONMENT_VARIABLE
    )
    checkout = _read_checkout(root)
    if supplied is not None:
        return SourceRevision(supplied, ORIGIN_DECLARED, checkout)
    if from_environment is not None:
        return SourceRevision(from_environment, ORIGIN_ENVIRONMENT, checkout)
    if checkout is not None:
        return SourceRevision(checkout.head, ORIGIN_CHECKOUT, checkout)
    return None


def require_source_revision(
    *, declared: str | None = None, workspace: Path | None = None
) -> SourceRevision:
    """:func:`source_revision`, refusing when nothing can name the commit.

    The outcome for a caller using the revision as an identity rather than a description. A
    key assembled without one of its ingredients collides across builds and a schema pinned to
    forty hex characters has no spelling for absent, so there is nothing sensible to publish
    and the refusal is the answer.

    An identity caller that wants to phrase its own recovery -- naming its own flag, say --
    calls :func:`source_revision` and refuses on ``None`` itself. Both are the same policy;
    this one is for the callers with nothing more specific to add.
    """

    resolved = source_revision(declared=declared, workspace=workspace)
    if resolved is None:
        root = PACKAGE_ROOT if workspace is None else workspace
        raise SourceRevisionError(
            f"Could not resolve a 40-character source revision: {root} is not a Git checkout "
            f"root and no revision was declared. Set {REVISION_ENVIRONMENT_VARIABLE}, or pass "
            "the commit explicitly."
        )
    return resolved


def is_source_revision(value: object) -> bool:
    """Whether ``value`` is spelled the way a resolved revision is spelled.

    The one place the format is known, offered to readers rather than writers: a caller
    holding a value out of a document it did not produce can ask whether it is a revision at
    all, without copying the pattern and becoming the fifth definition of it.
    """

    return isinstance(value, str) and _COMMIT.fullmatch(value) is not None


def _validated(candidate: str | None, source: str) -> str | None:
    """One candidate, normalised and checked, or ``None`` when the source said nothing.

    Anything present but malformed refuses here rather than falling through to the next
    source. Falling through is how a typo becomes a stamp naming somebody else's commit.
    """

    if candidate is None:
        return None
    value = candidate.strip().lower()
    if not value:
        return None
    if not _COMMIT.fullmatch(value):
        raise SourceRevisionError(
            f"The {source} is not a 40-character lowercase Git commit: {candidate!r}."
        )
    return value


def _read_checkout(workspace: Path) -> CheckoutState | None:
    """What the checkout rooted exactly at ``workspace`` says, or ``None`` if there is none.

    ``None`` covers every way the question cannot be answered and they are deliberately not
    distinguished: git is not installed (the deployment image ships neither ``git`` nor
    ``.git``, so the call raises ``FileNotFoundError`` rather than failing), the directory is
    in no repository, or it is inside one without being its root. None of those is an error
    here; they are the absence of a checkout, and the caller decides what that means.
    """

    located = _git(workspace, "rev-parse", "--show-toplevel", "HEAD")
    if located is None:
        return None
    lines = located.splitlines()
    if len(lines) != 2:
        return None
    toplevel, head = lines
    if not _COMMIT.fullmatch(head.strip().lower()):
        return None
    if not _same_directory(Path(toplevel.strip()), workspace):
        return None
    status = _git(workspace, "status", "--porcelain")
    if status is None:
        return None
    return CheckoutState(head.strip().lower(), bool(status.strip()))


def _git(workspace: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *arguments],
            capture_output=True,
            check=False,
            text=True,
            shell=False,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _same_directory(left: Path, right: Path) -> bool:
    """Whether two paths name one directory, on a filesystem that ignores case.

    ``git`` answers in forward slashes and in whatever case the repository was created under,
    while the caller's path came from ``Path.resolve()``. On Windows those spellings differ
    for the same directory, so they are compared the way the filesystem compares them.
    """

    try:
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))
    except OSError:
        return False


__all__ = (
    "ORIGIN_CHECKOUT",
    "ORIGIN_DECLARED",
    "ORIGIN_ENVIRONMENT",
    "PACKAGE_ROOT",
    "REVISION_ENVIRONMENT_VARIABLE",
    "CheckoutState",
    "SourceRevision",
    "is_source_revision",
    "require_source_revision",
    "source_revision",
)
