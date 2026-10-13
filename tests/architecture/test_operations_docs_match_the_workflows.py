"""Two operations documents say things about the workflows; the workflows are read to check them.

`docs/architecture/operations_inventory.md` lists the repository variables. It listed one
after the site build had started reading a second, `ADVICE_API_ORIGIN`, the address that
points the live site at the backend, so a reader who trusted it would not know the variable
exists. Every `vars.<NAME>` a workflow reads must be named in that row.

`docs/architecture/branching.md` said the `Deploy Pages` run history is a complete record of
what was deployed, "because each production job is named after the tag it deployed". The
production job's name is fixed from the tag the source check resolved, before any of its own
steps runs, and runs that deployed nothing carry the same kind of name (run 35287375625 is
named `production site-2026-27-gw05-fix5` and stopped at the daily cap). What says whether a
job deployed is its steps, so the document names them, and the names it cites must be the
workflow's own: a step renamed in the workflow would otherwise leave the document pointing a
reader at a step no run shows.

Neither check reads GitHub. The value of a variable and the history of runs are read with
`gh`, and the documents say which read they quote.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
DEPLOY_PAGES = WORKFLOWS / "deploy-pages.yml"
INVENTORY = REPOSITORY_ROOT / "docs" / "architecture" / "operations_inventory.md"
BRANCHING = REPOSITORY_ROOT / "docs" / "architecture" / "branching.md"
DEPLOYMENT_RUNBOOK = REPOSITORY_ROOT / "docs" / "deployment_runbook.md"

#: The production job's steps that `branching.md` cites to say what a run did.
CAP_STEP = "Stop production at the hard daily cap"
DEPLOY_STEP = "Deploy exact production artifact"
VERIFY_STEP = "Verify production deployment identity"

#: The expression the production job takes its name and its commit message from.
RELEASE_TAG = "${{ needs.production_meta.outputs.release_tag }}"


def _variables_the_workflows_read() -> dict[str, list[str]]:
    """Every `vars.<NAME>` in a workflow, with the workflows that read it."""

    found: dict[str, list[str]] = {}
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        names = set(re.findall(r"\bvars\.([A-Za-z0-9_]+)", workflow.read_text("utf-8")))
        for name in sorted(names):
            found.setdefault(name, []).append(workflow.name)
    return found


def _inventory_row(label: str) -> str:
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {label} |"):
            return line
    raise AssertionError(f"operations_inventory.md has no '{label}' row")


def _production_job() -> str:
    """The text of the `production` job in `deploy-pages.yml`, up to the next job or the end."""

    text = DEPLOY_PAGES.read_text(encoding="utf-8")
    start = re.search(r"^  production:\n", text, re.MULTILINE)
    assert start is not None, "deploy-pages.yml has no job named 'production'"
    following = re.search(r"^  \S", text[start.end() :], re.MULTILINE)
    return text[start.start() : start.end() + (following.start() if following else len(text))]


def _step_names(job: str) -> list[str]:
    return [name.strip() for name in re.findall(r"^      - name: (.+)$", job, re.MULTILINE)]


def _step(job: str, name: str) -> str:
    """The text of one step, from its `- name:` line to the next step."""

    start = job.index(f"      - name: {name}\n")
    following = job.find("\n      - name: ", start + 1)
    return job[start : following if following != -1 else len(job)]


def test_every_variable_a_workflow_reads_is_named_in_the_inventory() -> None:
    """A variable the build reads and the inventory omits is configuration nobody can find."""

    read = _variables_the_workflows_read()
    # If this is ever empty the pattern has stopped matching and the test is asleep.
    assert "CLOUDFLARE_PAGES_PROJECT" in read, f"no workflow reads the Pages project; found {read}"

    row = _inventory_row("Repository variables")
    missing = [
        f"{name} (read by {', '.join(workflows)})"
        for name, workflows in read.items()
        if f"`{name}=" not in row and f"`{name}`" not in row
    ]
    assert not missing, (
        "operations_inventory.md's 'Repository variables' row does not name these variables, "
        "which the workflows read: " + "; ".join(missing)
    )


def test_the_production_job_is_named_before_any_of_its_steps_runs() -> None:
    """The name comes from the source check's output, so it cannot say whether a deploy happened.

    This is the fact `branching.md` rests on when it says the run history is not a record of
    what was deployed. If the name ever came from something the job itself did, the document
    would have to change with it.
    """

    job = _production_job()
    name = re.search(r"^    name: (.+)$", job, re.MULTILINE)
    assert name is not None, "the production job has no name"
    assert name.group(1).strip() == f"production {RELEASE_TAG}"
    assert re.search(r"^    needs: production_meta$", job, re.MULTILINE), (
        "the production job no longer takes its tag from the production_meta job"
    )


def test_branching_names_the_steps_that_say_what_a_production_run_did() -> None:
    """The steps `branching.md` cites are the production job's own, and it cites all three."""

    steps = _step_names(_production_job())
    document = BRANCHING.read_text(encoding="utf-8")
    for step in (CAP_STEP, DEPLOY_STEP, VERIFY_STEP):
        assert step in steps, f"deploy-pages.yml's production job has no step {step!r}"
        assert f"`{step}`" in document, (
            f"branching.md does not name the production step `{step}`; without the steps a "
            "reader has only the job's name, which does not say whether it deployed"
        )
    # The order is what makes a success of the deploy step and a failure of the job possible.
    assert steps.index(CAP_STEP) < steps.index(DEPLOY_STEP) < steps.index(VERIFY_STEP)


def test_both_ways_of_deploying_production_leave_the_tag_in_cloudflare() -> None:
    """`branching.md` sends a reader to Cloudflare's list for the tag of a production deploy.

    The workflow and the manual fallback in the deployment runbook both pass it as the commit
    message; a deploy made without it would appear in that list with nothing to find it by.
    """

    deploy = _step(_production_job(), DEPLOY_STEP)
    assert f"--commit-message=release:{RELEASE_TAG}" in deploy

    runbook = DEPLOYMENT_RUNBOOK.read_text(encoding="utf-8")
    fallback = runbook[runbook.index("## Exact-artifact manual fallback") :]
    fallback = fallback[: fallback.index("\n## ", 1)]
    assert re.search(r"pages deploy .*--commit-message release:site-", fallback), (
        "the runbook's manual fallback no longer deploys with a release:<tag> commit message"
    )
    assert "`release:<tag>`" in BRANCHING.read_text(encoding="utf-8")
