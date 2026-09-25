"""Chosen chips use the published solve and stay distinct through HTTP and storage."""

import json
from pathlib import Path
from typing import Any

import pytest

from squadopt.application.advice_menu import ChipUnavailable, MenuRequest, advise_menu_entry
from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.live.rules import CHIP_NAMES
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.api_contract import ADVISE_CHIPS, ApiCommandRequest

LEAGUE = 352490


def _advise(**changes: object) -> ApiCommandRequest:
    return ApiCommandRequest(
        **{
            "operation": "league.advise",
            "idempotency_key": "client:advise:1",
            "season": "2026-27",
            "gameweek": 3,
            "league_id": LEAGUE,
            "entry_id": 313686,
            "strategy": "saf-puan",
            "window": 1,
            "capture_snapshot_id": "fpl-live-20260826T083133Z-d45f1bea8b68",
            **changes,
        }
    )  # type: ignore[arg-type]


def test_chip_identity_roundtrips_and_preserves_the_plain_fingerprint() -> None:
    assert set(ADVISE_CHIPS) == {*CHIP_NAMES, "auto"}
    assert _advise().request_fingerprint == _advise(chip=None).request_fingerprint
    fingerprints = {_advise().request_fingerprint}
    for chip in ADVISE_CHIPS:
        command = _advise(chip=chip)
        assert ApiCommandRequest.from_dict(command.to_dict()) == command
        fingerprints.add(command.request_fingerprint)
    assert len(fingerprints) == 6


def test_post_get_cache_and_capabilities_carry_each_chip(
    tmp_path: Path, chip_http: dict[str, Any]
) -> None:
    state = chip_http["build"](CHIP_NAMES)
    client = state["client"]
    caps = client.get(f"/api/v1/leagues/{LEAGUE}/capabilities").json()
    assert caps["chips"]["held_by_entry"]["313686"] == list(CHIP_NAMES)
    keys = set()
    for chip in CHIP_NAMES:
        response = client.post(chip_http["url"], json={**chip_http["body"], "chip": chip})
        assert response.status_code == 202, response.text
        job = state["queue"].load(response.json()["job_id"])
        spec = state["specs"].get(job.cache_key)
        assert spec.switch("chip")["chip"] == chip
        keys.add(job.cache_key)
        params = {"strategy": "saf-puan", "window": 1, "chip": chip}
        assert client.get(chip_http["url"], params=params).status_code == 404
        payload = chip_http["payload"]
        FileAdviceCache(tmp_path / "cache").put(job.cache_key, payload)
        assert client.get(chip_http["url"], params=params).content == payload
        assert (
            client.post(chip_http["url"], json={**chip_http["body"], "chip": chip}).content
            == payload
        )
    assert len(keys) == 4


@pytest.mark.parametrize("held,code", [(None, "CHIP_HISTORY_UNKNOWN"), ((), "CHIP_NOT_HELD")])
def test_unknown_or_spent_chip_is_refused_before_queueing(
    chip_http: dict[str, Any], held: Any, code: str
) -> None:
    state = chip_http["build"](held)
    client = state["client"]
    for response in (
        client.post(chip_http["url"], json={**chip_http["body"], "chip": "bboost"}),
        client.get(
            chip_http["url"], params={"strategy": "saf-puan", "window": 1, "chip": "bboost"}
        ),
    ):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
    assert not state["queue"].jobs()


@pytest.mark.parametrize("extra", [{"managers_word": True}])
def test_chip_cannot_combine_with_other_switches(
    chip_http: dict[str, Any], extra: dict[str, Any]
) -> None:
    state = chip_http["build"](CHIP_NAMES)
    response = state["client"].post(
        chip_http["url"], json={**chip_http["body"], "chip": "bboost", **extra}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"
    assert not state["queue"].jobs()


def test_the_automatic_chip_strategy_is_not_offered_and_is_refused_before_queueing(
    chip_http: dict[str, Any],
) -> None:
    """Audit 2026-09-25, H3: its holding value cannot beat the window's best week."""

    state = chip_http["build"](CHIP_NAMES)
    client = state["client"]
    caps = client.get(f"/api/v1/leagues/{LEAGUE}/capabilities").json()
    assert "strategy" not in caps["chips"]
    assert caps["chips"]["held_by_entry"]["313686"] == list(CHIP_NAMES)
    for window in (1, 3, 5):
        body = {**chip_http["body"], "window": window, "chip": "auto"}
        for response in (
            client.post(chip_http["url"], json=body),
            client.get(chip_http["url"], params=body),
        ):
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert error["code"] == "UNSUPPORTED_ADVICE_REQUEST"
            assert "automatic chip strategy is not offered" in error["message"]
    assert not state["queue"].jobs()


def test_three_members_match_every_published_chip_file(
    chip_publication: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = (chip_publication[key] for key in ("inputs", "projection", "rules"))
    picks, provider = chip_publication["picks"], chip_publication["provider"]
    registrations = tuple(
        EntryRegistration(entry, f"member-{entry}", "2026-08-23T00:00:00Z") for entry in picks
    )
    build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=LEAGUE,
        league_name="Test League",
        out_dir=tmp_path,
    )
    fields = ("moves", "captain", "starting_xi", "expected_own_points", "chip_choice")
    for entry in picks:
        for chip in CHIP_NAMES:
            published = json.loads(
                (tmp_path / f"advice/{entry}/saf-puan/1/chip-{chip}.json").read_text(
                    encoding="utf-8"
                )
            )["payload"]
            request = MenuRequest("2026-27", 2, LEAGUE, entry, chip=chip)
            answer = advise_menu_entry(
                request, provider=provider, inputs=inputs, projection=projection, rules=rules
            )
            assert {f: answer[f] for f in fields} == {f: published[f] for f in fields}
    spent = chip_publication["spent_provider"]
    with pytest.raises(ChipUnavailable) as refused:
        advise_menu_entry(
            MenuRequest("2026-27", 2, LEAGUE, 101, chip="bboost"),
            provider=spent,
            inputs=inputs,
            projection=projection,
            rules=rules,
        )
    assert refused.value.code == "CHIP_NOT_HELD"
