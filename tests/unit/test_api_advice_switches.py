"""The member menu's switches on the wire: the body, the query, the address and the refusals.

Two optional fields, ``top100_weight`` and ``managers_word``. Off is the default and leaves
every identity a plain request has (its fingerprint, its cache key, its stored spec) exactly
as it was; on, the address also names the per-capture input the answer is computed from, so
an answer from one export is never served as the answer from another.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from tests.unit.test_api_advice_post import (
    ADVICE_URL,
    BODY,
    CONTEXT,
    LEAGUE_ID,
    _publish_members,
)

from squadopt.api.app import create_app
from squadopt.application.advice_capabilities import TOP100_WEIGHTS, menu_capabilities
from squadopt.application.manager_words import MANAGERS_WORD_RULE_VERSION, ManagerWords
from squadopt.application.top100_weight import TOP100_PRICE_BASIS, Top100Counts
from squadopt.platform.advice_cache import (
    ADVICE_CACHE_CONTRACT_VERSION,
    AdviceCacheError,
    FileAdviceCache,
    advice_cache_key,
)
from squadopt.platform.advice_documents import (
    LEAGUE_CAPABILITIES_SCHEMA_PATH,
    league_capabilities_schema,
)
from squadopt.platform.advice_job_spec import (
    AdviceJobSpec,
    AdviceJobSpecError,
    FileAdviceJobSpecStore,
)
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
)
from squadopt.platform.advice_submit import AdviceSubmitService
from squadopt.platform.advice_switches import (
    MANAGERS_WORD_SWITCH,
    TOP100_SWITCH,
    AdviceSwitchInputs,
    SwitchInputUnavailable,
    switch_identity,
)
from squadopt.platform.api_contract import (
    ADVISE_TOP100_WEIGHTS,
    ApiCommandRequest,
    BackendApiContractError,
    backend_api_schema,
)

COUNTS = Top100Counts(
    counts={1001: 100},
    table_sha256="a" * 64,
    cohort_snapshot_id="fpl-top100-20260827T080000Z-000000000000",
    picks_snapshot_id="fpl-elite-picks-20260827T080100Z-111111111111",
    picks_gameweek=2,
)
WORDS = ManagerWords(
    season="2026-27",
    gameweek=3,
    source_kind="synthetic_fixture",
    source_label="club_news_v1.fixture.json",
    evidence_table="rotation_evidence_v2_2026-27_gw03_d45f1bea8b68.csv",
    clubs_covered=(),
    words=(),
)
BOTH = AdviceSwitchInputs(top100_counts=COUNTS, manager_words=WORDS, rotation_table_sha256="b" * 64)


class _Context:
    def current(self) -> AdviceRequestContext:
        return CONTEXT


class _Switches:
    def __init__(self, inputs: AdviceSwitchInputs) -> None:
        self.inputs = inputs

    def switch_inputs(self, context: AdviceRequestContext) -> AdviceSwitchInputs | None:
        assert context == CONTEXT
        return self.inputs


def _world(
    tmp_path: Path,
    inputs: AdviceSwitchInputs | None = BOTH,
    *,
    held_chips: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    _publish_members(tmp_path / "site")
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    specs = FileAdviceJobSpecStore(tmp_path / "specs")
    switches = None if inputs is None else _Switches(inputs)
    reader = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"),
        cache,
        _Context(),
        {slug: value.requires_rival for slug, value in menu_capabilities().items()},
        capabilities=menu_capabilities(),
        switches=switches,
        chip_availability=lambda context, league, entry: held_chips,
    )
    application = create_app(
        data_root=tmp_path / "site",
        advice_store=reader,
        advice_submit=AdviceSubmitService(reader, queue, specs=specs),
        utc_now=lambda: datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )
    return {
        "client": TestClient(application, raise_server_exceptions=False),
        "queue": queue,
        "specs": specs,
        "reader": reader,
        "switches": switches,
    }


# --- the contract -------------------------------------------------------------------------


def _advise(**changes: object) -> ApiCommandRequest:
    values: dict[str, object] = {
        "operation": "league.advise",
        "idempotency_key": "client:advise:1",
        "season": "2026-27",
        "gameweek": 3,
        "league_id": 352490,
        "entry_id": 313686,
        "strategy": "saf-puan",
        "window": 1,
        "capture_snapshot_id": "fpl-live-20260826T083133Z-d45f1bea8b68",
    }
    values.update(changes)
    return ApiCommandRequest(**values)  # type: ignore[arg-type]


def test_the_wire_enum_is_the_applications_own_list() -> None:
    assert ADVISE_TOP100_WEIGHTS == TOP100_WEIGHTS


def test_a_switch_left_off_moves_no_fingerprint_and_no_byte() -> None:
    plain = _advise()
    # The pin tests/unit/test_backend_api_contract.py holds, unchanged by the new fields.
    assert plain.request_fingerprint == (
        "c1ccaf17b696e15dbb5814f595f983862e0de7be0d39f569ea4e778dd7556ce6"
    )
    explicit = _advise(top100_weight=0, managers_word=False)
    assert explicit == plain and explicit.to_dict() == plain.to_dict()
    assert "top100_weight" not in plain.to_dict() and "managers_word" not in plain.to_dict()


def test_a_switch_turned_on_is_part_of_the_request() -> None:
    plain, weighted, worded = _advise(), _advise(top100_weight=20), _advise(managers_word=True)
    prints = {plain.request_fingerprint, weighted.request_fingerprint, worded.request_fingerprint}
    assert len(prints) == 3
    assert _advise(top100_weight=30).request_fingerprint not in prints
    schema = backend_api_schema()
    for request in (weighted, worded, _advise(top100_weight=50, managers_word=True)):
        document = request.to_dict()
        assert ApiCommandRequest.from_dict(document) == request
        jsonschema.validate(
            document, {**schema["$defs"]["AdviseCommandRequest"], "$defs": schema["$defs"]}
        )
    assert weighted.to_dict()["top100_weight"] == 20
    assert worded.to_dict()["managers_word"] is True


def test_the_switch_fields_are_strict() -> None:
    for bad in (15, True, 20.0, "20", None, -5):
        with pytest.raises(BackendApiContractError, match="top100_weight must be one of"):
            _advise(top100_weight=bad)
    with pytest.raises(BackendApiContractError, match="managers_word must be boolean"):
        _advise(managers_word=1)
    with pytest.raises(BackendApiContractError, match="accepts no top100_weight"):
        ApiCommandRequest(operation="season.tick", idempotency_key="k", top100_weight=5)
    body = backend_api_schema()["$defs"]["AdviseRequestBody"]
    jsonschema.validate({**BODY, "top100_weight": 5, "managers_word": True}, body)
    jsonschema.validate(BODY, body)
    for wrong in ({"top100_weight": 15}, {"managers_word": "yes"}, {"surprise": 1}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**BODY, **wrong}, body)


# --- the address --------------------------------------------------------------------------


def _key(**overrides: Any) -> str:
    fields: dict[str, Any] = {
        "advice_contract_version": "advice_v1",
        "capture_snapshot_id": "fpl-live-20260826T083133Z-d45f1bea8b68",
        "season": "2026-27",
        "gameweek": 3,
        "league_id": 352490,
        "entry_id": 313686,
        "strategy": "saf-puan",
        "window": 1,
        "projection_handoff_fingerprint": "f" * 64,
        "repository_commit": "abc1234",
        "configuration_fingerprint": "d" * 64,
    }
    fields.update(overrides)
    return advice_cache_key(**fields)


def test_a_plain_key_is_the_digest_it_has_always_been() -> None:
    """Spelled out by hand, so a change to the hashed document has to be made twice."""

    document = {
        "cache_contract_version": ADVICE_CACHE_CONTRACT_VERSION,
        "advice_contract_version": "advice_v1",
        "capture_snapshot_id": "fpl-live-20260826T083133Z-d45f1bea8b68",
        "season": "2026-27",
        "gameweek": 3,
        "league_id": 352490,
        "entry_id": 313686,
        "strategy": "saf-puan",
        "window": 1,
        "rival_entry_id": None,
        "projection_handoff_fingerprint": "f" * 64,
        "repository_commit": "abc1234",
        "configuration_fingerprint": "d" * 64,
    }
    expected = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert _key() == expected
    assert _key(switches=None) == expected
    assert _key(switches={}) == expected


def test_a_switched_key_names_the_value_and_the_input_it_was_computed_from() -> None:
    at_20 = switch_identity(BOTH, top100_weight=20)
    assert at_20 == {
        TOP100_SWITCH: {
            "weight": 20,
            "price_basis": TOP100_PRICE_BASIS,
            "table_sha256": "a" * 64,
            "cohort_snapshot_id": COUNTS.cohort_snapshot_id,
            "picks_snapshot_id": COUNTS.picks_snapshot_id,
            "picks_gameweek": 2,
        }
    }
    word = switch_identity(BOTH, managers_word=True)
    assert word[MANAGERS_WORD_SWITCH]["rule_version"] == MANAGERS_WORD_RULE_VERSION
    assert word[MANAGERS_WORD_SWITCH]["rotation_table_sha256"] == "b" * 64
    assert switch_identity(BOTH) == {}

    other_export = AdviceSwitchInputs(
        top100_counts=Top100Counts(
            counts={1001: 100},
            table_sha256="c" * 64,
            cohort_snapshot_id=COUNTS.cohort_snapshot_id,
            picks_snapshot_id=COUNTS.picks_snapshot_id,
            picks_gameweek=2,
        )
    )
    keys = {
        _key(),
        _key(switches=at_20),
        _key(switches=switch_identity(BOTH, top100_weight=30)),
        _key(switches=switch_identity(other_export, top100_weight=20)),
        _key(switches=word),
        _key(switches=switch_identity(BOTH, top100_weight=20, managers_word=True)),
    }
    assert len(keys) == 6
    with pytest.raises(SwitchInputUnavailable) as missing:
        switch_identity(other_export, managers_word=True)
    assert missing.value.switch == MANAGERS_WORD_SWITCH
    with pytest.raises(AdviceCacheError, match="JSON scalars"):
        _key(switches={"top100": {"weight": [20]}})  # type: ignore[dict-item]
    with pytest.raises(AdviceCacheError, match="leave it out when off"):
        _key(switches={"top100": {}})


def test_a_plain_spec_keeps_its_bytes_and_a_switched_one_round_trips() -> None:
    plain = AdviceJobSpec(
        league_id=LEAGUE_ID, entry_id=313686, strategy="saf-puan", window=1, context=CONTEXT
    )
    assert set(plain.as_payload()) == {
        "contract_version",
        "league_id",
        "entry_id",
        "strategy",
        "window",
        "rival_entry_id",
        "context",
    }
    switched = AdviceJobSpec(
        league_id=LEAGUE_ID,
        entry_id=313686,
        strategy="saf-puan",
        window=1,
        context=CONTEXT,
        switches=switch_identity(BOTH, top100_weight=20, managers_word=True),
    )
    assert AdviceJobSpec.from_payload(json.loads(json.dumps(switched.as_payload()))) == switched
    assert switched.switch(TOP100_SWITCH)["weight"] == 20
    assert plain.switch(TOP100_SWITCH) == {}
    with pytest.raises(AdviceJobSpecError):
        AdviceJobSpec.from_payload({**plain.as_payload(), "switches": {"top100": {}}})
    with pytest.raises(AdviceJobSpecError):
        AdviceJobSpec.from_payload({**plain.as_payload(), "switches": ["top100"]})


# --- the routes ---------------------------------------------------------------------------


def test_a_switched_post_files_its_own_job_and_records_what_it_was_accepted_against(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    client = world["client"]

    plain = client.post(ADVICE_URL, json=BODY)
    weighted = client.post(ADVICE_URL, json={**BODY, "top100_weight": 20})
    both = client.post(ADVICE_URL, json={**BODY, "top100_weight": 20, "managers_word": True})
    again = client.post(ADVICE_URL, json={**BODY, "top100_weight": 20, "managers_word": False})
    assert [r.status_code for r in (plain, weighted, both, again)] == [202, 202, 202, 202]
    assert again.json()["job_id"] == weighted.json()["job_id"]
    assert len({r.json()["job_id"] for r in (plain, weighted, both)}) == 3

    job = world["queue"].load(weighted.json()["job_id"])
    spec = world["specs"].get(job.cache_key)
    assert spec.switches == switch_identity(BOTH, top100_weight=20)
    plain_job = world["queue"].load(plain.json()["job_id"])
    assert world["specs"].get(plain_job.cache_key).switches == {}
    # The GET addresses the same key the POST filed the job under.
    read = client.get(ADVICE_URL, params={**BODY, "top100_weight": 20})
    assert read.status_code == 404 and read.json()["error"]["code"] == "NOT_COMPUTED"
    world["reader"]._cache.put(job.cache_key, _document(top100_weight=20))
    served = client.get(ADVICE_URL, params={**BODY, "top100_weight": 20})
    assert served.status_code == 200
    assert served.json()["payload"]["top100"]["weight"] == 20
    assert client.get(ADVICE_URL, params=BODY).status_code == 404


def _document(**payload: object) -> bytes:
    return json.dumps(
        {
            "contract_version": "provisional_league_ui_v1",
            "generated_at_utc": "2026-08-27T12:00:00Z",
            "source_kind": "live",
            "payload": {
                "season": "2026-27",
                "gameweek": 3,
                "entry_id": 313686,
                "league_id": LEAGUE_ID,
                "mode": "saf-puan",
                "window": 1,
                "moves": [],
                "data_quality": "complete",
                "missing_fields": [],
                "top100": {
                    "weight": payload["top100_weight"],
                    "changed": False,
                    "price_basis": TOP100_PRICE_BASIS,
                },
            },
        }
    ).encode("utf-8")


def test_a_new_export_is_a_new_address(tmp_path: Path) -> None:
    world = _world(tmp_path)
    body = {**BODY, "top100_weight": 20}
    first = world["client"].post(ADVICE_URL, json=body).json()["job_id"]
    world["switches"].inputs = AdviceSwitchInputs(
        top100_counts=Top100Counts(
            counts={1001: 99},
            table_sha256="e" * 64,
            cohort_snapshot_id=COUNTS.cohort_snapshot_id,
            picks_snapshot_id=COUNTS.picks_snapshot_id,
            picks_gameweek=2,
        )
    )
    second = world["client"].post(ADVICE_URL, json=body).json()["job_id"]
    assert first != second


@pytest.mark.parametrize(
    ("inputs", "body", "code"),
    [
        (None, {"top100_weight": 20}, "TOP100_INPUTS_UNAVAILABLE"),
        (AdviceSwitchInputs(), {"top100_weight": 20}, "TOP100_INPUTS_UNAVAILABLE"),
        (AdviceSwitchInputs(), {"managers_word": True}, "MANAGERS_WORD_UNAVAILABLE"),
        (
            AdviceSwitchInputs(top100_counts=COUNTS),
            {"top100_weight": 20, "managers_word": True},
            "MANAGERS_WORD_UNAVAILABLE",
        ),
    ],
)
def test_a_switch_the_capture_cannot_answer_is_refused_by_name_and_never_queued(
    tmp_path: Path, inputs: AdviceSwitchInputs | None, body: dict[str, Any], code: str
) -> None:
    world = _world(tmp_path, inputs)
    posted = world["client"].post(ADVICE_URL, json={**BODY, **body})
    read = world["client"].get(ADVICE_URL, params={**BODY, **body})
    for response in (posted, read):
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code
    assert world["queue"].jobs() == ()
    # The plain request is not affected by what the capture lacks.
    assert world["client"].post(ADVICE_URL, json=BODY).status_code == 202


@pytest.mark.parametrize(
    "body",
    [
        {"strategy": "saf-puan", "window": 3, "managers_word": True},
        {"strategy": "fark-yarat", "window": 1, "rival_entry_id": 2199732, "managers_word": True},
    ],
)
def test_the_word_outside_the_one_week_pure_points_plan_is_unsupported(
    tmp_path: Path, body: dict[str, Any]
) -> None:
    world = _world(tmp_path)
    response = world["client"].post(ADVICE_URL, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"
    assert world["queue"].jobs() == ()


def test_the_menu_reaches_rival_windows_and_settings_on_every_strategy(tmp_path: Path) -> None:
    world = _world(tmp_path)
    for body in (
        {"strategy": "fark-yarat", "window": 3, "rival_entry_id": 2199732},
        {"strategy": "ortak-koru", "window": 5, "rival_entry_id": 2199732, "top100_weight": 10},
        {"strategy": "saf-puan", "window": 5, "top100_weight": 50},
    ):
        assert world["client"].post(ADVICE_URL, json=body).status_code == 202, body
    assert len(world["queue"].jobs()) == 3


@pytest.mark.parametrize(
    "extra",
    [
        {"top100_weight": 15},
        {"top100_weight": True},
        {"top100_weight": "20"},
        {"managers_word": "true"},
        {"managers_word": 1},
        {"surprise": 1},
    ],
)
def test_the_strict_body_refuses_a_malformed_switch(tmp_path: Path, extra: dict[str, Any]) -> None:
    world = _world(tmp_path)
    response = world["client"].post(ADVICE_URL, json={**BODY, **extra})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert world["queue"].jobs() == ()


def test_the_query_refuses_a_setting_nobody_offers(tmp_path: Path) -> None:
    world = _world(tmp_path)
    for params in ({"top100_weight": 15}, {"top100_weight": "x"}, {"managers_word": "maybe"}):
        response = world["client"].get(ADVICE_URL, params={**BODY, **params})
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# --- capabilities -------------------------------------------------------------------------


def test_capabilities_say_what_may_be_asked_right_now(tmp_path: Path) -> None:
    world = _world(tmp_path)
    url = f"/api/v1/leagues/{LEAGUE_ID}/capabilities"
    document = world["client"].get(url).json()
    assert document == {
        "contract_version": "league_capabilities_v1",
        "league_id": LEAGUE_ID,
        "capture_snapshot_id": CONTEXT.capture_snapshot_id,
        "season": "2026-27",
        "gameweek": 3,
        "strategies": {
            "fark-yarat": {"windows": [1, 3, 5], "requires_rival": True},
            "ortak-koru": {"windows": [1, 3, 5], "requires_rival": True},
            "saf-puan": {"windows": [1, 3, 5], "requires_rival": False},
        },
        "top100": {"available": True, "weights": list(TOP100_WEIGHTS)},
        "managers_word": {"available": True},
        "chips": {"held_by_entry": {}},
    }
    jsonschema.validate(document, league_capabilities_schema())

    world["switches"].inputs = AdviceSwitchInputs()
    without = world["client"].get(url).json()
    assert without["top100"] == {"available": False, "weights": [0]}
    assert without["managers_word"] == {"available": False}

    missing = world["client"].get("/api/v1/leagues/999/capabilities")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LEAGUE_NOT_CONNECTED"


def test_a_reader_wired_as_before_offers_no_switch(tmp_path: Path) -> None:
    _publish_members(tmp_path / "site")
    reader = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"),
        FileAdviceCache(tmp_path / "cache"),
        _Context(),
        {"saf-puan": False, "fark-yarat": True},
    )
    document = reader.league_capabilities(LEAGUE_ID)
    assert document["strategies"] == {
        "fark-yarat": {"windows": [1], "requires_rival": True},
        "saf-puan": {"windows": [1, 3, 5], "requires_rival": False},
    }
    assert document["top100"] == {"available": False, "weights": [0]}
    assert document["managers_word"] == {"available": False}


def test_the_committed_capabilities_schema_matches_its_generator() -> None:
    committed = json.loads(LEAGUE_CAPABILITIES_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == league_capabilities_schema()
