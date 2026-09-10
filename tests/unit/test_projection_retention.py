"""Capture history survives same-week publication and an interrupted alias replacement."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from squadopt.live import InSeasonProjection, read_projection_handoff, write_projection_handoff
from squadopt.platform import projection_retention as retention


def _projection(capture: str = "fpl-live-test-a") -> InSeasonProjection:
    return InSeasonProjection(
        season="2026-27",
        gameweek=4,
        source_snapshot_id=capture,
        model_name="test",
        model_version="test-v1",
        feature_contract_version="test-v1",
        expected_points={1: 4.5},
    )


def test_same_week_publish_retains_legacy_and_new_capture_without_schema_change(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "2026-27-gw04.json"
    old, new = _projection(), _projection("fpl-live-test-b")
    write_projection_handoff(alias, old)  # Existing pre-retention file must also survive.
    old_bytes = alias.read_bytes()
    assert retention.publish_retained_handoff(alias, new) == alias
    new_bytes = alias.read_bytes()
    for projection, raw in ((old, old_bytes), (new, new_bytes)):
        retained = retention.retained_handoff_path(
            tmp_path, projection.source_snapshot_id, hashlib.sha256(raw).hexdigest()
        )
        assert retained.read_bytes() == raw
        assert read_projection_handoff(retained).fingerprint == projection.fingerprint
    assert read_projection_handoff(alias).source_snapshot_id == new.source_snapshot_id
    assert set(json.loads(new_bytes)) == set(json.loads(old_bytes))


def test_diagnostic_only_change_keeps_both_exact_byte_versions(tmp_path: Path) -> None:
    alias = tmp_path / "2026-27-gw04.json"
    first = _projection()
    second = replace(first, diagnostics={"reason": "changed diagnostic"})
    assert first.fingerprint == second.fingerprint
    retention.publish_retained_handoff(alias, first)
    retention.publish_retained_handoff(alias, second)
    retention.publish_retained_handoff(alias, second)
    retained = list((tmp_path / "by-capture" / first.source_snapshot_id).glob("*.json"))
    assert len(retained) == 2
    assert {read_projection_handoff(file).fingerprint for file in retained} == {first.fingerprint}


def test_interrupted_alias_replace_preserves_old_alias_and_both_retained_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = tmp_path / "2026-27-gw04.json"
    old, new = _projection(), _projection("fpl-live-test-b")
    retention.publish_retained_handoff(alias, old)
    before = alias.read_bytes()

    def fail(*args: object) -> None:
        raise OSError("injected replacement failure")

    monkeypatch.setattr(retention.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failure"):
        retention.publish_retained_handoff(alias, new)
    assert alias.read_bytes() == before
    captures = {
        read_projection_handoff(file).source_snapshot_id
        for file in (tmp_path / "by-capture").rglob("*.json")
    }
    assert captures == {old.source_snapshot_id, new.source_snapshot_id}
    assert not list(tmp_path.glob(".handoff-*"))


def test_corrupt_existing_archive_is_refused_before_replacing_alias(tmp_path: Path) -> None:
    alias = tmp_path / "2026-27-gw04.json"
    old = _projection()
    retention.publish_retained_handoff(alias, old)
    before = alias.read_bytes()
    retained = next((tmp_path / "by-capture").rglob("*.json"))
    retained.write_bytes(b"corrupt")
    with pytest.raises(retention.ProjectionRetentionError, match="corrupt"):
        retention.publish_retained_handoff(alias, _projection("fpl-live-test-b"))
    assert alias.read_bytes() == before


def test_capture_path_cannot_escape_retention_root(tmp_path: Path) -> None:
    with pytest.raises(retention.ProjectionRetentionError, match="Invalid capture"):
        retention.publish_retained_handoff(tmp_path / "alias.json", _projection("../escape"))
    assert not (tmp_path / "alias.json").exists()
