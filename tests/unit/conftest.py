"""Shared setup for member-menu HTTP and publication checks."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_read import AdviceReadStore, AdviceRequestContext, FileLeagueDirectory
from squadopt.platform.advice_submit import AdviceSubmitService
from squadopt.platform.advice_switches import AdviceSwitchInputs


def advice_http_world(
    root: Path, context_provider: Any, switches: Any, held_chips: tuple[str, ...] | None
) -> dict[str, Any]:
    """Wire the real HTTP, queue and cache around already published synthetic members."""
    cache = FileAdviceCache(root / "cache")
    queue = FileJobQueue(root / "jobs")
    specs = FileAdviceJobSpecStore(root / "specs")
    reader = AdviceReadStore(
        FileLeagueDirectory(root / "site"),
        cache,
        context_provider,
        {slug: value.requires_rival for slug, value in menu_capabilities().items()},
        capabilities=menu_capabilities(),
        switches=switches,
        chip_availability=lambda context, league, entries: dict.fromkeys(entries, held_chips),
    )
    application = create_app(
        data_root=root / "site",
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


@pytest.fixture
def chip_http(tmp_path: Path) -> dict[str, Any]:
    from tests.unit.test_advice_read import _valid_advice_document
    from tests.unit.test_api_advice_post import (
        ADVICE_URL,
        BODY,
        CONTEXT,
        LEAGUE_ID,
        _publish_members,
    )

    class Context:
        def current(self) -> AdviceRequestContext:
            return CONTEXT

    class Switches:
        def switch_inputs(self, context: AdviceRequestContext) -> AdviceSwitchInputs:
            return AdviceSwitchInputs()

    def build(held_chips: tuple[str, ...] | None) -> dict[str, Any]:
        _publish_members(tmp_path / "site")
        return advice_http_world(tmp_path, Context(), Switches(), held_chips)

    return {
        "build": build,
        "url": ADVICE_URL,
        "body": BODY,
        "league": LEAGUE_ID,
        "payload": _valid_advice_document(),
    }


@pytest.fixture
def chip_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from dataclasses import replace

    from tests.unit.test_advice_chips import _every_chip_open
    from tests.unit.test_league_views import (
        DISCRETIONARY_SQUAD,
        _legal_squad,
        _member_picks,
        _Provider,
        _world_context,
    )
    from tests.unit.test_live_transfers import _world

    world = _world.__wrapped__(tmp_path, monkeypatch)
    inputs, projection, rules = _world_context(world)
    rules = _every_chip_open(rules)
    picks = {
        entry: replace(
            _member_picks(
                world, entry, list(DISCRETIONARY_SQUAD) if entry == 303 else _legal_squad(world)
            ),
            bank_tenths=bank,
        )
        for entry, bank in ((101, 5), (202, 10), (303, 15))
    }
    assert picks[303].squad != picks[101].squad
    return {
        "inputs": inputs,
        "projection": projection,
        "rules": rules,
        "picks": picks,
        "provider": _Provider(picks),
        "spent_provider": _Provider({101: replace(picks[101], chips_used={"bboost": (1,)})}),
    }
