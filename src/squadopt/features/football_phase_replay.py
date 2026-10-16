"""Read historical duty facts from exact public-revision CSV bytes.

Public recording and present retrieval remain separate clocks. This reader does
not create a captured live snapshot or infer source permission from a Git hash.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re

from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.features.football_phase_inputs import (
    PROTECTED_SEASON,
    TAKER_FIELDS,
    PhaseDutyCapture,
    PhaseDutyPlayer,
    PhaseReplay,
    validate_phase_season,
)

_VERSION = "football_phase_public_revision_replay_v1"
_INTEGER = re.compile(r"[1-9][0-9]*(?:\.0+)?\Z")
MAX_REPLAY_CSV_BYTES = 20 * 1024 * 1024


def _positive_integer(value: str, label: str) -> int:
    text = value.strip()
    if len(text) > 64 or not _INTEGER.fullmatch(text):
        raise ValueError(f"{label} must be a positive integral CSV value.")
    result = int(text.split(".", 1)[0])
    if result > 2**63 - 1:
        raise ValueError(f"{label} exceeds persistent integer support.")
    return result


def _table(payload: bytes, required: set[str], label: str) -> list[dict[str, str]]:
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must be valid UTF-8 CSV.") from error
    if "\x00" in decoded:
        raise ValueError(f"{label} must not contain NUL characters.")
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        columns = next(reader, None)
        if (
            not columns
            or any(not column.strip() for column in columns)
            or len(set(columns)) != len(columns)
            or not required <= set(columns)
        ):
            raise ValueError(f"{label} lacks unique named required CSV columns.")
        rows = []
        for row in reader:
            if len(row) != len(columns):
                raise ValueError(f"{label} CSV row width differs from its header.")
            rows.append(dict(zip(columns, row, strict=True)))
    except csv.Error as error:
        raise ValueError(f"{label} is malformed CSV.") from error
    if not rows:
        raise ValueError(f"{label} requires a nonempty table.")
    return rows


def _replay_headers(
    replay: PhaseReplay, *, decision_at: str, valid_until: str
) -> tuple[dict[str, str], str, str]:
    if not isinstance(replay, PhaseReplay) or replay.version != _VERSION:
        raise ValueError("A supported public-revision phase replay is required.")
    if not isinstance(replay.revision, str) or not re.fullmatch(r"[a-f0-9]{40}", replay.revision):
        raise ValueError("Phase replay requires its full immutable Git revision.")
    if type(replay.source_hashes) is not tuple or not replay.source_hashes:
        raise ValueError("Phase replay requires immutable named source hashes.")
    hashes: dict[str, str] = {}
    for pair in replay.source_hashes:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0].strip()
            or pair[0] in hashes
            or not isinstance(pair[1], str)
            or not re.fullmatch(r"[a-f0-9]{64}", pair[1])
        ):
            raise ValueError("Phase replay source hashes must be unique named SHA256 values.")
        hashes[pair[0]] = pair[1]
    if not {"players_raw.csv", "teams.csv"} <= hashes.keys():
        raise ValueError("Phase replay must bind both original roster and club CSV sources.")
    try:
        times = {
            name: normalize_utc_timestamp(value, label=name)
            for name, value in (
                ("recorded_at", replay.recorded_at),
                ("retrieved_at", replay.retrieved_at),
                ("generated_at", replay.generated_at),
                ("feature_cutoff", replay.feature_cutoff),
                ("decision_at", decision_at),
                ("valid_until", valid_until),
            )
        }
    except DataError as error:
        raise ValueError("Phase replay duty clocks must be explicit UTC timestamps.") from error
    recorded, decision, retrieved, generated, feature, expiry = (
        as_instant(times[name])
        for name in (
            "recorded_at",
            "decision_at",
            "retrieved_at",
            "generated_at",
            "feature_cutoff",
            "valid_until",
        )
    )
    if not recorded <= feature <= decision <= expiry < retrieved <= generated:
        raise ValueError("Phase replay public recording, retrieval and decision clocks disagree.")
    return hashes, times["retrieved_at"], times["valid_until"]


def read_replayed_phase_duties(
    players_raw: bytes,
    teams_raw: bytes,
    *,
    season: str,
    decision_at: str,
    valid_until: str,
    replay: PhaseReplay,
    model_use_approved: bool,
    model_use_evidence_ref: str,
    allow_released_2025_26: bool = False,
) -> PhaseDutyCapture:
    """Preserve original ranks, exact source bytes and the actual retrieval time.

    Blank and literal ``None`` are the CSV source's missing-rank encodings. Integer
    decimal forms such as ``1.0`` retain exact integer meaning without float casts.
    Other missing-value spellings, zero and fractional ranks are refused.
    """
    validate_phase_season(season)
    if type(allow_released_2025_26) is not bool:
        raise ValueError("The released season selection must be an explicit Boolean.")
    if season == PROTECTED_SEASON and not allow_released_2025_26:
        raise ValueError("The declared phase source season is protected or unselected.")
    if model_use_approved is not True:
        raise ValueError("Replayed duties require explicit admitted model-use evidence.")
    if (
        not isinstance(model_use_evidence_ref, str)
        or not model_use_evidence_ref.strip()
        or len(model_use_evidence_ref) > 2048
    ):
        raise ValueError("Replayed duties require a bounded nonempty model-use evidence reference.")
    hashes, retrieved, expiry = _replay_headers(
        replay, decision_at=decision_at, valid_until=valid_until
    )
    for name, payload in (("players_raw.csv", players_raw), ("teams.csv", teams_raw)):
        if type(payload) is not bytes or len(payload) > MAX_REPLAY_CSV_BYTES:
            raise ValueError("Replayed duty CSV requires immutable bytes within the 20 MiB limit.")
        if hashlib.sha256(payload).hexdigest() != hashes[name]:
            raise ValueError("Replayed duty CSV bytes differ from their original source hashes.")
    clubs: dict[int, int] = {}
    club_codes: set[int] = set()
    for row in _table(teams_raw, {"id", "code"}, "teams"):
        team_id = _positive_integer(row["id"], "team id")
        code = _positive_integer(row["code"], "club code")
        if team_id in clubs or code in club_codes:
            raise ValueError("Replayed duties have ambiguous club identities.")
        clubs[team_id] = code
        club_codes.add(code)
    players = []
    identities: set[int] = set()
    codes: set[int] = set()
    for row in _table(players_raw, {"id", "code", "team", *TAKER_FIELDS}, "players"):
        identity = _positive_integer(row["id"], "player id")
        code = _positive_integer(row["code"], "player code")
        team_id = _positive_integer(row["team"], "player team id")
        if identity in identities or code in codes or team_id not in clubs:
            raise ValueError("Replayed duties have ambiguous player or unmapped club identities.")
        if (
            "team_code" in row
            and _positive_integer(row["team_code"], "team code") != clubs[team_id]
        ):
            raise ValueError("Replayed player club code differs from the original team mapping.")
        ranks = tuple(
            None if row[name].strip() in ("", "None") else _positive_integer(row[name], name)
            for name in TAKER_FIELDS
        )
        players.append(PhaseDutyPlayer(code, clubs[team_id], *ranks))
        identities.add(identity)
        codes.add(code)
    return PhaseDutyCapture(
        season=season,
        snapshot_id="git:" + replay.revision,
        source_fingerprint=hashes["players_raw.csv"],
        captured_at=retrieved,
        valid_until=expiry,
        model_use_approved=model_use_approved,
        model_use_evidence_ref=model_use_evidence_ref,
        players=tuple(players),
    )
