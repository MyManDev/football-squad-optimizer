"""The VM release package: configuration rendering, the drift bound and a pack/stage round trip.

Nothing here reaches the VM, Docker or the network. The round trip packs a small synthetic
week from a temporary Git repository and unpacks it into a temporary releases directory.
"""

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from scripts.release import vm_football_release as release

CAPTURE = "fpl-live-20261022T054506Z-fdb7b49822e7"
NEWS = "club-news-20261021T161737Z-ca7354f945c2"


def test_render_env_replaces_named_keys_and_keeps_everything_else() -> None:
    lines = ["# comment", "SQUADOPT_SITE_PATH=/old/site", "SQUADOPT_API_PORT=8000", "", "OTHER=1"]
    rendered = release.render_env(lines, {"SQUADOPT_SITE_PATH": "/new/site", "NEW_KEY": "x"})
    assert rendered.splitlines() == [
        "# comment",
        "SQUADOPT_SITE_PATH=/new/site",
        "SQUADOPT_API_PORT=8000",
        "",
        "OTHER=1",
        "NEW_KEY=x",
    ]


def test_render_env_leaves_a_commented_key_alone() -> None:
    rendered = release.render_env(["# SQUADOPT_SITE_PATH=/x"], {"SQUADOPT_SITE_PATH": "/y"})
    assert rendered.splitlines() == ["# SQUADOPT_SITE_PATH=/x", "SQUADOPT_SITE_PATH=/y"]


def test_override_reads_a_news_capture_inside_the_snapshot_root() -> None:
    text = release.render_override(
        PurePosixPath("/r/payload/artifact_root"), (f"/mnt/snapshots/{NEWS}", None)
    )
    assert text.count("source: /r/payload/artifact_root") == 2
    assert text.count(f"SQUADOPT_BACKEND_CLUB_NEWS_SOURCE: /mnt/snapshots/{NEWS}") == 2
    assert "club_news_v1.fixture.json" not in text


def test_override_mounts_a_retained_fixture_for_both_services() -> None:
    text = release.render_override(
        PurePosixPath("/r/payload/artifact_root"),
        ("/mnt/club_news_v1.fixture.json", PurePosixPath("/r/payload/club_news_fixture.json")),
    )
    assert text.count("source: /r/payload/club_news_fixture.json") == 2
    assert text.count("target: /mnt/club_news_v1.fixture.json") == 2


def _documents(value: float, source: str = "a" * 64) -> tuple[dict, dict]:
    metadata = {"model_artifacts": [{"sha256": source}], "basis_sha256": "b" * 64}
    forecast = {
        "rows": [{"expected_points": value, "player_code": 1}],
        "composite_metadata": metadata,
        "fingerprint": hashlib.sha256(str(value).encode()).hexdigest(),
    }
    components = {"recipe": {"version": "r"}, "composite_metadata": metadata, "rows": []}
    return forecast, components


def test_drift_bound_accepts_last_bit_differences_in_derived_values() -> None:
    drift = release._bounded_difference(_documents(0.1 + 0.2), _documents(0.3))
    assert drift["counts"] == {"float": 1, "hash": 1}
    assert 0 < drift["maximum_absolute_float_difference"] <= release.MAX_ABSOLUTE_DRIFT


def test_drift_bound_refuses_a_large_difference() -> None:
    with pytest.raises(release.ReleaseError, match="too large"):
        release._bounded_difference(_documents(1.0), _documents(1.001))


def test_drift_bound_refuses_a_changed_source_identity() -> None:
    with pytest.raises(release.ReleaseError, match="Source identity drift"):
        release._bounded_difference(_documents(1.0, "a" * 64), _documents(1.0, "c" * 64))


def test_drift_bound_refuses_structural_drift() -> None:
    held = _documents(1.0)
    rebuilt = _documents(1.0)
    rebuilt[0]["rows"].append({"expected_points": 2.0, "player_code": 2})
    with pytest.raises(release.ReleaseError, match="Structural length drift"):
        release._bounded_difference(held, rebuilt)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _week(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    (repo / "data" / "sample").mkdir(parents=True)
    (repo / "data" / "sample" / "club_news_v1.fixture.json").write_text("{}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c")
    _git(repo, "tag", "site-2026-27-gw08-decision")
    snapshots = tmp_path / "snapshots"
    for snapshot_id in (CAPTURE, "fpl-top100-x", "fpl-elite-picks-x", NEWS):
        (snapshots / snapshot_id / "payloads").mkdir(parents=True)
        (snapshots / snapshot_id / "metadata.json").write_text(json.dumps({"id": snapshot_id}))
    tables = tmp_path / "tables"
    tables.mkdir()
    top100 = tables / "player_evidence_v1_2026-27_gw08_top100_x.csv"
    top100.write_text("player,count\n1,2\n")
    (tables / "top100.manifest.json").write_text(
        json.dumps(
            {
                "table_file": top100.name,
                "table_sha256": hashlib.sha256(top100.read_bytes()).hexdigest(),
                "target_gameweek": 8,
                "source_snapshot_ids": ["fpl-elite-picks-x", "fpl-top100-x"],
            }
        )
    )
    rotation = tables / "rotation_evidence_v4_2026-27_gw08_x.csv"
    rotation.write_text("code,claim\n")
    (tables / "rotation.manifest.json").write_text(
        json.dumps(
            {
                "table_file": rotation.name,
                "table_sha256": hashlib.sha256(rotation.read_bytes()).hexdigest(),
                "target_gameweek": "8",
                "club_news_snapshot_id": NEWS,
                "roster_snapshot_id": CAPTURE,
            }
        )
    )
    handoff = tmp_path / "2026-27-gw08.json"
    handoff.write_text("{}")
    site = tmp_path / "site"
    (site / "leagues").mkdir(parents=True)
    (site / "leagues.json").write_text("{}")
    return {
        "repo": repo,
        "snapshots": snapshots,
        "tables": tables,
        "handoff": handoff,
        "site": site,
    }


def _pack(week: dict[str, Path], out: Path, *extra: str) -> int:
    return release.main(
        [
            "pack",
            "--repo",
            str(week["repo"]),
            "--gameweek",
            "8",
            "--capture",
            CAPTURE,
            "--tag",
            "site-2026-27-gw08-decision",
            "--snapshot-root",
            str(week["snapshots"]),
            "--handoff",
            str(week["handoff"]),
            "--top100-manifest",
            str(week["tables"] / "top100.manifest.json"),
            "--site-data",
            str(week["site"]),
            "--name",
            "gw08-test",
            "--out",
            str(out),
            *extra,
        ]
    )


def test_pack_then_stage_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    week = _week(tmp_path)
    out = tmp_path / "out"
    assert (
        _pack(
            week,
            out,
            "--news-capture",
            NEWS,
            "--rotation-manifest",
            str(week["tables"] / "rotation.manifest.json"),
        )
        == 0
    )
    package = json.loads((out / "gw08-test" / "package.json").read_text())
    assert package["captures"] == sorted([CAPTURE, "fpl-top100-x", "fpl-elite-picks-x", NEWS])
    assert package["rotation_table"] == "rotation_evidence_v4_2026-27_gw08_x.csv"
    assert package["football"] is False
    assert not (out / "gw08-test" / "payload" / "club_news_fixture.json").exists()

    releases = tmp_path / "releases"
    monkeypatch.setattr(release, "RELEASES", releases)
    tarball = out / "gw08-test.tar.gz"
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    assert release.main(["stage", "--tarball", str(tarball), "--sha256", digest]) == 0
    staged, manifest = release._release("gw08-test")
    release._verify(staged, manifest)
    assert not tarball.exists()

    (staged / "payload" / "handoff_root" / "2026-27-gw08.json").write_text('{"x": 1}')
    with pytest.raises(release.ReleaseError, match="differs from the manifest"):
        release._verify(staged, manifest)


def test_stage_refuses_a_package_that_changed_in_transit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    week = _week(tmp_path)
    assert _pack(week, tmp_path / "out") == 0
    monkeypatch.setattr(release, "RELEASES", tmp_path / "releases")
    code = release.main(
        ["stage", "--tarball", str(tmp_path / "out" / "gw08-test.tar.gz"), "--sha256", "0" * 64]
    )
    assert code == 2
    assert not (tmp_path / "releases").exists()


def test_pack_without_news_carries_the_tags_fixture(tmp_path: Path) -> None:
    week = _week(tmp_path)
    assert _pack(week, tmp_path / "out") == 0
    fixture = tmp_path / "out" / "gw08-test" / "payload" / "club_news_fixture.json"
    assert fixture.read_text() == "{}\n"


def test_pack_refuses_a_rotation_table_from_another_news_capture(tmp_path: Path) -> None:
    week = _week(tmp_path)
    code = _pack(
        week,
        tmp_path / "out",
        "--news-capture",
        "club-news-other",
        "--rotation-manifest",
        str(week["tables"] / "rotation.manifest.json"),
    )
    assert code == 2
