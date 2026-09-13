"""One answer to "which commit produced this build", and one meaning for absent.

Four functions used to answer this question with four resolution orders and four failure
policies, and three of the four were measured returning a full SHA that described none of the
bytes on disk. These tests pin the resolver that replaced them and, just as importantly, pin
what each of the four callers now does with it: the two that use the revision as an identity
still refuse, and the one that uses it as a description now publishes absence rather than a
guess.

Everything here runs against a real temporary Git repository rather than a mocked
``subprocess``. Every failure this module exists to prevent is a failure of the real
subprocess -- git missing, a directory that is not a checkout root, a tree with edits in it --
and a mock would assert that the code calls itself the way it calls itself.
"""

import subprocess
from pathlib import Path

import pytest

from squadopt.application.advice_record import repository_commit
from squadopt.application.weekly_plan import WeekError
from squadopt.data import source_revision as source_revision_module
from squadopt.data.errors import DataError, SourceRevisionError
from squadopt.data.source_revision import (
    ORIGIN_CHECKOUT,
    ORIGIN_DECLARED,
    ORIGIN_ENVIRONMENT,
    REVISION_ENVIRONMENT_VARIABLE,
    require_source_revision,
    source_revision,
)
from squadopt.platform.backend_runtime import BackendConfigError, _repository_commit
from squadopt.platform.cli import _git_commit
from squadopt.platform.weekly_operations import _revision

REPOSITORY = Path(__file__).resolve().parents[2]
OTHER = "b" * 40


@pytest.fixture(autouse=True)
def _no_inherited_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer shell with the variable exported must not decide what these tests measure."""

    monkeypatch.delenv(REVISION_ENVIRONMENT_VARIABLE, raising=False)


def _git(checkout: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *arguments], capture_output=True, check=True, text=True
    ).stdout.strip()


def _checkout(root: Path, *, modified: bool = False) -> str:
    """A real repository with one commit in it, optionally with an edit left in the tree."""

    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    # The identity has to live in the repository: a runner with no global git identity
    # refuses the commit, and then every test here fails for a reason that is not the subject.
    _git(root, "config", "user.name", "Synthetic")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    (root / "source.py").write_text("committed", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    if modified:
        (root / "source.py").write_text("edited after the commit", encoding="utf-8")
    return _git(root, "rev-parse", "HEAD")


def test_each_source_resolves_and_says_which_one_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stamp is only auditable if the record says where it came from, so origin is reported."""

    head = _checkout(tmp_path / "checkout")
    resolved = source_revision(workspace=tmp_path / "checkout")
    assert resolved is not None
    assert (resolved.commit, resolved.origin) == (head, ORIGIN_CHECKOUT)

    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    from_environment = source_revision(workspace=tmp_path / "nowhere")
    assert from_environment is not None
    assert (from_environment.commit, from_environment.origin) == (OTHER, ORIGIN_ENVIRONMENT)

    declared = source_revision(declared=OTHER, workspace=tmp_path / "nowhere")
    assert declared is not None
    assert (declared.commit, declared.origin) == (OTHER, ORIGIN_DECLARED)


def test_a_declared_revision_outranks_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    resolved = source_revision(declared="c" * 40, workspace=tmp_path / "nowhere")
    assert resolved is not None
    assert (resolved.commit, resolved.origin) == ("c" * 40, ORIGIN_DECLARED)


def test_the_environment_outranks_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The image stamps its own commit in; a checkout lying around does not outrank it."""

    _checkout(tmp_path / "checkout")
    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    resolved = source_revision(workspace=tmp_path / "checkout")
    assert resolved is not None
    assert (resolved.commit, resolved.origin) == (OTHER, ORIGIN_ENVIRONMENT)


def test_a_revision_is_normalised_before_it_is_accepted(tmp_path: Path) -> None:
    resolved = source_revision(declared=f"  {'A' * 40}\n", workspace=tmp_path / "nowhere")
    assert resolved is not None
    assert resolved.commit == "a" * 40


@pytest.mark.parametrize("malformed", ["0123456789abcdef", "z" * 40, "a" * 41])
def test_a_malformed_revision_refuses_instead_of_falling_through_to_the_next_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    """The failure that matters: a typo must not be answered with somebody else's commit.

    A resolver that skipped an unusable candidate would hand back the next source's value
    under the operator's typo, and the stamp would name a build nobody asked about.
    """

    head = _checkout(tmp_path / "checkout")
    with pytest.raises(SourceRevisionError, match="declared source revision"):
        source_revision(declared=malformed, workspace=tmp_path / "checkout")

    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, malformed)
    with pytest.raises(SourceRevisionError, match=REVISION_ENVIRONMENT_VARIABLE):
        source_revision(workspace=tmp_path / "checkout")
    assert head  # the checkout could have answered, and deliberately was not asked to.


@pytest.mark.parametrize("origin", [ORIGIN_DECLARED, ORIGIN_ENVIRONMENT])
def test_a_declaration_the_checkout_contradicts_is_reported_rather_than_overruled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    """The resolver resolves; it does not adjudicate.

    Both declaring mechanisms exist to name a commit the surrounding directory cannot, so a
    checkout that happens to be present must not veto them: that would break an exported tree,
    an image, and this suite's own injection of a deterministic commit. What the caller gets
    instead is the disagreement itself, as ``matches_checkout``, and the two callers that know
    what it should mean act on it -- pinned further down for each.
    """

    _checkout(tmp_path / "checkout")
    declared = OTHER if origin == ORIGIN_DECLARED else None
    if origin == ORIGIN_ENVIRONMENT:
        monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    resolved = source_revision(declared=declared, workspace=tmp_path / "checkout")
    assert resolved is not None
    assert (resolved.commit, resolved.origin) == (OTHER, origin)
    assert resolved.matches_checkout is False


def test_a_modified_checkout_still_resolves_but_no_longer_claims_to_be_the_tree(
    tmp_path: Path,
) -> None:
    _checkout(tmp_path / "clean")
    clean = source_revision(workspace=tmp_path / "clean")
    assert clean is not None and clean.matches_checkout is True

    head = _checkout(tmp_path / "edited", modified=True)
    edited = source_revision(workspace=tmp_path / "edited")
    assert edited is not None
    assert edited.commit == head
    assert edited.matches_checkout is False
    assert edited.checkout is not None and edited.checkout.modified is True


def test_an_untracked_file_counts_as_a_modified_checkout(tmp_path: Path) -> None:
    """Nobody committed it, and the build may still have read it."""

    _checkout(tmp_path / "checkout")
    (tmp_path / "checkout" / "scratch.py").write_text("never added", encoding="utf-8")
    resolved = source_revision(workspace=tmp_path / "checkout")
    assert resolved is not None and resolved.matches_checkout is False


def test_no_checkout_leaves_the_question_unanswered_rather_than_answered_no(
    tmp_path: Path,
) -> None:
    """The container case. ``False`` would read as "the tree does not match" and be a lie."""

    resolved = source_revision(declared=OTHER, workspace=tmp_path / "no-repository")
    assert resolved is not None
    assert resolved.checkout is None
    assert resolved.matches_checkout is None


def test_a_directory_inside_a_checkout_is_not_that_checkout(tmp_path: Path) -> None:
    """``git -C`` walks up until it finds any repository, which is how a package installed
    inside an unrelated project would stamp that project's HEAD onto this one's evidence."""

    _checkout(tmp_path / "checkout")
    inside = tmp_path / "checkout" / "nested"
    inside.mkdir()
    resolved = source_revision(declared=OTHER, workspace=inside)
    assert resolved is not None
    assert resolved.checkout is None


def test_nothing_to_ask_is_absent_from_one_outcome_and_a_refusal_from_the_other(
    tmp_path: Path,
) -> None:
    assert source_revision(workspace=tmp_path / "no-repository") is None
    with pytest.raises(SourceRevisionError, match=REVISION_ENVIRONMENT_VARIABLE):
        require_source_revision(workspace=tmp_path / "no-repository")


def test_git_missing_from_the_path_is_absence_and_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployment image ships neither ``.git`` nor ``git``; the call raises OSError."""

    _checkout(tmp_path / "checkout")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert source_revision(workspace=tmp_path / "checkout") is None


def test_the_advice_record_publishes_absence_rather_than_a_revision_it_cannot_stand_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this change exists to end.

    Measured before it, on a checkout with nineteen modified paths, this function returned a
    full SHA. The record is the only evidence of what a member was told, and a stamp naming a
    revision that produced none of those bytes attributes the advice to the wrong build.
    """

    head = _checkout(tmp_path / "clean")
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "clean")
    assert repository_commit() == head

    _checkout(tmp_path / "edited", modified=True)
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "edited")
    assert repository_commit() is None


def test_the_advice_record_declines_a_declared_revision_its_own_tree_contradicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stale exported variable, measured being published before this change.

    The resolver honours the declaration, because that is what declarations are for, and this
    caller then declines to write it down, because the tree it can see is not that commit. The
    record says nothing rather than naming a build that produced none of these bytes.
    """

    _checkout(tmp_path / "checkout")
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "checkout")
    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    assert repository_commit() is None


def test_the_advice_record_publishes_a_declared_revision_where_there_is_no_tree_to_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container, where declining would lose a provenance that is perfectly good.

    Nothing contradicts the declaration because there is nothing to contradict it, and an
    unanswerable question must not be read as a negative answer.
    """

    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "no-repository")
    monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    assert repository_commit() == OTHER


def test_the_advice_record_still_records_when_no_revision_can_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It describes; it does not identify. Losing the evidence to protect its footnote would
    be the worse trade, so this returns ``None`` and never raises."""

    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "no-repository")
    assert repository_commit() is None


def test_the_backend_refuses_to_fill_a_cache_it_cannot_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An identity use: the commit is hashed into the cache key, so absent has no spelling.

    The message must keep naming the variable. The image's own guard and its deployment
    runbook both quote that instruction, and it is the whole recovery.
    """

    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "no-repository")
    with pytest.raises(BackendConfigError, match=REVISION_ENVIRONMENT_VARIABLE):
        _repository_commit()


def test_the_backend_keys_a_cache_from_a_modified_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deliberately not the advice record's rule. A developer editing a tree across two
    processes still needs the two to agree on a key, and the commit alone gives them one."""

    head = _checkout(tmp_path / "edited", modified=True)
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "edited")
    assert _repository_commit() == head


def test_the_cli_takes_the_commit_it_was_handed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--repository-commit`` overrides, which is what it is for.

    A run whose manifest should carry the deploying commit rather than whatever tree the code
    was invoked from is the case the flag was added for, so a checkout being present does not
    revoke it. The manifest's schema wants a commit and gets the one it was told.
    """

    _checkout(tmp_path / "checkout")
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "checkout")
    assert _git_commit("d" * 40) == "d" * 40


def test_the_cli_refuses_a_commit_that_is_not_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "no-repository")
    with pytest.raises(DataError, match="not a 40-character"):
        _git_commit("d" * 12)


def test_the_cli_refuses_when_nothing_names_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_revision_module, "PACKAGE_ROOT", tmp_path / "no-repository")
    with pytest.raises(DataError, match="--repository-commit"):
        _git_commit(None)


def test_the_weekly_run_refuses_a_modified_checkout_in_its_own_words(tmp_path: Path) -> None:
    """The refusal that was already right, and the reason the sanctioned Friday path never
    reaches the advice record with a tree it cannot stand behind."""
    _checkout(tmp_path / "edited", modified=True)
    with pytest.raises(WeekError, match="clean source checkout"):
        _revision(tmp_path / "edited", None)


@pytest.mark.parametrize("through_the_environment", [False, True])
def test_the_weekly_run_refuses_a_revision_that_is_not_its_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, through_the_environment: bool
) -> None:
    """This is the caller that *does* adjudicate, because its workspace is the source tree.

    The refusal names where the offending value came from. An exported variable reaches here
    as well as the flag does, and an operator told only that "the supplied revision" is wrong
    would go looking at a command line that does not carry it.
    """

    head = _checkout(tmp_path / "checkout")
    if through_the_environment:
        monkeypatch.setenv(REVISION_ENVIRONMENT_VARIABLE, OTHER)
    with pytest.raises(WeekError) as refusal:
        _revision(tmp_path / "checkout", None if through_the_environment else OTHER)
    expected = ORIGIN_ENVIRONMENT if through_the_environment else ORIGIN_DECLARED
    assert expected in str(refusal.value)
    assert OTHER in str(refusal.value) and head in str(refusal.value)


def test_the_weekly_run_refuses_a_non_git_workspace_with_nothing_declared(
    tmp_path: Path,
) -> None:
    with pytest.raises(WeekError, match="non-Git workspace"):
        _revision(tmp_path / "no-repository", None)


def test_the_weekly_run_takes_a_declared_revision_for_a_workspace_with_no_checkout(
    tmp_path: Path,
) -> None:
    """A deployed workspace is not a checkout, and the declared revision is the whole point
    of the flag. Nothing contradicts it, so there is nothing to refuse."""

    assert _revision(tmp_path / "no-repository", OTHER) == OTHER


def test_only_one_module_asks_git_which_commit_this_is() -> None:
    """The guard that makes the consolidation stick rather than decay.

    Four copies is how this started, and a fifth appears the moment someone needs a commit
    and finds no obvious home for the question. ``weekly_publish`` is allowlisted because its
    ``rev-parse`` answers a different question: which commit the generated publication branch
    landed, which is not which commit produced this build.
    """

    allowed = {
        Path("src/squadopt/data/source_revision.py"),
        Path("src/squadopt/platform/weekly_publish.py"),
    }
    found = {
        path.relative_to(REPOSITORY)
        for path in (REPOSITORY / "src/squadopt").rglob("*.py")
        if "rev-parse" in path.read_text(encoding="utf-8")
    }
    assert found <= allowed, f"A second resolver appeared in {sorted(found - allowed)}."
