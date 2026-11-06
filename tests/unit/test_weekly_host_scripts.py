"""The provisioning and readiness scripts of the weekly schedule's host (#1243), read as text.

`deploy/weekly-schedule/provision.sh` sets up a fresh Contabo Cloud VPS on Ubuntu 24.04 as root,
and `check_host.sh` reports on it read-only. Neither can run here, so these tests hold what can
be held without the host: both parse under `bash -n`; the provisioning refuses any OS but
Ubuntu 24.04, and a user who is not root, before it changes anything (run for real, with a
fixture in place of `/etc/os-release`); each step that changes the host checks first, so a
second run changes nothing; it writes no secret; it installs the dry-run drop-in on a first
provisioning only and enables the timer; and its paths are the units' paths. Its checkout
runs for real on local repositories, with the script sourced and its main not run: cloned from
#1262's branch (`SQUADOPT_REF`), then moved to `develop` once the units are there, refusing
local changes, an unknown branch, a branch without the units and a fast-forward git cannot
make. The readiness report writes nothing and prints no token.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOST_FILES = Path(__file__).resolve().parents[2] / "deploy" / "weekly-schedule"
PROVISION = HOST_FILES / "provision.sh"
CHECK = HOST_FILES / "check_host.sh"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    BASH is None or sys.platform == "win32", reason="the host scripts run under a POSIX bash"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> list[str]:
    """The script's lines without comment lines, which may name what the code must not do."""

    return [line for line in _text(path).splitlines() if not line.lstrip().startswith("#")]


def _readonly(path: Path) -> dict[str, str]:
    pairs = re.findall(r"^readonly ([A-Z_]+)=([^\s(]+)$", _text(path), flags=re.MULTILINE)
    return {name: value.strip('"') for name, value in pairs}


def _unit(name: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for line in _text(HOST_FILES / name).splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            directives.setdefault(key.strip(), []).append(value.strip())
    return directives


@needs_bash
@pytest.mark.parametrize("script", [PROVISION, CHECK], ids=lambda path: path.name)
def test_both_scripts_parse_and_say_how_they_fail(script: Path) -> None:
    parsed = subprocess.run([BASH or "bash", "-n", str(script)], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
    lines = _text(script).splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    # The provisioning stops at the first failure; the report goes on past a failed check.
    expected = "set -euo pipefail" if script == PROVISION else "set -uo pipefail"
    assert expected in lines


def _provision(
    tmp_path: Path, os_release: str, ref: str | None = None
) -> subprocess.CompletedProcess[str]:
    fixture = tmp_path / "os-release"
    fixture.write_text(os_release, encoding="utf-8")
    environment = {"PATH": os.environ.get("PATH", ""), "SQUADOPT_OS_RELEASE": str(fixture)}
    if ref is not None:
        environment["SQUADOPT_REF"] = ref
    return subprocess.run(
        [BASH or "bash", str(PROVISION)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@needs_bash
@pytest.mark.parametrize(
    "os_release,host",
    [
        ('ID=ubuntu\nVERSION_ID="22.04"\n', "ubuntu 22.04"),
        ('ID=ubuntu\nVERSION_ID="24.10"\n', "ubuntu 24.10"),
        ('ID=debian\nVERSION_ID="12"\n', "debian 12"),
        ("NAME=unknown\n", "unknown unknown"),
    ],
)
def test_the_provisioning_refuses_any_os_but_ubuntu_24_04_before_anything_else(
    tmp_path: Path, os_release: str, host: str
) -> None:
    refused = _provision(tmp_path, os_release)
    assert refused.returncode == 1
    assert refused.stderr.strip() == (
        f"Refused: this provisions Ubuntu 24.04 only, and this host is {host}"
    )
    assert refused.stdout == ""


@needs_bash
@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="as root it would provision this machine"
)
def test_on_ubuntu_24_04_it_still_refuses_a_user_who_is_not_root(tmp_path: Path) -> None:
    refused = _provision(tmp_path, 'ID=ubuntu\nVERSION_ID="24.04"\n')
    assert (refused.returncode, refused.stderr.strip(), refused.stdout) == (
        1,
        "Refused: run as root: bash provision.sh",
        "",
    )


@needs_bash
@pytest.mark.parametrize("ref", ["feature/x;rm -rf /", "../develop", "-develop", "feature/", ""])
def test_a_ref_that_names_no_branch_is_refused_before_anything_else(
    tmp_path: Path, ref: str
) -> None:
    refused = _provision(tmp_path, 'ID=ubuntu\nVERSION_ID="24.04"\n', ref)
    expected = f"Refused: SQUADOPT_REF must name a branch, not '{ref}'"
    if ref == "":
        # An empty SQUADOPT_REF is no SQUADOPT_REF: develop, and the root check after it.
        expected = "Refused: run as root: bash provision.sh"
    if ref == "" and os.geteuid() == 0:
        pytest.skip("as root it would provision this machine")
    assert (refused.returncode, refused.stderr.strip(), refused.stdout) == (1, expected, "")


def test_preflight_comes_before_the_first_step_that_changes_the_host() -> None:
    main = _text(PROVISION).split("main() {", 1)[1].split("}", 1)[0].split()
    assert main[:3] == ["preflight", "cd", "/"]
    assert main[3:] == [
        "packages",
        "github_cli",
        "python313",
        "service_user",
        "checkout",
        "venv",
        "swap",
        "firewall",
        "security_updates",
        "journal_cap",
        "ssh_hardening",
        "units",
        "steps_left",
    ]


#: Each step that changes the host, and the check it makes first, so that a second run of the
#: script changes nothing the first one set up.
GUARDED = [
    ('if [ ! -s "$keyring" ]; then', "curl -fsSL https://cli.github.com/packages/"),
    ("if ! compgen -G '/etc/apt/sources.list.d/deadsnakes-ubuntu-ppa-*'", "add-apt-repository"),
    ('if ! getent passwd "$SERVICE_USER"', "useradd --system"),
    ('if [ ! -d "$target/.git" ]; then', 'git clone -q --branch "$ref"'),
    ('if [ ! -x "$CHECKOUT/.venv/bin/python" ]; then', "-m venv"),
    ('if [ -z "$(swapon --show --noheadings)" ]; then', "fallocate"),
    ('! grep -qE "^$SWAP_FILE[[:space:]]" /etc/fstab', ">>/etc/fstab"),
    ('if [ ! -e "$ENVIRONMENT_FILE" ]; then', 'write_if_changed "$ENVIRONMENT_FILE" 0600'),
    ('if [ "$first" = yes ] || [ -e "$DROP_INS/dry-run.conf" ]; then', "dry-run.conf"),
    ("if [ ! -s /root/.ssh/authorized_keys ]; then", "return 0"),
]


@pytest.mark.parametrize("guard,step", GUARDED, ids=[step for _, step in GUARDED])
def test_each_step_that_changes_the_host_checks_first(guard: str, step: str) -> None:
    lines = _code(PROVISION)
    (at,) = [index for index, line in enumerate(lines) if guard in line]
    assert any(step in line for line in lines[at : at + 5]), (guard, lines[at : at + 5])


def test_files_are_written_only_when_they_change_and_one_line_is_ever_appended() -> None:
    code = "\n".join(_code(PROVISION))
    assert 'cmp -s "$staged" "$target"' in code
    appended = [line for line in _code(PROVISION) if ">>" in line]
    assert appended == ["    printf '%s none swap sw 0 0\\n' \"$SWAP_FILE\" >>/etc/fstab"]


SECRETS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"-----BEGIN"),
    re.compile(r"--with-token|--show-token|chpasswd"),
    re.compile(r"^\s*(export\s+)?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*=\S", re.MULTILINE),
]


@pytest.mark.parametrize("script", [PROVISION, CHECK], ids=lambda path: path.name)
def test_neither_script_holds_or_prints_a_secret(script: Path) -> None:
    text = _text(script)
    assert [pattern.pattern for pattern in SECRETS if pattern.search(text)] == []
    # The environment file the provisioning creates holds comments only.
    if script == PROVISION:
        template = text.split('write_if_changed "$ENVIRONMENT_FILE" 0600 <<CONF', 1)[1]
        body = template.split("\n", 1)[1].split("\nCONF\n", 1)[0].splitlines()
        assert body and all(line.startswith("#") for line in body), body


def test_the_dry_run_drop_in_is_installed_and_the_timer_enabled() -> None:
    code = "\n".join(_code(PROVISION))
    assert 'install -m 0644 "$source/dry-run.conf" "$DROP_INS/dry-run.conf"' in code
    assert '[ -e "$UNITS/weekly-schedule.service" ] || first=yes' in code
    assert (
        'install -m 0644 "$source/weekly-schedule.service" "$source/weekly-schedule.timer" '
        '"$UNITS/"'
    ) in code
    assert code.index('dry-run.conf"') < code.index("systemctl enable --now weekly-schedule.timer")
    assert "printf '[Service]\\nEnvironment=WEEKLY_WORKERS=%s\\n' \"$(nproc)\"" in code


def test_python_3_13_is_the_version_the_repository_pins_and_installs_as_ci_does() -> None:
    root = HOST_FILES.parents[1]
    assert "Python 3.13" in _text(root / "constraints.txt").splitlines()[1]
    assert 'python_version = "3.13"' in _text(root / "pyproject.toml")
    code = "\n".join(_code(PROVISION))
    assert "add-apt-repository -y ppa:deadsnakes/ppa" in code
    assert "apt-get install -y -q python3.13 python3.13-venv" in code
    assert "assert sys.version_info[:2] == (3, 13)" in code
    assert '-m pip install -q -c "$CHECKOUT/constraints.txt" -e "${CHECKOUT}[llm]"' in code


def test_the_scripts_and_the_units_name_one_layout() -> None:
    provision, check = _readonly(PROVISION), _readonly(CHECK)
    service, dry_run = _unit("weekly-schedule.service"), _unit("dry-run.conf")
    checkout = provision["CHECKOUT"]
    assert (provision["SERVICE_HOME"], checkout) == ("/srv/squadopt", "/srv/squadopt/weekly")
    assert service["WorkingDirectory"] == [checkout]
    assert service["User"] == service["Group"] == [provision["SERVICE_USER"]]
    assert service["EnvironmentFile"] == [provision["ENVIRONMENT_FILE"]]
    for command in (service["ExecStart"][-1], dry_run["ExecStart"][-1]):
        assert command.startswith(f"{checkout}/.venv/bin/python ")
        assert f"--workspace {checkout} " in command
    assert {key: check[key] for key in ("SERVICE_USER", "CHECKOUT", "ENVIRONMENT_FILE")} == {
        key: provision[key] for key in ("SERVICE_USER", "CHECKOUT", "ENVIRONMENT_FILE")
    }
    assert check["DROP_INS"] == provision["DROP_INS"]
    assert provision["DROP_INS"] == "/etc/systemd/system/weekly-schedule.service.d"


def test_ssh_passwords_are_turned_off_only_once_root_has_a_key() -> None:
    code = "\n".join(_code(PROVISION))
    hardening = code.split("ssh_hardening() {", 1)[1].split("\n}\n", 1)[0]
    assert hardening.index("[ ! -s /root/.ssh/authorized_keys ]") < hardening.index(
        "PasswordAuthentication no"
    )
    assert "10-squadopt-hardening.conf" in hardening  # read before 50-cloud-init.conf
    assert hardening.index("sshd -t") < hardening.index("systemctl try-reload-or-restart ssh")


def test_the_readiness_report_changes_nothing_and_prints_no_token() -> None:
    code = "\n".join(_code(CHECK))
    changing = re.compile(
        r"apt-get|\binstall\s|useradd|\brm\s|mkdir|chmod|chown|\btee\b|>>|>\s*/(?!dev/null)"
        r"|systemctl (enable|disable|start|stop|restart|reload|daemon-reload)|\bufw (allow|enable)"
    )
    assert changing.findall(code) == []
    assert "grep -vi token" in code and "--show-token" not in code


def test_the_scripts_and_the_guide_hold_no_long_dash() -> None:
    for path in (PROVISION, CHECK, HOST_FILES / "README.md", *HOST_FILES.glob("*.conf")):
        assert not {chr(0x2013), chr(0x2014)} & set(_text(path)), path


FEATURE = "feature/the-scheduled-run-releases-itself-on-any-host"
UNITS = "deploy/weekly-schedule/weekly-schedule.service"


def _git(cwd: Path, *arguments: str) -> str:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(cwd),
        "GIT_CONFIG_NOSYSTEM": "1",
        **{
            f"GIT_{who}_{what}": value
            for who in ("AUTHOR", "COMMITTER")
            for what, value in (("NAME", "Host Test"), ("EMAIL", "host@example.invalid"))
        },
    }
    done = subprocess.run(
        ["git", *arguments], cwd=cwd, env=environment, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _commit(work: Path, path: str, text: str) -> str:
    (work / path).parent.mkdir(parents=True, exist_ok=True)
    (work / path).write_text(text, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", f"add {path}")
    return _git(work, "rev-parse", "HEAD")


@pytest.fixture
def origin(tmp_path: Path) -> tuple[Path, Path]:
    """`develop` without the units, #1262's branch with them, and a bare origin of both."""

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "develop")
    _commit(work, "README.md", "develop\n")
    _git(work, "checkout", "-q", "-b", FEATURE)
    _commit(work, UNITS, "[Service]\n")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    return work, bare


def _checkout_ref(tmp_path: Path, bare: Path, ref: str) -> subprocess.CompletedProcess[str]:
    """`checkout_ref` alone, the script sourced with its main not run and git run as this user.

    The os-release fixture is Debian, so that even a main that ran would refuse at once.
    """

    fixture = tmp_path / "debian"
    fixture.write_text("ID=debian\n", encoding="utf-8")
    run = 'source "$1"; as_user() { "$@"; }; checkout_ref "$2" "$3" "$4"'
    return subprocess.run(
        [
            BASH or "bash",
            "-c",
            run,
            "sourced",
            str(PROVISION),
            str(bare),
            str(tmp_path / "weekly"),
            ref,
        ],
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "SQUADOPT_OS_RELEASE": str(fixture),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@needs_bash
def test_the_host_is_provisioned_from_the_branch_then_moved_to_develop(
    tmp_path: Path, origin: tuple[Path, Path]
) -> None:
    work, bare = origin
    weekly = tmp_path / "weekly"
    first = _checkout_ref(tmp_path, bare, FEATURE)
    assert first.returncode == 0, first.stderr
    head = _git(weekly, "rev-parse", "--short", "HEAD")
    assert first.stdout == f"checkout on {FEATURE} at {head} add {UNITS}\n"
    assert _git(weekly, "rev-parse", "--abbrev-ref", "HEAD") == FEATURE

    # Before the merge, develop has no units: the switch refuses and leaves the branch.
    early = _checkout_ref(tmp_path, bare, "develop")
    assert early.returncode == 1
    assert early.stderr.strip() == (
        "Refused: origin's develop has no deploy/weekly-schedule/ units; the checkout was left "
        "on its branch"
    )
    assert _git(weekly, "rev-parse", "--abbrev-ref", "HEAD") == FEATURE

    # #1262 merges, develop moves on, and the host moves to it.
    _git(work, "checkout", "-q", "develop")
    _git(work, "merge", "-q", "--no-ff", "-m", "merge #1262", FEATURE)
    merged = _commit(work, "CHANGELOG.md", "after the merge\n")
    _git(work, "push", "-q", "origin", "develop")
    moved = _checkout_ref(tmp_path, bare, "develop")
    assert moved.returncode == 0, moved.stderr
    assert _git(weekly, "rev-parse", "HEAD") == merged
    assert _git(weekly, "rev-parse", "--abbrev-ref", "develop@{upstream}") == "origin/develop"
    assert moved.stdout.startswith(f"checkout on develop at {merged[:7]}")

    # Run again: develop fast-forwards to what origin has now.
    later = _commit(work, "NEWS.md", "later\n")
    _git(work, "push", "-q", "origin", "develop")
    assert _checkout_ref(tmp_path, bare, "develop").returncode == 0
    assert _git(weekly, "rev-parse", "HEAD") == later


@needs_bash
def test_a_checkout_with_local_changes_or_an_unknown_branch_is_left_where_it_is(
    tmp_path: Path, origin: tuple[Path, Path]
) -> None:
    work, bare = origin
    weekly = tmp_path / "weekly"
    assert _checkout_ref(tmp_path, bare, FEATURE).returncode == 0
    head = _git(weekly, "rev-parse", "HEAD")

    unknown = _checkout_ref(tmp_path, bare, "no-such-branch")
    assert unknown.returncode == 1
    assert unknown.stderr.strip() == (
        "Refused: origin has no branch no-such-branch; the checkout was left on its branch"
    )

    (weekly / UNITS).write_text("[Service]\nchanged\n", encoding="utf-8")
    dirty = _checkout_ref(tmp_path, bare, FEATURE)
    assert dirty.returncode == 1
    assert dirty.stderr.strip() == (
        f"Refused: the checkout at {weekly} has local changes; it was left on its branch"
    )
    (weekly / UNITS).write_text("[Service]\n", encoding="utf-8")

    # A local commit origin does not have cannot be fast-forwarded: git refuses, nothing moves.
    _commit(weekly, "local.txt", "only here\n")
    _commit(work, "remote.txt", "only there\n")
    _git(work, "push", "-q", "origin", FEATURE)
    local = _git(weekly, "rev-parse", "HEAD")
    diverged = _checkout_ref(tmp_path, bare, FEATURE)
    assert diverged.returncode != 0
    assert (_git(weekly, "rev-parse", "HEAD"), local != head) == (local, True)
    assert _git(weekly, "rev-parse", "--abbrev-ref", "HEAD") == FEATURE


def test_the_ref_in_use_is_printed_and_develop_is_the_default() -> None:
    code = "\n".join(_code(PROVISION))
    assert _readonly(PROVISION)["REF"] == "${SQUADOPT_REF:-$DEVELOP}"
    assert _readonly(PROVISION)["DEVELOP"] == "develop"
    assert 'say "Checkout of $REF at $CHECKOUT"' in code
    assert "== Provisioned from $REF." in code
    assert 'checkout_ref "$REPOSITORY" "$CHECKOUT" "$REF"' in code
    # The checkout never moves under a running tick.
    guard = code.index("systemctl is-active --quiet weekly-schedule.service")
    assert guard < code.index('checkout_ref "$REPOSITORY" "$CHECKOUT" "$REF"')


@needs_bash
def test_a_first_clone_of_a_branch_without_the_units_is_refused(
    tmp_path: Path, origin: tuple[Path, Path]
) -> None:
    _, bare = origin
    refused = _checkout_ref(tmp_path, bare, "develop")
    assert refused.returncode == 1
    assert refused.stderr.strip() == (
        "Refused: the checkout of develop has no deploy/weekly-schedule/ units"
    )
