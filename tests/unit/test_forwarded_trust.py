"""Declared proxy trust is observable without collecting visitor addresses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from squadopt.api import runtime


@pytest.fixture(autouse=True)
def clean_server_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(runtime.os.environ):
        if name.startswith("UVICORN_") or name == "FORWARDED_ALLOW_IPS":
            monkeypatch.delenv(name)


def observe(monkeypatch: pytest.MonkeyPatch, *flags: str) -> dict[str, object]:
    monkeypatch.setattr(
        runtime.sys, "argv", ["uvicorn", "squadopt.api.runtime:build_app", "--factory", *flags]
    )
    return runtime._forwarded_trust()


def test_unset_cli_reports_the_server_loopback_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert observe(monkeypatch) == {
        "trust_status": "enabled",
        "trust_source": "uvicorn default",
        "forwarded_allow_ips_set": False,
        "forwarded_allow_ips_count": 1,
        "proxy_headers": True,
        "proxy_headers_source": "uvicorn default",
    }


def test_cli_overrides_environment_and_names_both_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    monkeypatch.setenv("UVICORN_FORWARDED_ALLOW_IPS", "192.0.2.2")
    monkeypatch.setenv("UVICORN_PROXY_HEADERS", "false")
    result = observe(monkeypatch, "--proxy-headers", "--forwarded-allow-ips=127.0.0.1")
    assert result["forwarded_allow_ips_set"] is True
    assert result["forwarded_allow_ips_count"] == 1
    assert result["trust_status"] == "enabled"
    assert result["trust_source"] == "uvicorn commandline"
    assert result["proxy_headers_source"] == "uvicorn commandline"


@pytest.mark.parametrize(
    "name,source",
    [
        ("FORWARDED_ALLOW_IPS", "FORWARDED_ALLOW_IPS"),
        ("UVICORN_FORWARDED_ALLOW_IPS", "uvicorn environment"),
    ],
)
def test_environment_allowlist_is_named(
    monkeypatch: pytest.MonkeyPatch, name: str, source: str
) -> None:
    monkeypatch.setenv(name, "192.0.2.0/24, , 198.51.100.1")
    result = observe(monkeypatch)
    assert result["forwarded_allow_ips_set"] is True
    assert result["forwarded_allow_ips_count"] == 2
    assert "192.0.2.0" not in json.dumps(result)
    assert "198.51.100.1" not in json.dumps(result)
    assert result["trust_source"] == source


def test_disabled_headers_do_not_claim_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    result = observe(monkeypatch, "--no-proxy-headers")
    assert result["trust_status"] == "disabled"
    assert result["proxy_headers"] is False


@pytest.mark.parametrize("allowed", ["", " , "])
def test_empty_allowlist_trusts_no_peer(monkeypatch: pytest.MonkeyPatch, allowed: str) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", allowed)
    result = observe(monkeypatch)
    assert result["trust_status"] == "disabled"
    assert result["forwarded_allow_ips_set"] is True
    assert result["forwarded_allow_ips_count"] == 0


@pytest.mark.parametrize("entry", ["uvicorn.exe", "/venv/lib/uvicorn/__main__.py"])
def test_supported_cli_launch_shapes(monkeypatch: pytest.MonkeyPatch, entry: str) -> None:
    monkeypatch.setattr(runtime.sys, "argv", [entry, "squadopt.api.runtime:build_app", "--factory"])
    assert runtime._forwarded_trust()["trust_status"] == "enabled"


def test_programmatic_launcher_does_not_mistake_environment_for_effective_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    monkeypatch.setattr(runtime.sys, "argv", ["custom_server.py"])
    assert runtime._forwarded_trust() == {
        "trust_status": "unverified",
        "trust_source": "unknown launcher",
    }


def test_env_file_cannot_reconstruct_earlier_cli_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "server.env"
    env_file.write_text("", encoding="utf-8")
    assert observe(monkeypatch, "--env-file", str(env_file))["trust_status"] == "unverified"


def test_factory_emits_one_structured_configuration_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    observe(monkeypatch, "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1")
    monkeypatch.setattr(runtime, "configure_advice_logging", lambda: None)
    monkeypatch.setattr(runtime, "backend_from_environment", lambda **kwargs: object())
    app = FastAPI()
    monkeypatch.setattr(runtime, "app_for_backend", lambda backend: app)
    caplog.set_level("INFO", logger="advice.api")
    assert runtime.build_app() is app
    records = [json.loads(record.message) for record in caplog.records]
    assert len(records) == 1
    assert records[0]["event"] == "advice_forwarded_trust"
    assert records[0]["component"] == "api"
    assert records[0]["forwarded_allow_ips_set"] is True
    assert records[0]["forwarded_allow_ips_count"] == 1
    assert "127.0.0.1" not in caplog.text
    assert set(records[0]) == {
        "event",
        "component",
        "at_utc",
        "trust_status",
        "trust_source",
        "forwarded_allow_ips_set",
        "forwarded_allow_ips_count",
        "proxy_headers",
        "proxy_headers_source",
    }


@pytest.mark.parametrize(
    "peer,allowed,expected",
    [
        ("127.0.0.1", "127.0.0.1", "198.51.100.9"),
        ("192.0.2.10", "127.0.0.1", "192.0.2.10"),
        ("192.0.2.10", "192.0.2.0/24", "198.51.100.9"),
    ],
)
def test_server_only_accepts_forwarded_visitor_from_a_trusted_peer(
    peer: str, allowed: str, expected: str
) -> None:
    clients: list[Any] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        clients.append(scope["client"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    client = TestClient(ProxyHeadersMiddleware(app, trusted_hosts=allowed), client=(peer, 43210))
    assert client.get("/", headers={"x-forwarded-for": "198.51.100.9"}).status_code == 204
    assert clients[0][0] == expected


def test_container_templates_enable_headers_without_inventing_a_peer() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "deploy/compose.yaml").read_text(encoding="utf-8")
    azure = (root / "deploy/containerapp.yaml").read_text(encoding="utf-8")
    example = (root / "deploy/backend.env.example").read_text(encoding="utf-8")
    assert "--proxy-headers" in compose and "--proxy-headers" in azure
    assert "      FORWARDED_ALLOW_IPS:\n" in compose
    assert "- name: FORWARDED_ALLOW_IPS" not in azure
    assert not any(line.startswith("FORWARDED_ALLOW_IPS=") for line in example.splitlines())
    assert all("UNVERIFIED" in text for text in (compose, azure, example))
