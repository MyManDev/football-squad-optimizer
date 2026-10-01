"""Anthropic failures remain per-club refusals without logging credentials."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from squadopt.data.sources.club_news import FixtureClubNewsProvider
from squadopt.platform.club_news_model import AnthropicClubNewsProvider, ClubNewsModelError

SECRET = "sentinel-anthropic-key-do-not-print"


class SdkError(Exception):
    status_code = 401


class Client:
    def __init__(self, response: object = None) -> None:
        self.response = response
        self.calls = 0

    @property
    def messages(self) -> Client:
        return self

    def create(self, **kwargs: Any) -> object:
        self.calls += 1
        if self.response is None:
            raise SdkError(f"remote body and x-api-key: {SECRET}")
        return self.response


def inputs() -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    fixture = FixtureClubNewsProvider(
        Path(__file__).resolve().parents[2] / "data" / "sample" / "club_news_v1.fixture.json"
    )
    return tuple(fixture.fetch(url) for url in fixture.urls), fixture.roster()


def test_sdk_failure_is_sanitized_unchained_and_not_retried_by_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(APIError=SdkError))
    client = Client()
    provider = AnthropicClubNewsProvider(client=client, api_key=SECRET)
    with pytest.raises(ClubNewsModelError, match="HTTP 401") as captured:
        provider.code(*inputs())
    assert client.calls == 1
    assert SECRET not in str(captured.value)
    assert SECRET not in "".join(traceback.format_exception(captured.value))
    assert captured.value.__suppress_context__ is True


def test_refusal_text_cannot_echo_the_key() -> None:
    client = Client(
        SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category=SECRET))
    )
    provider = AnthropicClubNewsProvider(client=client, api_key=SECRET)
    with pytest.raises(ClubNewsModelError) as captured:
        provider.code(*inputs())
    assert SECRET not in str(captured.value)
    assert "[key withheld]" in str(captured.value)


@pytest.mark.parametrize("key", ["", "space inside", "line\nbreak", "nonascii-ş"])
def test_an_invalid_header_key_refuses_without_quoting_it(key: str) -> None:
    with pytest.raises(ClubNewsModelError) as captured:
        AnthropicClubNewsProvider(client=Client(), api_key=key)
    assert str(captured.value) == "The API key must be a single printable token."
