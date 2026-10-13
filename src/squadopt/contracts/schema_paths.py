"""The one place that names the folder of the committed contract schemas.

The schemas under ``docs/contracts`` are documents of the repository, not files of the
installed package. A schema writer defaults to a path in that folder and the tests read the
committed file by the same path, so the path is built here once (ADR 0011, decision 6),
relative to the working directory exactly as every module built it before: a caller that
runs from a checkout reaches the file, and a caller elsewhere passes its own path. Anchoring
the path to the repository root would change what every writer and test does, so that is a
separate decision for the owner.
"""

import re
from pathlib import Path
from typing import Final

CONTRACT_SCHEMA_DIRECTORY: Final = Path("docs") / "contracts"
"""The folder of the committed schemas, relative to the working directory."""

#: A contract version is a lowercase name and a positive version number: ``ui_view_v1``.
_CONTRACT_VERSION: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*_v[1-9][0-9]*")


def contract_schema_path(contract_version: str) -> Path:
    """The committed schema of ``contract_version``: ``docs/contracts/<name>_v<N>.schema.json``.

    Refuses a name that is not ``<name>_v<N>``, so the path never leaves the folder and a
    schema file is always named by the contract version it holds.
    """

    if _CONTRACT_VERSION.fullmatch(contract_version) is None:
        raise ValueError(
            f"contract_version must be <name>_v<N>, such as ui_view_v1: {contract_version!r}"
        )
    return CONTRACT_SCHEMA_DIRECTORY / f"{contract_version}.schema.json"
