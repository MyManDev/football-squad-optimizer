"""Every rename in the package goes through ``squadopt.data.atomic``.

On Windows a rename is refused with ``PermissionError`` while any process holds a handle on
the file, and ``replace_retrying`` is the one place that waits that out and then names the
refusal. A module that calls ``os.replace`` itself has its own answer to that, which is how
a weekly run once stopped while another process was reading its ``run.json``. So outside
``data/atomic.py`` the package calls none of ``os.replace``, ``os.rename``, ``os.renames``
or ``shutil.move``.

``Path.rename(target)`` and ``Path.replace(target)`` are the same call, so a one-argument
``.rename``/``.replace`` is refused too, in the packages where that shape is a path:
``api``, ``platform``, ``application`` and ``live``. Elsewhere the same shape is also a
pandas Series call (``Series.replace`` swaps values in ``experiments/positional_defence.py``
and ``Series.rename`` names the result in ``prediction/baseline.py``), so the rule does
not reach there.

``os.link`` is not counted. It is the create-once primitive, and the sites that use it
refuse to overwrite on purpose.
"""

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "squadopt"
PRIMITIVE = PACKAGE / "data" / "atomic.py"
RENAMES = {"os": {"replace", "rename", "renames"}, "shutil": {"move"}}
PATH_PACKAGES = ("api", "platform", "application", "live")


def rename_calls(source: str, *, path_methods: bool) -> list[str]:
    """``line: call`` for each rename in ``source``, through any import alias."""

    tree = ast.parse(source)
    modules: dict[str, str] = {}
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name if alias.asname else alias.name.split(".")[0]
                if name in RENAMES:
                    modules[alias.asname or name] = name
        elif isinstance(node, ast.ImportFrom) and node.module in RENAMES:
            for alias in node.names:
                if alias.name in RENAMES[node.module]:
                    functions[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = node.func
        if isinstance(call, ast.Name) and call.id in functions:
            found.append(f"{node.lineno}: {functions[call.id]}")
        elif isinstance(call, ast.Attribute):
            owner = call.value.id if isinstance(call.value, ast.Name) else ""
            module = modules.get(owner)
            if module is not None and call.attr in RENAMES[module]:
                found.append(f"{node.lineno}: {module}.{call.attr}")
            elif (
                path_methods
                and call.attr in {"rename", "replace"}
                and len(node.args) == 1
                and not node.keywords
            ):
                found.append(f"{node.lineno}: .{call.attr}() with one argument")
    return found


def test_only_the_atomic_module_renames() -> None:
    outside = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == PRIMITIVE:
            continue
        relative = path.relative_to(PACKAGE)
        calls = rename_calls(
            path.read_text(encoding="utf-8"), path_methods=relative.parts[0] in PATH_PACKAGES
        )
        outside += [f"{relative.as_posix()}:{call}" for call in calls]
    assert outside == [], (
        "Rename through squadopt.data.atomic.replace_retrying (an overwrite) or "
        "write_bytes_once/write_document_once (a record written once):\n" + "\n".join(outside)
    )


def test_the_scan_sees_the_one_rename_there_is() -> None:
    """A scan that found nothing because it read nothing would pass the test above."""

    calls = rename_calls(PRIMITIVE.read_text(encoding="utf-8"), path_methods=True)
    assert [call.split(": ")[1] for call in calls] == ["os.replace"]


def test_the_pandas_calls_named_above_are_the_calls_in_those_files() -> None:
    """The reason the one-argument rule stops at four packages names real calls."""

    prose = " ".join((__doc__ or "").split())
    named = re.findall(r"``Series\.(rename|replace)`` [a-z ]+ ``([\w/]+\.py)``", prose)
    assert named, "The module docstring names no pandas Series call."
    for method, relative in named:
        assert relative.split("/")[0] not in PATH_PACKAGES, relative
        calls = rename_calls((PACKAGE / relative).read_text(encoding="utf-8"), path_methods=True)
        assert f".{method}() with one argument" in [call.split(": ")[1] for call in calls], (
            f"{relative} has no one-argument .{method}() call."
        )


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("import os\nos.replace(a, b)", ["os.replace"]),
        ("import os.path\nos.rename(a, b)", ["os.rename"]),
        ("import os as system\nsystem.renames(a, b)", ["os.renames"]),
        ("from os import replace as swap\nswap(a, b)", ["os.replace"]),
        ("import shutil\nshutil.move(a, b)", ["shutil.move"]),
        ("staged.rename(target)", [".rename() with one argument"]),
        ("Path(staged).replace(target)", [".replace() with one argument"]),
        ("import os\nos.link(a, b)", []),
        ("text.replace('Z', '+00:00')", []),
        ("moment.replace(tzinfo=UTC)", []),
        ("frame.rename(columns=names)", []),
    ],
)
def test_the_scan_names_each_way_to_rename(source: str, found: list[str]) -> None:
    calls = rename_calls(source, path_methods=True)
    assert [call.split(": ")[1] for call in calls] == found
