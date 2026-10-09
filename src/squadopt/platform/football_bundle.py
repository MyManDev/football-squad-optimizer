"""Validate existing football inputs and publish one immutable ready marker last.

This module never fetches, fits, exports news, generates a site, or activates runtime
configuration. A marker certifies the held inputs; activation remains a separate step.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from squadopt.application.manager_words import load_manager_words
from squadopt.contracts.injuries import require_official_injury_source
from squadopt.contracts.league import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.contracts.league_tree import single_league_tree
from squadopt.data._long_paths import addressable
from squadopt.data.atomic import document_bytes, write_bytes_once
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news_capture import read_club_news_capture
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.premier_league_injuries import OfficialInjuryReport
from squadopt.data.timestamps import as_instant
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.live import infer_season, read_inputs, read_projection_handoff
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.platform.football_minute_basis import _basis_from_snapshot, football_components_path
from squadopt.platform.official_injury_capture import REPORT_PAYLOAD, read_official_injury_capture
from squadopt.platform.projection_retention import _safe

CONTRACT_VERSION = "football_ready_bundle_v1"
_REQUIRED = frozenset({"forecast", "components", "handoff", "site_members"})
_OPTIONAL = frozenset({"rotation_table", "rotation_manifest"})
#: The one rule for a sealed rotation filename, applied when a bundle is read and, so that
#: no marker is ever written for a bundle its reader refuses, before anything is copied.
_ROTATION_FILENAME = re.compile(r"[A-Za-z0-9_-]+(?:\.manifest)?\.(?:csv|json)")
#: Names a rotation artifact may not take inside the bundle folder.
_RESERVED_FILENAMES = frozenset({"handoff.json", "site.json"})


def football_bundle_path(artifact_root: Path, snapshot_id: str) -> Path:
    return football_artifact_path(artifact_root, snapshot_id).with_suffix(".bundle.json")


class FootballBundleStage(StrEnum):
    STARTED = ".bundle.started.json"
    PREPARATION = ".bundle.preparation.json"
    PRODUCTION = ".bundle.production.json"
    FOLDER = ".bundle"


def football_bundle_stage_path(
    artifact_root: Path, snapshot_id: str, stage: FootballBundleStage
) -> Path:
    return football_artifact_path(artifact_root, snapshot_id).with_suffix(stage.value)


def football_bundle_stage_paths(artifact_root: Path, snapshot_id: str) -> tuple[Path, ...]:
    return tuple(
        football_bundle_stage_path(artifact_root, snapshot_id, stage)
        for stage in FootballBundleStage
    )


def _object(raw: bytes) -> dict[str, Any]:
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("A football bundle document must be an object.")
    return result


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source(snapshot_root: Path, capture_id: str) -> CapturedSnapshot:
    # read_snapshot validates exact bytes; reject path aliases before opening them.
    if not re.fullmatch(r"[a-z0-9][A-Za-z0-9-]{0,159}", capture_id):
        raise ValueError("Invalid bundle source capture identity.")
    _safe(Path(addressable(snapshot_root / capture_id)))
    return read_snapshot(snapshot_root, capture_id)


def _capture_record(snapshot: CapturedSnapshot) -> dict[str, str]:
    meta = snapshot.metadata
    return {
        "snapshot_id": meta.snapshot_id,
        "fingerprint": meta.fingerprint,
        "captured_at_utc": meta.captured_at_utc,
    }


@dataclass(frozen=True, slots=True)
class FootballBundle:
    marker_path: Path
    fingerprint: str
    snapshot_id: str
    season: str
    gameweek: int
    files: Mapping[str, Path]
    news_capture_id: str | None
    official_injury_capture_id: str | None
    official_injuries: OfficialInjuryReport | None
    handoff_fingerprint: str


def _validate(
    *,
    snapshot_root: Path,
    snapshot_id: str,
    files: Mapping[str, Path],
    news_capture_id: str | None,
    official_injury_capture_id: str | None,
) -> tuple[dict[str, Any], OfficialInjuryReport | None]:
    if official_injury_capture_id is not None:
        require_official_injury_source()
    extras = files.keys() - (_REQUIRED | _OPTIONAL)
    if not files.keys() >= _REQUIRED or any(
        not re.fullmatch(r"site_entry_[1-9][0-9]*", role) for role in extras
    ):
        raise ValueError("Bundle file roles are incomplete or unsupported.")
    has_rotation = files.keys() >= _OPTIONAL
    if (news_capture_id is not None) != has_rotation or bool(
        files.keys() & _OPTIONAL
    ) != has_rotation:
        raise ValueError("News requires both exact rotation artifacts, or none of the three.")
    for path in files.values():
        _safe(Path(addressable(path)))
    snapshot = _source(snapshot_root, snapshot_id)
    if snapshot.metadata.source != FPL_LIVE_SOURCE:
        raise ValueError("A ready football bundle requires an FPL decision capture.")
    inputs = read_inputs(snapshot, season=infer_season(snapshot))
    if as_instant(inputs.captured_at_utc) >= as_instant(inputs.deadline.deadline_utc):
        raise ValueError("A ready decision capture must precede its deadline.")
    forecast = read_football_forecast(files["forecast"], inputs)
    _basis_from_snapshot(
        _object(Path(addressable(files["forecast"])).read_bytes()),
        _object(Path(addressable(files["components"])).read_bytes()),
        snapshot,
        inputs,
        forecast,
    )
    handoff = read_projection_handoff(files["handoff"])
    if (
        handoff.source_snapshot_id != snapshot_id
        or handoff.season != inputs.season
        or handoff.gameweek != inputs.deadline.gameweek
        or not set(handoff.expected_points) <= set(inputs.players.player_id)
    ):
        raise ValueError("Projection handoff differs from the decision capture or roster.")
    site_files = _site_files(files["site_members"].parent)
    if {role: path for role, path in files.items() if role.startswith("site_")} != site_files:
        raise ValueError("Bundle site files differ from its declared human members.")
    generated = set()
    for role, path in site_files.items():
        document = _object(Path(addressable(path)).read_bytes())
        payload = document["payload"]
        if (
            payload.get("season") != inputs.season
            or payload.get("gameweek") != inputs.deadline.gameweek
            or (role != "site_members" and payload.get("source_snapshot_id") != snapshot_id)
        ):
            raise ValueError("Generated site identity differs from the decision capture.")
        timestamp = document.get("generated_at_utc")
        if not isinstance(timestamp, str) or as_instant(timestamp) < as_instant(
            inputs.captured_at_utc
        ):
            raise ValueError("Generated site must postdate its source capture.")
        generated.add(timestamp)
    if len(generated) != 1:
        raise ValueError("Generated site identity files are from different publications.")
    site_generated = generated.pop()
    identities: dict[str, Any] = {
        "decision": _capture_record(snapshot),
        "season": inputs.season,
        "gameweek": inputs.deadline.gameweek,
        "forecast_fingerprint": forecast.fingerprint,
        "handoff_fingerprint": handoff.fingerprint,
        "site_generated_at_utc": site_generated,
        "news": None,
        "official_injuries": None,
    }
    if news_capture_id is not None:
        news = _source(snapshot_root, news_capture_id)
        read_club_news_capture(news)
        if as_instant(news.metadata.captured_at_utc) >= as_instant(inputs.captured_at_utc):
            raise ValueError("News capture must complete before the decision capture.")
        rotation = read_rotation_evidence_artifact(
            files["rotation_table"], files["rotation_manifest"]
        )
        manifest = _object(Path(addressable(files["rotation_manifest"])).read_bytes())
        if (
            manifest.get("roster_snapshot_id") != snapshot_id
            or manifest.get("club_news_snapshot_id") != news_capture_id
            or manifest.get("club_news_captured_at_utc") != news.metadata.captured_at_utc
            or set(rotation.player_id) != set(inputs.players.player_id)
            or set(rotation.season.astype(str)) != {inputs.season}
            or set(rotation.target_gameweek) != {inputs.deadline.gameweek}
            or set(rotation.captured_at_utc.astype(str)) != {inputs.captured_at_utc}
        ):
            raise ValueError("Rotation evidence differs from the exact decision/news pair.")
        if files["rotation_table"].with_suffix(".manifest.json") != files["rotation_manifest"]:
            raise ValueError("Rotation table and manifest must be exact siblings.")
        load_manager_words(
            files["rotation_table"],
            club_news_source=snapshot_root / news_capture_id,
            snapshot_root=snapshot_root,
        )
        identities["news"] = _capture_record(news)
    official_report = None
    if official_injury_capture_id is not None:
        official = _source(snapshot_root, official_injury_capture_id)
        official_report = read_official_injury_capture(official)
        original = _object(official.payloads[REPORT_PAYLOAD])
        roster_id = str(original.get("roster_snapshot_id", ""))
        roster = _source(snapshot_root, roster_id)
        if (
            original.get("roster_fingerprint") != roster.metadata.fingerprint
            or official.payloads[BOOTSTRAP_PAYLOAD] != roster.payloads[BOOTSTRAP_PAYLOAD]
            or official_report.season != inputs.season
            or as_instant(official_report.observed_at) > as_instant(inputs.captured_at_utc)
        ):
            raise ValueError(
                "Official injury capture differs from its recorded roster or decision time."
            )
        # A source reading may precede the fresh decision. Rebuild against that
        # decision's roster, refusing identity drift rather than inventing a join.
        current = _object(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        previous = _object(roster.payloads[BOOTSTRAP_PAYLOAD])

        def roster_identity(doc: dict[str, Any]) -> tuple[object, object]:
            clubs = sorted((row["id"], row["name"]) for row in doc["teams"])
            players = sorted(
                (
                    row["code"],
                    row["team"],
                    row.get("web_name"),
                    row.get("first_name"),
                    row.get("second_name"),
                )
                for row in doc["elements"]
            )
            return clubs, players

        if roster_identity(current) != roster_identity(previous):
            raise ValueError("Official injury roster identities differ from the decision roster.")
        identities["official_injuries"] = _capture_record(official)
    return identities, official_report


def _site_files(tree: Path) -> dict[str, Path]:
    """Read the existing member/entry envelopes of one league's tree, without importing
    runtime services."""
    member_path = tree / "members.json"
    _safe(Path(addressable(member_path)))
    document = _object(Path(addressable(member_path)).read_bytes())
    payload = document.get("payload")
    if document.get("contract_version") != LEAGUE_VIEW_CONTRACT_VERSION or not isinstance(
        payload, dict
    ):
        raise ValueError("Invalid site member envelope.")
    for name in ("league_id", "gameweek"):
        if type(payload.get(name)) is not int or payload[name] < 1:
            raise ValueError("Invalid site member publication identity.")
    for name in ("league_name", "season"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise ValueError("Missing site member publication identity.")
    members = payload.get("members")
    if not isinstance(members, list):
        raise ValueError("Missing site member rows.")
    result = {"site_members": member_path}
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("Invalid site member row.")
        kind, identifier = member.get("member_kind"), member.get("entry_id")
        if kind == "system" and (
            identifier is None or (type(identifier) is int and identifier == 0)
        ):
            continue
        if kind != "human" or type(identifier) is not int or identifier < 1:
            raise ValueError("Invalid site member identity.")
        role = f"site_entry_{identifier}"
        if role in result:
            raise ValueError("Duplicate site member identity.")
        path = tree / "entries" / f"{identifier}.json"
        _safe(Path(addressable(path)))
        entry = _object(Path(addressable(path)).read_bytes())
        row = entry.get("payload")
        if (
            entry.get("contract_version") != LEAGUE_VIEW_CONTRACT_VERSION
            or not isinstance(row, dict)
            or row.get("league_id") != payload["league_id"]
            or not isinstance(row.get("entry"), dict)
            or row["entry"].get("entry_id") != identifier
            or row["entry"].get("member_kind") != "human"
        ):
            raise ValueError("Site entry differs from its declared member.")
        result[role] = path
    if len(result) == 1:
        raise ValueError("A ready site requires at least one human member capture.")
    return result


#: Where a sealed site's member documents sit inside the bundle: the league's tree as the
#: site publishes it, the legacy ``league`` or ``leagues/<league id>``.
_SITE_MEMBERS = re.compile(r"site/(league|leagues/[1-9][0-9]*)/members\.json")


def _site_folder(prefix: str, records: dict[str, object]) -> str:
    """The sealed tree's folder, read from the members record; the legacy one when it
    names no tree, so a record of any other shape is refused by the role check."""

    members = records.get("site_members")
    path = members.get("path") if isinstance(members, dict) else None
    if isinstance(path, str) and path.startswith(prefix):
        match = _SITE_MEMBERS.fullmatch(path.removeprefix(prefix))
        if match is not None:
            return f"site/{match.group(1)}/"
    return "site/league/"


def _relative_files(marker: Path, snapshot_id: str, records: object) -> dict[str, Path]:
    if not isinstance(records, dict):
        raise ValueError("Bundle file records must be an object.")
    result = {}
    prefix = snapshot_id + ".bundle/"
    site = prefix + _site_folder(prefix, records)
    for role, entry in records.items():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("Bundle file entries require a path and digest.")
        relative = entry["path"]
        expected = {
            "forecast": snapshot_id + ".json",
            "components": snapshot_id + ".components.json",
            "handoff": prefix + "handoff.json",
            "site_members": site + "members.json",
        }.get(role)
        if re.fullmatch(r"site_entry_[1-9][0-9]*", role):
            expected = site + "entries/" + role.removeprefix("site_entry_") + ".json"
        if expected is None:
            if (
                role not in _OPTIONAL
                or not isinstance(relative, str)
                or not relative.startswith(prefix)
            ):
                raise ValueError("Unexpected bundle role or relative path.")
            name = relative.removeprefix(prefix)
            if name in _RESERVED_FILENAMES or not _ROTATION_FILENAME.fullmatch(name):
                raise ValueError("Invalid sealed rotation filename.")
        elif relative != expected:
            raise ValueError("Bundle role has an unexpected filename.")
        path = marker.parent / relative
        _safe(Path(addressable(path)))
        if _digest(Path(addressable(path)).read_bytes()) != entry["sha256"]:
            raise ValueError("Bundle file digest mismatch.")
        result[role] = path
    return result


def read_football_bundle(
    *, artifact_root: Path, snapshot_root: Path, snapshot_id: str
) -> FootballBundle:
    """Read only this exact ready marker and revalidate every declared input."""
    marker = football_bundle_path(artifact_root, snapshot_id)
    _safe(Path(addressable(marker)))
    raw = Path(addressable(marker)).read_bytes()
    record = _object(raw)
    if (
        record.get("contract_version") != CONTRACT_VERSION
        or record.get("snapshot_id") != snapshot_id
    ):
        raise ValueError("Unsupported or mismatched football ready marker.")
    if record.get("official_injuries") is not None:
        require_official_injury_source()
    files = _relative_files(marker, snapshot_id, record.get("files"))
    news = record.get("news")
    official = record.get("official_injuries")
    for value in (news, official):
        if value is not None and (
            not isinstance(value, dict) or not isinstance(value.get("snapshot_id"), str)
        ):
            raise ValueError("Invalid bundle source identity.")
    news_id = news["snapshot_id"] if news is not None else None
    official_id = official["snapshot_id"] if official is not None else None
    identity, report = _validate(
        snapshot_root=snapshot_root,
        snapshot_id=snapshot_id,
        files=files,
        news_capture_id=news_id,
        official_injury_capture_id=official_id,
    )
    expected = {
        "contract_version": CONTRACT_VERSION,
        "snapshot_id": snapshot_id,
        "files": record["files"],
        **identity,
    }
    if record != expected:
        raise ValueError("Football ready marker provenance differs from its held inputs.")
    return FootballBundle(
        marker,
        _digest(raw),
        snapshot_id,
        identity["season"],
        identity["gameweek"],
        MappingProxyType(files),
        news_id,
        official_id,
        report,
        identity["handoff_fingerprint"],
    )


def seal_football_bundle(
    *,
    artifact_root: Path,
    snapshot_root: Path,
    snapshot_id: str,
    handoff_path: Path,
    site_data_root: Path,
    news_capture_id: str | None = None,
    rotation_table_path: Path | None = None,
    official_injury_capture_id: str | None = None,
    league_id: int | None = None,
) -> FootballBundle:
    """Seal existing inputs without overwriting either artifacts or an earlier marker.

    The site files sealed are one league's tree: ``league_id``'s, or the only one the site
    publishes when it is not named.

    Copies may survive an interruption; only the final marker makes them ready.
    Repeating the identical inputs completes that interruption or returns a replay.
    """
    if official_injury_capture_id is not None:
        require_official_injury_source()
    marker = football_bundle_path(artifact_root, snapshot_id)
    _safe(Path(addressable(marker)))
    existing = (
        Path(addressable(marker)).read_bytes() if Path(addressable(marker)).exists() else None
    )
    if existing is not None:
        read_football_bundle(
            artifact_root=artifact_root, snapshot_root=snapshot_root, snapshot_id=snapshot_id
        )
    site_tree = single_league_tree(site_data_root, league_id)
    # A failed preparation has no ready marker or copied folder yet. Record the
    # attempt before either, so older v1 readers cannot serve its loose artifacts.
    started = football_bundle_stage_path(artifact_root, snapshot_id, FootballBundleStage.STARTED)
    _safe(Path(addressable(started)))
    write_bytes_once(
        document_bytes(
            {"contract_version": "football_bundle_attempt_v1", "snapshot_id": snapshot_id}
        ),
        started,
    )
    files = {
        "forecast": football_artifact_path(artifact_root, snapshot_id),
        "components": football_components_path(artifact_root, snapshot_id),
        "handoff": handoff_path,
        **_site_files(site_tree),
    }
    if rotation_table_path is not None:
        files.update(
            rotation_table=rotation_table_path,
            rotation_manifest=rotation_table_path.with_suffix(".manifest.json"),
        )
    # The reader's rule, before validation, a copy or a marker: a name the reader would
    # refuse must not become a marker that refuses every later read and reseal.
    for role in _OPTIONAL & files.keys():
        if files[role].name in _RESERVED_FILENAMES:
            raise ValueError("Reserved rotation artifact filename.")
        if not _ROTATION_FILENAME.fullmatch(files[role].name):
            raise ValueError("Invalid sealed rotation filename.")
    identity, _ = _validate(
        snapshot_root=snapshot_root,
        snapshot_id=snapshot_id,
        files=files,
        news_capture_id=news_capture_id,
        official_injury_capture_id=official_injury_capture_id,
    )
    folder = football_bundle_stage_path(artifact_root, snapshot_id, FootballBundleStage.FOLDER)
    destinations = dict(files)
    destinations["handoff"] = folder / "handoff.json"
    for role, path in files.items():
        if role.startswith("site_"):
            destinations[role] = folder / "site" / path.relative_to(site_data_root)
    for role in _OPTIONAL & files.keys():
        destinations[role] = folder / files[role].name
    payloads = {role: Path(addressable(path)).read_bytes() for role, path in files.items()}
    record = {
        "contract_version": CONTRACT_VERSION,
        "snapshot_id": snapshot_id,
        **identity,
        "files": {
            role: {
                "path": destinations[role].relative_to(marker.parent).as_posix(),
                "sha256": _digest(raw),
            }
            for role, raw in payloads.items()
        },
    }
    raw_marker = document_bytes(record)
    if existing is not None and existing != raw_marker:
        raise ValueError("A different ready bundle already exists for this capture.")
    # Preflight every immutable destination before writing any copy.
    for role, path in destinations.items():
        _safe(Path(addressable(path)))
        if (
            Path(addressable(path)).exists()
            and Path(addressable(path)).read_bytes() != payloads[role]
        ):
            raise ValueError("A different immutable bundle artifact already exists.")
    for role, path in destinations.items():
        if path != files[role]:
            write_bytes_once(payloads[role], path)
    # Re-read the copied bytes through production validators before the ready marker.
    final_identity, _ = _validate(
        snapshot_root=snapshot_root,
        snapshot_id=snapshot_id,
        files=destinations,
        news_capture_id=news_capture_id,
        official_injury_capture_id=official_injury_capture_id,
    )
    if final_identity != identity:
        raise ValueError("A bundle source identity changed while it was being sealed.")
    if any(
        Path(addressable(path)).read_bytes() != payloads[role]
        for role, path in destinations.items()
    ):
        raise ValueError("A bundle input changed while it was being sealed.")
    write_bytes_once(raw_marker, marker)
    return read_football_bundle(
        artifact_root=artifact_root, snapshot_root=snapshot_root, snapshot_id=snapshot_id
    )
