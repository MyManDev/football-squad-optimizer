"""The command refuses early, repeated and holdout readings before capture access."""

import json
from types import SimpleNamespace

import pytest
from scripts import read_benchmark_v2_live as cli
from tests.unit.test_benchmark_v2_live import week

from squadopt.data.snapshots import write_snapshot
from squadopt.experiments.benchmark_v2_live import CLAIM_FILE


@pytest.mark.parametrize("refusal", ["early", "repeat", "holdout", "gap", "undeclared"])
def test_command_refusal_opens_no_capture(tmp_path, monkeypatch, refusal):
    manifest = tmp_path / "private-manifest.json"
    record = tmp_path / "record"
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
        record.mkdir()
        (record / CLAIM_FILE).write_bytes(b"claimed")
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
                "--record-root",
                str(record),
            ]
        )
        == 1
    )


def test_command_reads_eight_real_format_synthetic_capture_ids(tmp_path, monkeypatch):
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
    replies = iter([SimpleNamespace(stdout="a" * 40), SimpleNamespace(stdout="")])
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: next(replies))
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--snapshot-root",
                str(store),
                "--record-root",
                str(tmp_path / "record"),
            ]
        )
        == 0
    )
    record = json.loads((tmp_path / "record" / cli.READING_FILE).read_bytes())
    assert record["paired_gameweeks"] == 8 and record["locked_holdout_accessed"] is False
    assert record["exclusions"] == [{"gameweek": 14, "reason": "missing_capture"}]
    assert record["declared_gameweeks"] == {"first_gameweek": 6, "last_gameweek": 14}
    assert record["manifest_sha256"] == cli.hashlib.sha256(manifest.read_bytes()).hexdigest()
