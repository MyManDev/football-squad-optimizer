"""ADR 0009's tunnel move and its outage facts agree with the watcher script and with itself.

The record tells the owner how to move the `squadopt-api` connector off the PC. Its first
draft said `start_backend_at_logon.ps1 -Unregister` keeps the PC's connector from coming back.
The script's `-Unregister` removes only the Startup shortcut, and a watcher that is already
running starts a missing connector again a few minutes later, so the move as written would
put two connectors in front of two stores. The same draft placed #821's failed check "half an
hour before the sleep began", reading only the hibernate leg of a sleep that had started hours
earlier.

A later draft listed the compiled pins with Linux wheels for both architectures and left out
`protobuf`, which the image installs because `ortools` requires it.

These checks read the record as the operator would and hold its steps to the script's actual
switches, mutex and timing, its #821 facts to its own outage table, option B's Compose step
to the deploy files it describes, and its list of compiled pins to what the image installs.
A failure names the paragraph to rewrite.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import tomllib
import zlib
from datetime import datetime
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADR = REPOSITORY_ROOT / "docs/architecture/decisions/0009-advice-backend-hosting-options.md"
WATCHER = REPOSITORY_ROOT / "scripts/start_backend_at_logon.ps1"
POWERSHELL = shutil.which("powershell.exe")
WHEEL_PARAGRAPH = "**The ortools wheels are not the obstacle on Arm.**"

WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}
NUMBER_WORDS = {value: word for word, value in WORDS.items()}


def _record() -> str:
    return ADR.read_text(encoding="utf-8")


def _script() -> str:
    return WATCHER.read_text(encoding="ascii")


def _flat(text: str) -> str:
    """Prose with its line breaks and indentation folded, as a reader sees it."""

    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """The text under a heading, up to the next heading of level two or three."""

    start = text.index(heading) + len(heading)
    end = re.search(r"^#{2,3} ", text[start:], re.M)
    return text[start : start + end.start()] if end else text[start:]


def _option(letter: str) -> str:
    return _section(_record(), f"\n### {letter}. ")


def _bullet(section: str, label: str) -> str:
    """The top-level `- **label**` bullet, up to the next top-level bold bullet."""

    start = section.index(f"- **{label}") + 2
    end = re.search(r"^- \*\*", section[start:], re.M)
    return section[start : start + end.start()] if end else section[start:]


def _steps(bullet: str) -> list[str]:
    """The `  N. ` steps of a bullet, in order, each with its continuation lines."""

    return re.split(r"^  \d+\. ", bullet, flags=re.M)[1:]


def _first(steps: list[str], needle: str) -> int:
    for index, step in enumerate(steps):
        if needle in _flat(step):
            return index
    raise AssertionError(f"ADR 0009's tunnel move has no step containing {needle!r}")


def _braced_block(source: str, opening: str) -> str:
    start = source.index(opening) + len(opening)
    depth = 1
    for index in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index]
    raise AssertionError(f"unbalanced block after {opening!r}")


def _mutex() -> str:
    """The mutex name the watcher takes with its default port and connector label."""

    source = _script()
    template = re.search(r'Mutex\(\$false, "([^"]+)"\)', source)
    label = re.search(r'\[string\]\$ConnectorLabel = "([^"]+)"', source)
    port = re.search(r"\[int\]\$Port = (\d+)", source)
    assert template and label and port, "the watcher's mutex or its defaults moved"
    return (
        template.group(1).replace("$Port", port.group(1)).replace("$ConnectorLabel", label.group(1))
    )


def _snippet() -> str:
    step = _steps(_bullet(_option("B"), "Tunnel and DNS"))[0]
    block = re.search(r"```powershell\n(.*?)^\s*```", step, re.S | re.M)
    assert block, "ADR 0009's first move step has no mutex check to run"
    return textwrap.dedent(block.group(1))


def test_unregister_removes_only_the_shortcut_and_no_switch_ends_a_watcher() -> None:
    """The premise of the move's first two steps. If the script gains a stop path, the record's
    step 1 can use it instead of naming the process and the mutex."""

    source = _script()
    unregister = _braced_block(source, "if ($Unregister) {")
    commands = set(re.findall(r"\b[A-Z][a-z]+-[A-Z][A-Za-z]+\b", unregister))
    assert commands == {"Get-StartupShortcut", "Test-Path", "Remove-Item", "Write-Output"}
    switches = set(re.findall(r"\[switch\]\$(\w+)", source))
    assert switches == {"Watch", "DryRun", "Register", "Unregister"}
    assert not re.search(r"Stop-Process|taskkill|\.Kill\(", source)


def test_the_move_ends_the_watcher_before_it_stops_the_pc_connector() -> None:
    steps = _steps(_bullet(_option("B"), "Tunnel and DNS"))
    end = _first(steps, "end any running watcher")
    unregister = _first(steps, "-Unregister")
    stop = _first(steps, "Stop the PC's connector")
    check = _first(steps, "cloudflared tunnel info squadopt-api")
    assert end < stop and unregister < stop < check
    assert "otherwise the watcher" not in _flat(steps[unregister]), (
        "-Unregister does not keep a running watcher from restarting the connector"
    )
    assert "go back to step" in _flat(steps[check]), "two connectors must send the mover back"


def test_the_record_names_the_mutex_the_watcher_takes() -> None:
    cited = set(re.findall(r"Global\\SquadOpt-backend-[\w-]+", _record()))
    assert cited == {_mutex()}
    assert _mutex() in _snippet()


def test_the_move_waits_out_a_missed_watcher_and_states_its_timing() -> None:
    source = _script()
    loop = _braced_block(source, "    do {")
    threshold = max(int(value) for value in re.findall(r"\$threshold = (\d+)", source))
    interval = int(re.findall(r"Start-Sleep -Seconds (\d+)", loop)[0])
    probe = int(re.findall(r"-TimeoutSec (\d+)", loop)[0])

    tunnel = _bullet(_option("B"), "Tunnel and DNS")
    flat = _flat(tunnel)
    assert f"every {interval} s" in flat
    assert f"after {NUMBER_WORDS[threshold]} consecutive checks find none" in flat

    wait = re.search(r"Wait at least (\w+) minutes after step (\d+)", flat)
    assert wait, "the one-connector check must wait out a watcher missed in step 1"
    assert "Stop the PC's connector" in _steps(tunnel)[int(wait.group(2)) - 1]
    # The slowest restart: each miss is a full interval plus a health probe that times out.
    assert WORDS[wait.group(1)] * 60 > threshold * (interval + probe)


def test_the_compose_gap_cites_the_file_that_states_it() -> None:
    """Option B's Compose step says the file mounts neither optional input and names where that
    is written down. `deploy/compose.yaml` carries no comment about them;
    `deploy/backend.env.example` does."""

    steps = _steps(_bullet(_option("B"), "Migration steps"))
    step = next(_flat(step) for step in steps if "Change `deploy/compose.yaml`" in step)
    inputs = ("SQUADOPT_BACKEND_ARTIFACT_ROOT", "SQUADOPT_BACKEND_CLUB_NEWS_SOURCE")
    assert f"mounts neither `{inputs[0]}` nor `{inputs[1]}`" in step

    compose = (REPOSITORY_ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    example = (REPOSITORY_ROOT / "deploy/backend.env.example").read_text(encoding="utf-8")
    assert not any(name in compose for name in inputs), "Compose now mounts an optional input"
    assert "the Compose file does not mount these" in example
    assert all(f"# {name}=" in example for name in inputs)
    assert "Its own comment" not in step
    assert "as `deploy/backend.env.example` says" in step


def _pins() -> dict[str, str]:
    """`constraints.txt`'s pins, by normalized name."""

    pins: dict[str, str] = {}
    for line in (REPOSITORY_ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.lstrip().startswith("#"):
            name, version = line.strip().split("==", 1)
            pins[canonicalize_name(name)] = version
    return pins


def _image_installs() -> set[str]:
    """What the Dockerfile's `pip install ".[api]"` installs on Linux, by normalized name.

    Walked from the installed distributions' own requirements, so a new transitive dependency
    shows up without this list being edited.
    """

    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    linux = {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"}
    pending = [
        Requirement(spec)
        for spec in project["project"]["dependencies"]
        + project["project"]["optional-dependencies"]["api"]
    ]
    installs: set[str] = set()
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        if name in installs:
            continue
        installs.add(name)
        try:
            requires = distribution(name).requires or []
        except PackageNotFoundError:
            pytest.skip(f"{name} is not installed, so the image's closure cannot be walked")
        for spec in requires:
            nested = Requirement(spec)
            if nested.marker is None or nested.marker.evaluate(linux):
                pending.append(nested)
    return installs


def _compiled(name: str) -> bool:
    return "Root-Is-Purelib: false" in (distribution(name).read_text("WHEEL") or "")


def test_the_arm_wheel_paragraph_names_every_compiled_pin_the_image_installs() -> None:
    """Option C rests on this paragraph: it lists the compiled pins the image installs and the
    Linux wheel each one publishes for both architectures. An omitted pin is a wheel nobody
    checked, which is how `protobuf` was missed."""

    record = _flat(_record())
    start = record.index(WHEEL_PARAGRAPH)
    paragraph = record[start : record.index("Packaging does not require x86-64.", start)]
    listed, _, others = paragraph.partition("The image installs no other compiled pin")

    pins = _pins()

    def named(text: str) -> dict[str, str | None]:
        """Backticked pin names, with the version where the text writes `name==version`."""

        found: dict[str, str | None] = {}
        for token in re.findall(r"`([^`]+)`", text):
            name, _, version = token.partition("==")
            if canonicalize_name(name) in pins:
                found[canonicalize_name(name)] = version or None
        return found

    image = _image_installs()
    compiled = {name for name in image & set(pins) if _compiled(name)}
    assert set(named(listed)) == compiled, "rewrite the wheel list to match the image"
    for name, version in named(listed).items():
        assert version in (None, pins[name]), f"{name} is pinned at {pins[name]}"

    requires = distribution("ortools").requires or []
    assert "protobuf" in {canonicalize_name(Requirement(spec).name) for spec in requires}
    protobuf = listed[listed.index("- `protobuf`") :]
    assert "which `ortools` requires" in protobuf
    assert "`cp39-abi3`" in protobuf and "not a `cp313` wheel" in protobuf

    assert named(others), "the paragraph must say which compiled pins the image leaves out"
    assert not set(named(others)) & image


@pytest.mark.parametrize(
    ("letter", "start", "end"),
    [("D", "**Keep the tunnel.**", "**Drop the tunnel.**"), ("E", None, None)],
)
def test_a_cloud_connector_starts_only_after_the_pc_one_is_out(
    letter: str, start: str | None, end: str | None
) -> None:
    text = _bullet(_option(letter), "Tunnel and DNS")
    if start is not None and end is not None:
        text = text[text.index(start) : text.index(end)]
    flat = _flat(text)
    order = ("end any running watcher", "-Unregister", "stop the PC's connector")
    positions = [flat.find(step) for step in order]
    assert -1 not in positions and positions == sorted(positions), flat
    assert "exactly one connector" in flat


@pytest.mark.parametrize("letter", ["B", "D", "E"])
def test_every_rollback_starts_a_watcher_now(letter: str) -> None:
    rollback = _flat(_bullet(_option(letter), "Rollback"))
    assert "-Register`" in rollback
    if letter == "B":
        assert "-Watch" in rollback and "next logon" in rollback
    else:
        assert "start a watcher now, as in B's rollback" in rollback


def _clock(value: str) -> datetime:
    return datetime.strptime(f"2026-09-25 {value}", "%Y-%m-%d %H:%M:%S")


def test_821_failed_inside_the_sleep_the_record_states() -> None:
    outages = _section(_record(), "### The outage record")
    row = re.search(r"^\| #821 \| 2026-09-25 (\S+) \| 2026-09-25 (\S+) \|", outages, re.M)
    assert row
    opened, closed = _clock(row.group(1) + ":00"), _clock(row.group(2) + ":00")

    blocks = [_flat(block) for block in re.split(r"\n(?=- )|\n\n", outages)]
    evidence = next(block for block in blocks if "The System log shows" in block)
    evidence = evidence[evidence.index("The System log shows") :]
    times = sorted(_clock(value) for value in re.findall(r"(\d\d:\d\d:\d\d)Z", evidence))
    asleep, resumed = times[0], times[-1]
    assert asleep < opened < resumed, "the failed check must fall inside the sleep it names"
    assert '"Button or Lid"' in evidence and "Hibernate from Sleep" in evidence
    if "bound the outages from outside" in _flat(outages):
        assert opened <= asleep and resumed <= closed


def test_821_is_not_cited_for_a_mode_nobody_observed() -> None:
    for sentence in re.split(r"(?<=[.:])\s+(?=[-A-Z(*#])", _flat(_record())):
        if "#821" in sentence:
            assert not re.search(r"not reachable|unreachable|not serving", sentence), sentence


def test_the_first_suggested_step_names_every_setting_that_slept_the_pc() -> None:
    order = _section(_record(), "## Suggested order")
    first = _flat(order[order.index("1. **A,") : order.index("2. **")])
    for setting in ("lid-close", "power-button", "hibernate timeout", "idle sleep timeout"):
        assert setting in first, setting


@pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")
def test_the_documented_mutex_check_sees_a_running_watcher(tmp_path: Path) -> None:
    """Run the record's own check while a mocked watcher loop holds the mutex, then after it
    exits. A distinct port and label keep it away from the owner's live watcher."""

    port = 20000 + zlib.crc32(str(tmp_path).encode()) % 20000
    label = "adr-check"
    snippet = _snippet().replace(_mutex(), f"Global\\SquadOpt-backend-{port}-{label}")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_backend_local.ps1").write_text("throw 'no run'", encoding="ascii")
    cloudflared = tmp_path / "cloudflared.exe"
    cloudflared.touch()
    check = tmp_path / "check.ps1"
    check.write_text(snippet, encoding="ascii")

    def quoted(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    harness = tmp_path / "harness.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest {{ return @{{StatusCode=200}} }}
function Get-CimInstance {{
    return @{{CommandLine='cloudflared tunnel --label {label} run test-tunnel'}}
}}
function Start-Process {{ throw 'must not launch' }}
function Start-Sleep {{
    param($Seconds)
    Write-Output ('DURING=' + (& {quoted(check)}))
    throw 'TEST_FINISHED'
}}
try {{
    & {quoted(WATCHER)} -RepoRoot {quoted(tmp_path)} -Port {port} -TunnelName test-tunnel `
        -ConnectorLabel {label} -Cloudflared {quoted(cloudflared)} -Watch
}} catch {{
    if ($_.Exception.Message -ne 'TEST_FINISHED') {{ throw }}
}}
Write-Output ('AFTER=' + (& {quoted(check)}))
""",
        encoding="ascii",
    )
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert "DURING=True" in result.stdout, result.stdout + result.stderr
    assert "AFTER=False" in result.stdout, result.stdout + result.stderr
