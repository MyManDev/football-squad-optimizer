"""Offline Python publisher -> real TypeScript consumer, including index addresses."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_league_views as fixture

from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.platform.advice_documents import validate_advice_document

pytestmark = pytest.mark.skipif(
    os.environ.get("SQUADOPT_PUBLICATION_CONTRACT") != "1",
    reason="Opt-in cross-language acceptance requires installed web dependencies.",
)
world = fixture.world
ROOT = Path(__file__).resolve().parents[2]


def test_python_publication_is_consumed_by_typescript(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = fixture._world_context(world)
    squad = fixture._legal_squad(world)
    output = tmp_path / "league"
    report = build_league_views(
        fixture._Provider(
            {
                identifier: fixture._member_picks(world, identifier, squad)
                for identifier in (101, 202)
            }
        ),
        tuple(
            EntryRegistration(identifier, f"member-{identifier}", "2026-08-23T00:00:00Z")
            for identifier in (101, 202)
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Contract fixture",
        out_dir=output,
        standings=fixture._two_member_standings(),
        now=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    assert report.rendered_count == 2
    documents = []
    for path in sorted(output.rglob("*.json")):
        relative = path.relative_to(output).as_posix()
        if relative.startswith("advice/") and path.name != "index.json":
            validate_advice_document(path.read_bytes())
        documents.append({"path": relative, "document": json.loads(path.read_bytes())})
    bundle = tmp_path / "publication.json"
    bundle.write_text(json.dumps(documents), encoding="utf-8")
    node = shutil.which("node")
    assert node, "The cross-language acceptance job requires Node."
    result = subprocess.run(
        [
            node,
            "node_modules/vitest/vitest.mjs",
            "run",
            "src/features/league/advice/publicationContract.test.ts",
        ],
        cwd=ROOT / "web",
        env={**os.environ, "SQUADOPT_PUBLICATION_FIXTURE": str(bundle)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
