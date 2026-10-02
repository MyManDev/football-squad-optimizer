"""Private settings and offline preflight; no real clients or network are used."""

from __future__ import annotations

from pathlib import Path

import pytest

from squadopt.data.sources.club_news import ClubNewsError
from squadopt.platform import club_news_acquire, club_news_provider
from squadopt.platform.club_news_provider import (
    DEFAULT_PROVIDER,
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    resolve_provider_config,
)

SECRET = "sentinel-private-key-do-not-print"


def settings(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "private.toml"
    path.write_text("[llm]\n" + body, encoding="utf-8")
    return path


def test_file_selects_model_and_key_without_changing_the_environment(tmp_path: Path) -> None:
    path = settings(tmp_path, f'provider="gemini"\nmodel="gemini-3.6-flash"\napi_key="{SECRET}"\n')
    source: dict[str, str] = {}
    config = resolve_provider_config(source, settings_file=path)
    assert (config.provider, config.model_identifier, config.api_key) == (
        "gemini",
        "gemini-3.6-flash",
        SECRET,
    )
    assert SECRET not in repr(config)
    assert source == {}


def test_environment_model_and_key_override_the_same_file_destination(tmp_path: Path) -> None:
    path = settings(tmp_path, f'provider="gemini"\nmodel="gemini-3.6-flash"\napi_key="{SECRET}"\n')
    config = resolve_provider_config(
        {MODEL_ENVIRONMENT_VARIABLE: "gemini-3.8-flash", KEY_ENVIRONMENT_VARIABLE: "replacement"},
        settings_file=path,
    )
    assert config.model_identifier == "gemini-3.8-flash"
    assert config.api_key == "replacement"


def test_provider_override_never_reuses_file_key_or_model(tmp_path: Path) -> None:
    path = settings(tmp_path, f'provider="gemini"\nmodel="gemini-3.6-flash"\napi_key="{SECRET}"\n')
    with pytest.raises(ClubNewsError, match="unset"):
        resolve_provider_config({PROVIDER_ENVIRONMENT_VARIABLE: "anthropic"}, settings_file=path)
    config = resolve_provider_config(
        {PROVIDER_ENVIRONMENT_VARIABLE: "anthropic", "ANTHROPIC_API_KEY": "anthropic-only"},
        settings_file=path,
    )
    assert config.provider == DEFAULT_PROVIDER
    assert config.model_identifier != "gemini-3.6-flash"
    assert config.api_key == "anthropic-only"


def test_endpoint_override_requires_a_new_credential_and_model(tmp_path: Path) -> None:
    path = settings(
        tmp_path,
        f'provider="openai-compatible"\nmodel="old-model"\napi_key="{SECRET}"\n'
        'base_url="https://first.example/v1"\n',
    )
    override = {
        "SQUADOPT_LLM_BASE_URL": "https://second.example/v1",
        MODEL_ENVIRONMENT_VARIABLE: "new-model",
    }
    with pytest.raises(ClubNewsError, match="unset"):
        resolve_provider_config(override, settings_file=path)
    config = resolve_provider_config(
        {**override, KEY_ENVIRONMENT_VARIABLE: "second-endpoint-key"}, settings_file=path
    )
    assert config.api_key == "second-endpoint-key"
    assert config.base_url == "https://second.example/v1"
    assert config.model_identifier == "new-model"


def test_equivalent_official_endpoint_keeps_the_file_bound_key_and_model(tmp_path: Path) -> None:
    path = settings(tmp_path, f'provider="openai"\nmodel="chosen-model"\napi_key="{SECRET}"\n')
    config = resolve_provider_config(
        {"SQUADOPT_LLM_BASE_URL": "https://API.OPENAI.COM:443/v1/"}, settings_file=path
    )
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key == SECRET
    assert config.model_identifier == "chosen-model"


def test_explicit_environment_key_reference_is_private_and_required(tmp_path: Path) -> None:
    path = settings(
        tmp_path, 'provider="openai"\nmodel="chosen-model"\napi_key_env="MY_NEWS_KEY"\n'
    )
    with pytest.raises(ClubNewsError, match="api_key_env is unset"):
        resolve_provider_config({}, settings_file=path)
    config = resolve_provider_config({"MY_NEWS_KEY": SECRET}, settings_file=path)
    assert config.api_key == SECRET
    assert config.base_url == "https://api.openai.com/v1"
    assert SECRET not in repr(config)


@pytest.mark.parametrize(
    "body",
    [
        'provider="gemini"\napi_key="one"\napi_key_env="MY_KEY"\n',
        'provider="gemini"\napi_key_env="ANTHROPIC_API_KEY"\n',
        'provider="openai"\nmax_completion_tokens=true\n',
        'provider="openai"\nallow_local_http="true"\n',
        'provider="openai"\nunknown="value"\n',
        'model="no-explicit-provider"\n',
    ],
)
def test_ambiguous_or_mistyped_private_settings_refuse(tmp_path: Path, body: str) -> None:
    with pytest.raises(ClubNewsError):
        resolve_provider_config({}, settings_file=settings(tmp_path, body))


def test_invalid_toml_never_echoes_the_secret_line(tmp_path: Path) -> None:
    path = settings(tmp_path, f'provider="openai"\napi_key="{SECRET}\n')
    with pytest.raises(ClubNewsError) as error:
        resolve_provider_config({}, settings_file=path)
    assert SECRET not in str(error.value)
    assert str(path) not in str(error.value)


@pytest.mark.parametrize(
    "source",
    [
        {PROVIDER_ENVIRONMENT_VARIABLE: "openai", KEY_ENVIRONMENT_VARIABLE: SECRET},
        {
            PROVIDER_ENVIRONMENT_VARIABLE: "openai-compatible",
            KEY_ENVIRONMENT_VARIABLE: SECRET,
            MODEL_ENVIRONMENT_VARIABLE: "chosen-model",
        },
        {
            PROVIDER_ENVIRONMENT_VARIABLE: "openai",
            KEY_ENVIRONMENT_VARIABLE: SECRET,
            MODEL_ENVIRONMENT_VARIABLE: "chosen-model",
            "SQUADOPT_LLM_BASE_URL": "https://other.example/v1",
        },
    ],
)
def test_openai_requires_explicit_model_and_compatible_destination(source: dict[str, str]) -> None:
    with pytest.raises(ClubNewsError):
        resolve_provider_config(source)


def test_offline_check_does_not_build_a_client_read_a_roster_or_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = settings(tmp_path, f'provider="openai"\nmodel="chosen-model"\napi_key="{SECRET}"\n')

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Offline preflight crossed an external boundary")

    monkeypatch.setattr(club_news_acquire, "build_coding_provider", forbidden)
    monkeypatch.setattr(club_news_acquire, "load_club_sources", forbidden)
    monkeypatch.setattr(club_news_acquire, "read_snapshot", forbidden)
    monkeypatch.setattr(club_news_provider.importlib.util, "find_spec", lambda _: object())
    before = sorted(p.name for p in tmp_path.iterdir())
    assert (
        club_news_acquire.main(
            ["--check-config", "--settings-file", str(path)], environ={}, opener=forbidden
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "openai" in output and "chosen-model" in output and "Offline check only" in output
    assert SECRET not in output
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_check_config_catches_unlisted_gemini_model_before_constructing_a_client(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = settings(tmp_path, f'provider="gemini"\nmodel="unlisted-model"\napi_key="{SECRET}"\n')
    assert club_news_acquire.main(["--check-config", "--settings-file", str(path)], environ={}) == 1
    output = capsys.readouterr().out
    assert "Refused:" in output and SECRET not in output


def test_compatible_completion_settings_are_typed_and_preserved(tmp_path: Path) -> None:
    path = settings(
        tmp_path,
        f'provider="openai-compatible"\nmodel="chosen-model"\napi_key="{SECRET}"\n'
        'base_url="https://compatible.example/v1"\nresponse_format="json_object"\n'
        "max_completion_tokens=4096\nallow_local_http=false\n",
    )
    config = resolve_provider_config({}, settings_file=path)
    club_news_provider.validate_provider_config(config)
    assert (config.response_format, config.max_completion_tokens, config.allow_local_http) == (
        "json_object",
        4096,
        False,
    )


def test_a_missing_dependency_is_an_offline_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(club_news_provider.importlib.util, "find_spec", lambda _: None)
    assert (
        club_news_acquire.main(
            ["--check-config"],
            environ={
                PROVIDER_ENVIRONMENT_VARIABLE: "openai",
                MODEL_ENVIRONMENT_VARIABLE: "chosen-model",
                KEY_ENVIRONMENT_VARIABLE: SECRET,
            },
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "llm extra" in output and SECRET not in output


def test_selected_openai_settings_reach_the_existing_provider_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = settings(
        tmp_path,
        f'provider="openai-compatible"\nmodel="chosen-model"\napi_key="{SECRET}"\n'
        'base_url="https://compatible.example/v1"\nresponse_format="json_object"\n'
        "max_completion_tokens=4096\n",
    )
    calls: list[dict[str, object]] = []
    sentinel = object()

    def factory(**kwargs: object) -> object:
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(club_news_provider, "OpenAIClubNewsProvider", factory)
    provider, config = club_news_provider.build_coding_provider({}, settings_file=path)
    assert provider is sentinel
    assert calls == [
        {
            "api_key": SECRET,
            "model_identifier": "chosen-model",
            "base_url": "https://compatible.example/v1",
            "response_format": "json_object",
            "max_completion_tokens": 4096,
            "allow_local_http": False,
            "target_context": None,
        }
    ]
    assert SECRET not in repr(config)
