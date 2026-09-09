"""Opt-in: the built image, two containers, one shared volume.

Everything about the backend's composition is already proven in-process, and
``test_backend_two_process.py`` proves that two *processes* compose over one store. Neither
can say anything about the artifact a deployment actually runs. This module is the narrow
gate for the layer they cannot reach: the image installs and imports the pinned scientific
stack on linux/amd64, both documented commands run from that one image, a job the api
container writes is computed by the worker container through a shared volume, the answer
survives the api container being replaced, and a forgotten volume is refused rather than
served from ephemeral disk.

It deliberately does **not** restate the process-level tests at container cost. The store
probe's primitives, the gate's TTL, the 503 shape and the worker's honouring of a shutdown
flag are unit- and process-level facts with injected clocks and flags; re-proving them here
would buy wall-clock time and no information.

A green run here is evidence about this machine's local volume. It is not, and must never be
reported as, a validation of an Azure Files NFS mount: cross-container visibility on a cloud
filesystem is a property of that deployment, answered by running the probe there.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import tests.unit.test_advice_worker as worker_fixture
import tests.unit.test_backend_runtime as deployment_fixture

from squadopt.application.advice import COMPUTED_MODE, COMPUTED_WINDOW

pytestmark = pytest.mark.skipif(
    os.environ.get("SQUADOPT_CONTAINER_SMOKE") != "1",
    reason="Opt-in: requires a Docker daemon and a built image (see docs/backend_runbook.md).",
)

REPOSITORY = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("SQUADOPT_CONTAINER_IMAGE", "squadopt-backend:dev")
LEAGUE_ID = deployment_fixture.LEAGUE_ID
ENTRY_ID = deployment_fixture.ENTRY_ID

# The runtime identity the image fixes and the shared mount has to be prepared for. Asserted
# rather than trusted: whoever prepares an Azure Files share needs both numbers, and a base
# image that quietly renumbered them would leave a store the runtime cannot write.
RUNTIME_UID = 10001
RUNTIME_GID = 10001

# The store root is a *subdirectory* of the mount, never the mount root. A share root's mode
# and owner are set by the platform and may not be ours to change; a subdirectory always is.
# It also makes the documented prepare step identical here and on the host.
MOUNT = "/mnt/squadopt-store"
STORE_ROOT = f"{MOUNT}/store"
INPUTS = "/mnt/squadopt-inputs"

API_COMMAND = [
    "uvicorn",
    "--factory",
    "squadopt.api.runtime:build_app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
]
WORKER_COMMAND = ["python", "-m", "squadopt.platform.advice_worker"]

READY_DEADLINE = 60.0
JOB_DEADLINE = 240.0
STOP_GRACE = 120


def _run_docker(*arguments: str, check: bool = True, timeout: float = 180.0) -> tuple[str, str]:
    """One place runs docker, so a failure carries the command that produced it.

    Both streams come back because ``docker logs`` splits them the way the container did:
    the container's stdout on stdout, its stderr on stderr. A caller that keeps only the
    first loses a crashed process's traceback at exactly the moment it is being reported.
    """

    executable = shutil.which("docker")
    assert executable is not None, "Docker CLI not on PATH; this module is opt-in."
    finished = subprocess.run(
        [executable, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and finished.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(arguments)} exited {finished.returncode}\n"
            f"stdout: {finished.stdout}\nstderr: {finished.stderr}"
        )
    return finished.stdout.strip(), finished.stderr.strip()


def _docker(*arguments: str, check: bool = True, timeout: float = 180.0) -> str:
    """The stdout of a docker command, for the callers that want one value."""

    return _run_docker(*arguments, check=check, timeout=timeout)[0]


def _environment_arguments(**overrides: str) -> list[str]:
    """Exactly what the runbook's configuration table names, and nothing else."""

    values = {
        "SQUADOPT_BACKEND_STORE_ROOT": STORE_ROOT,
        "SQUADOPT_BACKEND_SITE_DATA_ROOT": f"{INPUTS}/site",
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT": f"{INPUTS}/snapshots",
        "SQUADOPT_BACKEND_HANDOFF_ROOT": f"{INPUTS}/handoffs",
    }
    values.update(overrides)
    arguments: list[str] = []
    for name, value in values.items():
        arguments += ["--env", f"{name}={value}"]
    return arguments


@pytest.fixture(name="deployment")
def _deployment(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """A volume for the store, a read-only directory for what ops publishes.

    The inputs are read-only on purpose: the api and the worker read captures, handoffs and
    the league tree, and the only thing either of them may write is the store.
    """

    inputs = tmp_path / "inputs"
    snapshot_root = inputs / "snapshots"
    snapshot_id = worker_fixture._capture_with_entries(snapshot_root)
    deployment_fixture._handoff(inputs / "handoffs", snapshot_id)
    deployment_fixture._publish_members(inputs / "site")
    # pytest's basetemp can be 0700, and the mount's own mode is what the container's
    # non-root user sees. Explicit, so this does not pass locally and fail on a runner.
    for directory in (tmp_path, inputs, *(p for p in inputs.rglob("*") if p.is_dir())):
        directory.chmod(0o755)
    for readable in (p for p in inputs.rglob("*") if p.is_file()):
        readable.chmod(0o644)

    suffix = uuid4().hex[:10]
    volume = f"squadopt-store-{suffix}"
    containers: list[str] = []
    state = {
        "volume": volume,
        "inputs": inputs,
        "snapshot_id": snapshot_id,
        "suffix": suffix,
        "containers": containers,
    }
    # The volume is created inside the try, so a prepare step that fails still runs the
    # teardown below. Outside it, a broken mount permission left a named volume behind on
    # every run — and the next developer's `docker volume ls` paid for it.
    try:
        _docker("volume", "create", volume)
        # The documented prepare step, run from the image itself so no second image is
        # needed: the mount arrives root-owned, and the backend will not create its own
        # store root.
        _docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--volume",
            f"{volume}:{MOUNT}",
            IMAGE,
            "sh",
            "-c",
            f"mkdir -p {STORE_ROOT} && chown {RUNTIME_UID}:{RUNTIME_GID} {STORE_ROOT}",
        )
        yield state
    finally:
        for name in containers:
            _docker("rm", "--force", name, check=False, timeout=90.0)
        # `check=False` covers the case this ordering exists for: the create itself failed,
        # so there is nothing to remove.
        _docker("volume", "rm", "--force", volume, check=False, timeout=60.0)


def _start(state: dict[str, Any], role: str, command: Sequence[str], *publish: str) -> str:
    """Start one container from the image under test and remember it for teardown."""

    name = f"squadopt-{role}-{state['suffix']}-{uuid4().hex[:6]}"
    state["containers"].append(name)
    _docker(
        "run",
        "--detach",
        "--name",
        name,
        "--volume",
        f"{state['volume']}:{MOUNT}",
        "--volume",
        f"{state['inputs']}:{INPUTS}:ro",
        *publish,
        *_environment_arguments(),
        IMAGE,
        *command,
    )
    return name


def _origin(container: str) -> str:
    """The published port, read back from the daemon rather than guessed.

    Binding a free port on the host and then handing the number to docker is a race; asking
    docker which port it got is not.
    """

    mapping = _docker("port", container, "8000/tcp")
    return f"http://127.0.0.1:{mapping.rsplit(':', 1)[-1]}"


def _logs(state: dict[str, Any]) -> str:
    """Every container's own account of itself, both streams, for a failure message.

    The worker writes its JSON events to stdout and dies on stderr, so a report that keeps
    one of the two is empty in the case worth reading.
    """

    blocks = []
    for name in state["containers"]:
        out, err = _run_docker("logs", name, check=False, timeout=60.0)
        blocks.append(f"--- {name} stdout ---\n{out}\n--- {name} stderr ---\n{err}")
    return "\n\n".join(blocks)


def _get(url: str, deadline: float, state: dict[str, Any], *, expect: int = 200) -> Any:
    """Bounded polling, never a fixed sleep: the failure names what never arrived."""

    limit = time.monotonic() + deadline
    last = ""
    while time.monotonic() < limit:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == expect:
                    return json.loads(response.read().decode("utf-8"))
                last = f"status {response.status}"
        except urllib.error.HTTPError as error:
            last = f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:200]}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = repr(error)
        time.sleep(0.25)
    pytest.fail(f"{url} never answered {expect} within {deadline}s (last: {last})\n{_logs(state)}")


def _post(origin: str, state: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{origin}/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        data=json.dumps({"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise AssertionError(
            f"POST advice failed: HTTP {error.code} "
            f"{error.read().decode('utf-8', 'replace')[:300]}\n{_logs(state)}"
        ) from error


def test_the_image_is_the_measured_environment_on_the_measured_architecture() -> None:
    """What only a built image can answer, and what ADR 0006 made a correctness claim.

    x86-64 is not a preference here: the solver's determinism and its time budget were
    measured on it, so an image silently built for another architecture would invalidate
    every timing statement the deployment rests on.
    """

    assert _docker("image", "inspect", "--format", "{{.Architecture}}/{{.Os}}", IMAGE) == (
        "amd64/linux"
    )
    assert _docker("run", "--rm", IMAGE, "uname", "-m") == "x86_64"

    uid = _docker("run", "--rm", IMAGE, "id", "-u")
    gid = _docker("run", "--rm", IMAGE, "id", "-g")
    assert (uid, gid) == (str(RUNTIME_UID), str(RUNTIME_GID)), (
        "the shared mount is prepared for this pair; renumbering it silently would leave a "
        "store the runtime cannot write"
    )

    version = _docker("run", "--rm", IMAGE, "python", "-c", "import sys; print(sys.version)")
    assert version.startswith("3.13."), version

    # The pinned scientific stack, not merely importable but the versions constraints.txt
    # names. The declared ranges would install too; that is exactly what must not happen.
    pinned = dict(
        line.split("==", 1)
        for line in (REPOSITORY / "constraints.txt").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith("#")
    )
    installed = json.loads(
        _docker(
            "run",
            "--rm",
            IMAGE,
            "python",
            "-c",
            "import json,importlib.metadata as m;"
            "print(json.dumps({n: m.version(n) for n in "
            "('numpy','scipy','pandas','scikit-learn','ortools','fastapi','uvicorn')}))",
        )
    )
    for name, version_string in installed.items():
        assert version_string == pinned[name], (name, version_string, pinned[name])

    baked = _docker(
        "image",
        "inspect",
        "--format",
        "{{range .Config.Env}}{{println .}}{{end}}",
        IMAGE,
    )
    commit = next(
        line.split("=", 1)[1]
        for line in baked.splitlines()
        if line.startswith("SQUADOPT_REPOSITORY_COMMIT=")
    )
    assert len(commit) == 40 and commit == commit.lower(), commit


def test_a_worker_without_its_volume_refuses_to_start() -> None:
    """The forgotten `--volume`, in its actual shape.

    In-process this is a probe result; here it is the whole process, and the thing worth
    proving at this layer is that the image ships no store of its own to fall back onto.
    """

    executable = shutil.which("docker")
    assert executable is not None
    finished = subprocess.run(
        [executable, "run", "--rm", *_environment_arguments(), IMAGE, *WORKER_COMMAND],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert finished.returncode == 1, (finished.returncode, finished.stdout, finished.stderr)
    # And it says so. Until the advice logger had a handler this stream was empty, which is
    # the difference between a diagnosable deployment and a silent one.
    assert "advice_worker_store_unavailable" in finished.stdout + finished.stderr


def test_two_containers_from_one_image_answer_through_the_shared_volume(
    deployment: dict[str, Any],
) -> None:
    """The whole path, once: accept here, compute there, serve the stored answer.

    The completion below *is* the cross-container visibility evidence. A worker looking at a
    different volume finds no job, so this poll would time out rather than pass; no separate
    negative control is needed to make that claim.
    """

    api = _start(deployment, "api", API_COMMAND, "--publish", "127.0.0.1::8000")
    origin = _origin(api)
    worker = _start(deployment, "worker", WORKER_COMMAND)

    ready = _get(f"{origin}/ready", READY_DEADLINE, deployment)
    assert ready["checks"] == {
        "capture_context": True,
        "league_tree": True,
        "cache_store": True,
    }, ready

    status, accepted = _post(origin, deployment)
    assert status == 202, (status, accepted)
    job_id = accepted["job_id"]

    limit = time.monotonic() + JOB_DEADLINE
    view: Any = None
    while time.monotonic() < limit:
        view = _get(f"{origin}/api/v1/advice-jobs/{job_id}", 30.0, deployment)
        if view["status"] in {"completed", "failed"}:
            break
        time.sleep(0.5)
    assert view is not None and view["status"] == "completed", (view, _logs(deployment))

    served = _get(
        f"{origin}/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
        f"?strategy={COMPUTED_MODE}&window={COMPUTED_WINDOW}",
        30.0,
        deployment,
    )
    assert served["contract_version"] == "provisional_league_ui_v1"
    assert served["payload"]["entry_id"] == ENTRY_ID
    assert served["payload"]["solver_status"] in {"OPTIMAL", "FEASIBLE"}

    # The answer's identity, read from the spec the worker computed against rather than
    # inferred: this is what makes "the right capture and the right code" checkable.
    context = _spec_context(deployment)
    assert context["capture_snapshot_id"] == deployment["snapshot_id"]
    assert context["repository_commit"] == _baked_commit()
    assert served["generated_at_utc"].endswith("Z")

    # The same request again is a read, not a second solve.
    cached_status, cached = _post(origin, deployment)
    assert cached_status == 200, (cached_status, cached)
    assert cached == served

    # The worker container reports what it did. An empty log here is a deployment nobody can
    # diagnose, which is what this used to be.
    assert "advice_worker_started" in _docker("logs", worker, timeout=60.0)

    # A stop the host would issue. `--time` well above the measured 3.0-29.6 s solve, because
    # docker's ten-second default would SIGKILL a busy worker and prove the opposite of the
    # intended claim: exit 0 means the handler ran.
    _docker("stop", "--time", str(STOP_GRACE), worker, timeout=STOP_GRACE + 60)
    assert _docker("inspect", "--format", "{{.State.ExitCode}}", worker) == "0"

    # Replace the api container against the same volume: the completed job and the cached
    # answer are on the store, not in the process that accepted them.
    _docker("rm", "--force", api, timeout=90.0)
    replacement = _start(deployment, "api", API_COMMAND, "--publish", "127.0.0.1::8000")
    new_origin = _origin(replacement)
    _get(f"{new_origin}/ready", READY_DEADLINE, deployment)
    assert _get(f"{new_origin}/api/v1/advice-jobs/{job_id}", 30.0, deployment)["status"] == (
        "completed"
    )
    assert (
        _get(
            f"{new_origin}/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
            f"?strategy={COMPUTED_MODE}&window={COMPUTED_WINDOW}",
            30.0,
            deployment,
        )
        == served
    )


def _baked_commit() -> str:
    baked = _docker(
        "image", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", IMAGE
    )
    return next(
        line.split("=", 1)[1]
        for line in baked.splitlines()
        if line.startswith("SQUADOPT_REPOSITORY_COMMIT=")
    )


def test_compose_runs_the_documented_services_and_preserves_cache(
    deployment: dict[str, Any], tmp_path: Path
) -> None:
    """Exercise the checked-in Compose file, including read-only roots and metrics."""
    store = tmp_path / "compose-store"
    store.mkdir(mode=0o777)
    store.chmod(0o777)
    inputs = deployment["inputs"]
    config = tmp_path / "compose.env"
    values = {
        "SQUADOPT_BACKEND_IMAGE": IMAGE,
        "SQUADOPT_BACKEND_ALLOWED_ORIGINS": "https://example.invalid",
        "SQUADOPT_STORE_PATH": store.as_posix(),
        "SQUADOPT_SITE_PATH": (inputs / "site").as_posix(),
        "SQUADOPT_SNAPSHOT_PATH": (inputs / "snapshots").as_posix(),
        "SQUADOPT_HANDOFF_PATH": (inputs / "handoffs").as_posix(),
        "SQUADOPT_API_PORT": "0",
        "SQUADOPT_WORKER_METRICS_PORT": "0",
    }
    config.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    command = (
        "compose",
        "--project-name",
        f"squadopt-accept-{deployment['suffix']}",
        "--env-file",
        str(config),
        "--file",
        str(REPOSITORY / "deploy/compose.yaml"),
    )
    try:
        _docker(*command, "up", "--detach", "--wait", "--wait-timeout", "90")
        api = _docker(*command, "ps", "--quiet", "api")
        worker = _docker(*command, "ps", "--quiet", "worker")
        deployment["containers"].extend([api, worker])
        origin = _origin(api)
        _get(origin + "/ready", READY_DEADLINE, deployment)
        status, accepted = _post(origin, deployment)
        assert status == 202
        deadline = time.monotonic() + JOB_DEADLINE
        while time.monotonic() < deadline:
            job = _get(f"{origin}/api/v1/advice-jobs/{accepted['job_id']}", 10, deployment)
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.25)
        assert job["status"] == "completed", (job, _logs(deployment))
        cached_status, answer = _post(origin, deployment)
        assert cached_status == 200
        metrics_port = _docker("port", worker, "9091/tcp").rsplit(":", 1)[-1]
        with urllib.request.urlopen(f"http://127.0.0.1:{metrics_port}/metrics", timeout=5) as reply:
            metrics = reply.read().decode()
        assert 'advice_jobs_total{outcome="completed"} 1' in metrics
        assert "advice_solve_seconds_count 1" in metrics
        for container in (api, worker):
            assert (
                _docker("inspect", "--format", "{{.HostConfig.ReadonlyRootfs}}", container)
                == "true"
            )
        _docker(*command, "up", "--detach", "--force-recreate", "--no-deps", "api")
        replacement = _docker(*command, "ps", "--quiet", "api")
        deployment["containers"].append(replacement)
        origin = _origin(replacement)
        _get(origin + "/ready", READY_DEADLINE, deployment)
        assert _post(origin, deployment) == (200, answer)
    finally:
        output, error = _run_docker(*command, "logs", "--no-color", check=False)
        (tmp_path / "compose.log").write_text(output + "\n" + error, encoding="utf-8")
        _docker(*command, "down", "--timeout", "180", check=False, timeout=240)


def _spec_context(state: dict[str, Any]) -> dict[str, str]:
    """The one spec on the store, read as root because the host user is not 10001."""

    document = _docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "--volume",
        f"{state['volume']}:{MOUNT}",
        IMAGE,
        "python",
        "-c",
        "import glob,json,sys;"
        f"paths=sorted(glob.glob('{STORE_ROOT}/specs/*/*.json'));"
        "print(json.dumps(json.load(open(paths[0]))) if paths else 'null')",
    )
    parsed = json.loads(document)
    assert parsed is not None, "no advice job spec was written beside the answer"
    return {key: str(value) for key, value in parsed["context"].items()}
