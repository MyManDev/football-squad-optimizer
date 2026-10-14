"""Each file adapter of `squadopt.platform.storage` conforms to the port it stands behind.

ADR 0011 (decision 1) builds the storage ports: a Protocol declared in the innermost ring that
consumes it (`squadopt.application.ports`, `squadopt.data.capture` or `squadopt.live.ports`),
mirroring an existing `data` function one for one, and behind it a file adapter in
`squadopt.platform.storage`: a stateless frozen slots dataclass, exported as a module-level
singleton annotated with its Protocol, that calls the `data` function unchanged. mypy proves
the annotation; this file holds what mypy does not see. Each registered adapter

- is a stateless frozen slots dataclass whose singleton is one module attribute of its home,
  annotated with its port;
- survives a pickle round trip as an equal instance of the same class, which is what the league
  stage's process pool asks of it;
- carries every port method with the same `inspect.signature`, so a port and its adapter cannot
  drift apart in a parameter's name, kind, default or annotation;
- answers a sample call with what the wrapped `data` function answers for the same arguments.

The registry is empty: ADR 0011 created the two homes before the first group lands, and the
pull request that lands a group registers its adapters here, one entry per wrapped function,
and deletes the one test that states the homes are empty. Both homes are docstrings only, with
no barrel, and a port or adapter module that arrives without a registration fails the coverage
test. While the registry is empty the per-adapter tests report an empty parameter set.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pickle
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Generic, NamedTuple, Protocol

import pandas as pd
import pytest

import squadopt.application.ports as ports_home
import squadopt.platform.storage as storage_home

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PORTS = SOURCE_ROOT / "squadopt" / "application" / "ports"
STORAGE = SOURCE_ROOT / "squadopt" / "platform" / "storage"

#: Where ADR 0011 (decision 1) declares a port: the innermost ring that consumes it.
PORT_HOMES = ("squadopt.application.ports", "squadopt.data.capture", "squadopt.live.ports")

#: The positional and keyword arguments of one call, built under a temporary directory.
Arguments = tuple[tuple[object, ...], Mapping[str, object]]


class Registration(NamedTuple):
    """One adapter singleton, its port, and one port method with the `data` function it wraps."""

    port: type[Any]
    adapter: object
    method: str
    wrapped: Callable[..., object]
    sample: Callable[[Path], Arguments]


#: Every adapter of `squadopt.platform.storage`, one entry per wrapped `data` function,
#: registered by the pull request that lands it.
REGISTRY: tuple[Registration, ...] = ()


def _modules(home: Path) -> set[str]:
    """The dotted names of the modules under a home, apart from its package file."""

    package = ".".join(home.relative_to(SOURCE_ROOT).parts)
    return {f"{package}.{path.stem}" for path in home.glob("*.py") if path.name != "__init__.py"}


def _declared(port: type[Any]) -> dict[str, Any]:
    """The public functions and properties a port declares, its Protocol bases included."""

    found: dict[str, Any] = {}
    for klass in reversed(port.__mro__):
        if klass in (object, Protocol, Generic):
            continue
        for name, member in vars(klass).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(member) or isinstance(member, property):
                found[name] = member
    return found


def _adapters() -> list[Registration]:
    """One entry per adapter, for the checks that do not depend on the method."""

    first: dict[int, Registration] = {}
    for entry in REGISTRY:
        first.setdefault(id(entry.adapter), entry)
    return list(first.values())


def _same(answer: object, expected: object) -> bool:
    if isinstance(answer, pd.DataFrame | pd.Series):
        return type(expected) is type(answer) and bool(answer.equals(expected))
    return bool(answer == expected)


each_adapter = pytest.mark.parametrize(
    "entry", _adapters(), ids=[type(entry.adapter).__name__ for entry in _adapters()]
)
each_call = pytest.mark.parametrize(
    "entry", REGISTRY, ids=[f"{type(entry.adapter).__name__}.{entry.method}" for entry in REGISTRY]
)


@pytest.mark.parametrize("home", [ports_home, storage_home], ids=["ports", "storage"])
def test_a_home_is_a_docstring_only_with_no_barrel(home: ModuleType) -> None:
    """ADR 0011: each package file is a docstring; a port or adapter is imported by its module."""

    assert home.__file__ is not None
    tree = ast.parse(Path(home.__file__).read_text(encoding="utf-8"))

    assert ast.get_docstring(tree), home.__name__
    assert [type(node).__name__ for node in tree.body] == ["Expr"], home.__name__


def test_the_registry_covers_every_module_of_both_homes() -> None:
    """A port module or an adapter module lands with its registration.

    The adapter side is exact: every module of `platform.storage` holds a registered adapter,
    and every registered adapter lives there. The port side is a subset, because
    `CaptureReader` and `LedgerStore` are declared in `data` and `live`, where the other
    consumers of those ports sit.
    """

    registered_ports = {entry.port.__module__ for entry in REGISTRY}
    registered_adapters = {type(entry.adapter).__module__ for entry in REGISTRY}

    assert _modules(PORTS) <= registered_ports
    assert _modules(STORAGE) == registered_adapters
    assert [
        module
        for module in sorted(registered_ports)
        if module not in PORT_HOMES and module.rpartition(".")[0] not in PORT_HOMES
    ] == []


def test_the_homes_hold_no_module_until_the_first_group_lands() -> None:
    """The one test the first group's pull request deletes: both homes are empty today.

    It states the empty registry as a fact of this tree, rather than leaving it to a
    parametrize that matched nothing; the coverage test above keeps the registry and the homes
    in step once it goes.
    """

    assert _modules(PORTS) == set()
    assert _modules(STORAGE) == set()
    assert REGISTRY == ()


@each_adapter
def test_the_adapter_is_a_stateless_frozen_slots_dataclass_singleton(entry: Registration) -> None:
    adapter = entry.adapter
    klass = type(adapter)

    assert dataclasses.is_dataclass(adapter) and not isinstance(adapter, type)
    assert dataclasses.fields(adapter) == (), "stateless: the adapter holds no field"
    assert klass.__dataclass_params__.frozen, "frozen"
    assert "__slots__" in vars(klass), "slots"
    assert getattr(entry.port, "_is_protocol", False), "the port is a Protocol"

    module = importlib.import_module(klass.__module__)
    names = [name for name, value in vars(module).items() if value is adapter]
    assert len(names) == 1, "one module-level singleton"
    annotation = module.__annotations__.get(names[0])
    assert annotation is not None and entry.port.__name__ in str(annotation), (
        "annotated with its port"
    )


@each_adapter
def test_the_adapter_survives_a_pickle_round_trip(entry: Registration) -> None:
    copy = pickle.loads(pickle.dumps(entry.adapter, protocol=pickle.HIGHEST_PROTOCOL))

    assert type(copy) is type(entry.adapter)
    assert copy == entry.adapter


@each_adapter
def test_every_port_method_keeps_its_signature_on_the_adapter(entry: Registration) -> None:
    declared = _declared(entry.port)
    assert declared, "a port declares at least one method"

    for name, port_member in declared.items():
        adapter_member = inspect.getattr_static(type(entry.adapter), name, None)
        assert adapter_member is not None, name
        if isinstance(port_member, property):
            assert isinstance(adapter_member, property), name
            port_function, adapter_function = port_member.fget, adapter_member.fget
        else:
            port_function, adapter_function = port_member, adapter_member
        assert inspect.signature(adapter_function, eval_str=True) == inspect.signature(
            port_function, eval_str=True
        ), name


@each_call
def test_the_adapter_answers_a_sample_call_as_the_data_function_does(
    entry: Registration, tmp_path: Path
) -> None:
    assert entry.method in _declared(entry.port), "the sample calls a port method"
    args, kwargs = entry.sample(tmp_path)

    answer = getattr(entry.adapter, entry.method)(*args, **kwargs)
    expected = entry.wrapped(*args, **kwargs)

    assert _same(answer, expected)
