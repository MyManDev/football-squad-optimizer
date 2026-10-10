"""The command refuses early, repeated and holdout readings before capture access."""

import json
from types import SimpleNamespace

import pytest
from scripts import read_benchmark_v2_live as cli
from tests.unit.test_benchmark_v2_live import week

from squadopt.data.snapshots import write_snapshot
from squadopt.experiments.benchmark_v2_live import CLAIM_FILE, READING_FILE


@pytest.fixture
def record(tmp_path, monkeypatch):
    """The command's fixed record root and measurements index, kept inside the test."""
    root = tmp_path / "docs"
    root.mkdir()
    monkeypatch.setattr(cli, "RECORD_ROOT", root)
    monkeypatch.setattr(cli, "MEASUREMENTS_INDEX", root / "measurements_index.md")
    return root


def test_command_names_no_record_root():
    with pytest.raises(SystemExit):
        cli.main(["--manifest", "m.json", "--snapshot-root", "s", "--record-root", "elsewhere"])


@pytest.mark.parametrize(
    "refusal", ["early", "repeat", "recorded", "indexed", "holdout", "gap", "undeclared"]
)
def test_command_refusal_opens_no_capture(tmp_path, monkeypatch, record, refusal):
    manifest = tmp_path / "private-manifest.json"
    weeks = [
        {
            "gameweek": week,
            **{
                role + "_snapshot_id": "fpl-live-20261010T080000Z-aabbcc"
                for role in ("decision", "freeze", "cohort", "picks", "outcome")
            },
        }
        for week in range(6, 14)
    ]
    declared = {"first_gameweek": 6, "last_gameweek": 13}
    if refusal == "early":
        weeks = weeks[:7]
    if refusal == "repeat":
        (record / CLAIM_FILE).write_bytes(b"claimed")
    if refusal == "recorded":
        (record / READING_FILE.replace(".json", ".md")).write_text("# Reading", encoding="utf-8")
    if refusal == "indexed":
        (record / "measurements_index.md").write_text(
            "| `benchmark-v2-live-2026-27` | merged reading | |", encoding="utf-8"
        )
    if refusal == "holdout":
        weeks = [
            {**item, "picks_snapshot_id": "fpl-live-20251010T080000Z-aabbcc"} for item in weeks
        ]
    if refusal == "gap":
        weeks = [item for item in weeks if item["gameweek"] != 9] + [{**weeks[-1], "gameweek": 14}]
        declared = {"first_gameweek": 6, "last_gameweek": 14}
    if refusal == "undeclared":
        declared = {}
    manifest.write_text(
        json.dumps({"season": "2026-27", **declared, "weeks": weeks}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "read_snapshot", lambda *_: pytest.fail("Refused capture was opened"))
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: pytest.fail("Early git gate was reached")
    )
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--snapshot-root",
                str(tmp_path / "no-store"),
            ]
        )
        == 1
    )


def test_command_reads_eight_real_format_synthetic_capture_ids(tmp_path, monkeypatch, record):
    store = tmp_path / "store"
    rows = []
    for gameweek in range(6, 14):
        candidate = week(gameweek)
        captures = {}
        for role in ("decision", "cohort"):
            snapshot = getattr(candidate, role)
            captures[role] = write_snapshot(
                store,
                source=snapshot.metadata.source,
                captured_at_utc=snapshot.metadata.captured_at_utc,
                payloads=snapshot.payloads,
            )
        frozen = json.loads(candidate.freeze.payloads["system-decision.json"])
        frozen["snapshot_id"] = captures["decision"].snapshot_id
        frozen_raw = json.dumps(frozen).encode()
        binding = json.loads(candidate.freeze.payloads["benchmark.json"])
        binding.update(
            decision_snapshot_id=captures["decision"].snapshot_id,
            decision_fingerprint=captures["decision"].fingerprint,
            cohort_snapshot_id=captures["cohort"].snapshot_id,
            system_decision_sha256=cli.hashlib.sha256(frozen_raw).hexdigest(),
        )
        captures["freeze"] = write_snapshot(
            store,
            source=candidate.freeze.metadata.source,
            captured_at_utc=candidate.freeze.metadata.captured_at_utc,
            payloads={
                **candidate.freeze.payloads,
                "benchmark.json": json.dumps(binding).encode(),
                "system-decision.json": frozen_raw,
            },
        )
        picked = json.loads(candidate.picks.payloads["benchmark.json"])
        picked["cohort_snapshot_id"] = captures["cohort"].snapshot_id
        captures["picks"] = write_snapshot(
            store,
            source=candidate.picks.metadata.source,
            captured_at_utc=candidate.picks.metadata.captured_at_utc,
            payloads={**candidate.picks.payloads, "benchmark.json": json.dumps(picked).encode()},
        )
        captures["outcome"] = write_snapshot(
            store,
            source=candidate.outcome.metadata.source,
            captured_at_utc=candidate.outcome.metadata.captured_at_utc,
            payloads=candidate.outcome.payloads,
        )
        rows.append(
            {
                "gameweek": gameweek,
                **{role + "_snapshot_id": value.snapshot_id for role, value in captures.items()},
            }
        )
    rows.append({"gameweek": 14, "exclusion": "missing_capture"})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"season": "2026-27", "first_gameweek": 6, "last_gameweek": 14, "weeks": rows}),
        encoding="utf-8",
    )
    # The committed declaration has LF endings; a Windows checkout may hold CRLF.
    committed = b"# Benchmark V2 pre-registration\n"
    replies = {
        ("git", "rev-parse", "HEAD"): SimpleNamespace(stdout="a" * 40),
        ("git", "status", "--porcelain"): SimpleNamespace(stdout=""),
        ("git", "show", "HEAD:docs/benchmark_v2_prereg.md"): SimpleNamespace(stdout=committed),
    }
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **_: replies[tuple(command)])
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--snapshot-root",
                str(store),
            ]
        )
        == 0
    )
    result = json.loads((record / READING_FILE).read_bytes())
    assert result["paired_gameweeks"] == 8 and result["locked_holdout_accessed"] is False
    assert result["exclusions"] == [{"gameweek": 14, "reason": "missing_capture"}]
    assert result["declared_gameweeks"] == {"first_gameweek": 6, "last_gameweek": 14}
    assert result["manifest_sha256"] == cli.hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert result["preregistration_sha256"] == cli.hashlib.sha256(committed).hexdigest()
    assert (record / CLAIM_FILE).exists()
    # The fixed root holds the claim, so the same manifest cannot be read a second time.
    monkeypatch.setattr(cli, "read_snapshot", lambda *_: pytest.fail("Second capture was opened"))
    assert cli.main(["--manifest", str(manifest), "--snapshot-root", str(store)]) == 1
