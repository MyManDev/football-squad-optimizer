"""Capture history survives same-week publication and an interrupted alias replacement."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from squadopt.live import InSeasonProjection, read_projection_handoff, write_projection_handoff
from squadopt.platform import projection_retention as retention
from squadopt.platform._long_paths import addressable


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


def test_retention_root_past_windows_max_path_still_retains_create_once(tmp_path: Path) -> None:
    """A "<sha256>.json" target over MAX_PATH must still be retained exactly once.

    Windows caps path-based calls at 260 characters (measured on the owner's machine).
    The 69-character retained name pushes the target past the cap while the 17-character
    ".retain-XXXXXXXX" temporary beside it stays under - so the temporary is created and
    only the link into place fails. This test pins that asymmetry.
    """

    capture = "fpl-live-test-a"
    root = tmp_path.absolute()
    overhead = len(f"\\by-capture\\{capture}\\") + len(f"{'0' * 64}.json")
    while len(str(root)) + overhead <= 274:
        root = root / "deeper"
    root.mkdir(parents=True, exist_ok=True)
    alias = root / "2026-27-gw04.json"
    first = _projection(capture)

    assert retention.publish_retained_handoff(alias, first) == alias
    raw = alias.read_bytes()
    retained = retention.retained_handoff_path(root, capture, hashlib.sha256(raw).hexdigest())
    assert len(str(retained)) > 260, "target must exceed MAX_PATH for this to be a regression test"
    assert len(str(retained.parent)) + len("\\.retain-XXXXXXXX") < 260, (
        "the temporary must stay under MAX_PATH, or the failure is not the one being fixed"
    )
    assert len(str(alias)) < 260
    assert Path(addressable(retained)).read_bytes() == raw

    # Retaining identical bytes again is a no-op that keeps addressing the same target.
    assert retention.publish_retained_handoff(alias, first) == alias
    assert alias.read_bytes() == raw
    assert len(list((root / "by-capture" / capture).iterdir())) == 1

    # Differing bytes under an already-taken target are still refused, not overwritten.
    Path(addressable(retained)).write_bytes(b"corrupt")
    with pytest.raises(retention.ProjectionRetentionError, match="corrupt"):
        retention.publish_retained_handoff(alias, _projection("fpl-live-test-b"))
    assert alias.read_bytes() == raw


def test_capture_path_cannot_escape_retention_root(tmp_path: Path) -> None:
    with pytest.raises(retention.ProjectionRetentionError, match="Invalid capture"):
        retention.publish_retained_handoff(tmp_path / "alias.json", _projection("../escape"))
    assert not (tmp_path / "alias.json").exists()
