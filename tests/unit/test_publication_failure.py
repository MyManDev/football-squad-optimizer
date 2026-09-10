"""A failed replacement must leave the last complete public document readable."""

import json
import os
from pathlib import Path

import pytest
from tests.unit.test_scoreboard_recovery import recovery_world

from squadopt.application.scoreboard import ScoreboardPublicationRequest, publish_scoreboard
from squadopt.data.snapshots import write_snapshot
from squadopt.platform import capture_measurement, recover_scoreboard


@pytest.mark.parametrize("publisher", ["scoreboard", "recovery", "measurement"])
def test_failed_publication_preserves_previous_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publisher: str
) -> None:
    output = (
        tmp_path / "site/data/league/scoreboard.json"
        if publisher == "scoreboard"
        else tmp_path / "published.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = b'{"previous":"complete"}\n'
    output.write_bytes(previous)

    real_replace = os.replace

    def failed_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == output:
            raise OSError("injected publication failure")
        real_replace(source, target)

    monkeypatch.setattr("squadopt.live.ledger.os.replace", failed_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        if publisher == "scoreboard":
            source = recovery_world(tmp_path)
            snapshots = tmp_path / "snapshots"
            stored = write_snapshot(
                snapshots,
                source="fpl-live",
                captured_at_utc=source.metadata.captured_at_utc,
                payloads=source.payloads,
            )
            registry = tmp_path / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "contract_version": "entry_registry_v1",
                        "entries": [{"entry_id": 7, "label": "Member"}],
                    }
                )
            )
            publish_scoreboard(
                ScoreboardPublicationRequest(
                    snapshots,
                    stored.snapshot_id,
                    registry,
                    tmp_path / "ledger",
                    tmp_path / "site",
                    352490,
                    recovery_publication_root=tmp_path,
                    advice_record_root=tmp_path / "records",
                )
            )
        elif publisher == "recovery":
            monkeypatch.setattr(recover_scoreboard, "collect_outcomes", lambda *a, **k: None)
            monkeypatch.setattr(
                recover_scoreboard, "recovery_scoreboard", lambda **k: {"new": True}
            )
            recover_scoreboard.main(
                [
                    "--publication-root",
                    str(tmp_path),
                    "--advice-root",
                    str(tmp_path / "advice"),
                    "--capture-root",
                    str(tmp_path / "captures"),
                    "--out",
                    str(output),
                ]
            )
        else:
            monkeypatch.setattr(capture_measurement, "list_snapshot_ids", lambda *a, **k: ())
            capture_measurement.main(
                [
                    "--snapshot-root",
                    str(tmp_path),
                    "--season",
                    "2026-27",
                    "--out",
                    str(output),
                ]
            )
    assert output.read_bytes() == previous
    assert list(output.parent.iterdir()) == [output]
