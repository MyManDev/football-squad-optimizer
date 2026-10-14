"""Compatibility re-export of the projection CSV use case.

`optimize_squad_from_csv` moved to `squadopt.application.projection_csv` on 2026-10-13
(ADR 0010, Phase 2). This module keeps the old import path for one release
(docs/architecture/dependency_rules.md, rule 2): it ships in the next `site-*` release and is
removed in the release after it, together with the `integration` layer and its four source
entries in the import contracts of `pyproject.toml`. Import the function from the package root
or from `squadopt.application.projection_csv`.
"""

from squadopt.application.projection_csv import (
    optimize_squad_from_csv as optimize_squad_from_csv,
)
