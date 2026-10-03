"""The club-news coding configuration, one question at a time.

Which source wins for each setting, what may follow an override to another destination, what a
changed model does to the record, what the offline check explains, which settings are refused
rather than quietly dropped, where the call ceiling is bounded, what a failure may print, and
what makes two coding requests the same request.

Offline throughout. Every environment is a mapping handed in, every key is a synthetic
sentinel, the opener, the clock and the provider are injected, and every write is under
``tmp_path``.
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.test_club_news_acquire import _Provider
from tests.unit.test_club_news_observation_clock import (
    _Clock,
    _command,
    _opener,
    _roster_snapshot,
    _text,
)
from tests.unit.test_club_news_settings import settings

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    ClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import read_captured_responses
from squadopt.data.sources.club_news_coding import CODING_MODEL_IDENTIFIER, coding_prompt_sha256
from squadopt.platform import club_news_acquire, club_news_provider
from squadopt.platform.club_news_acquire import main
from squadopt.platform.club_news_gemini import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_PROVIDER,
    KEY_HEADER,
    GeminiClubNewsProvider,
)
from squadopt.platform.club_news_model import AnthropicClubNewsProvider
from squadopt.platform.club_news_openai import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_OPENAI_BASE_URL,
    OpenAIClubNewsProvider,
)
from squadopt.platform.club_news_provider import (
    BASE_URL_ENVIRONMENT_VARIABLE,
    DEFAULT_PROVIDER,
    FORMAT_ENVIRONMENT_VARIABLE,
    KEY_ENVIRONMENT_VARIABLE,
    LOCAL_HTTP_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    TOKENS_ENVIRONMENT_VARIABLE,
    CodingProviderConfig,
    check_coding_provider,
    coding_input_fingerprint,
    register_provider,
    resolve_provider_config,
)

#: Synthetic sentinels. Neither is a credential for anything.
FILE_KEY = "matrix-file-key-sentinel-0001"
OTHER_KEY = "matrix-other-key-sentinel-0002"

FILE_URL = "https://file.example/v1"
OTHER_URL = "https://environment.example/v1"
OPENAI_ONLY = "apply only to OpenAI adapters"

#: Header names and schemes a credential travels under. None belongs in printed output.
HEADER_WORDS = ("authorization", "x-api-key", "bearer", KEY_HEADER.lower())


# --- A. precedence -----------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "environ", "field", "expected"),
    [
        pytest.param(
            f'provider="gemini"\napi_key="{FILE_KEY}"\n',
            {PROVIDER_ENVIRONMENT_VARIABLE: DEFAULT_PROVIDER, "ANTHROPIC_API_KEY": OTHER_KEY},
            "provider",
            DEFAULT_PROVIDER,
            id="provider",
        ),
        pytest.param(
            f'provider="openai"\nmodel="file-model"\napi_key="{FILE_KEY}"\n',
            {MODEL_ENVIRONMENT_VARIABLE: "environment-model"},
            "model_identifier",
            "environment-model",
            id="model",
        ),
        pytest.param(
            f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
            f'base_url="{FILE_URL}"\n',
            {
                BASE_URL_ENVIRONMENT_VARIABLE: OTHER_URL,
                MODEL_ENVIRONMENT_VARIABLE: "environment-model",
                KEY_ENVIRONMENT_VARIABLE: OTHER_KEY,
            },
            "base_url",
            OTHER_URL,
            id="base_url",
        ),
        pytest.param(
            f'provider="openai"\nmodel="file-model"\napi_key="{FILE_KEY}"\n',
            {KEY_ENVIRONMENT_VARIABLE: OTHER_KEY},
            "api_key",
            OTHER_KEY,
            id="key",
        ),
    ],
)
def test_the_environment_beats_the_settings_file(
    tmp_path: Path, body: str, environ: dict[str, str], field: str, expected: str
) -> None:
    """A variable set in the shell is the operator's latest word for that setting.

    If this failed, a run started with an explicit variable would use the value in the file.
    """

    config = resolve_provider_config(environ, settings_file=settings(tmp_path, body))

    assert getattr(config, field) == expected


@pytest.mark.parametrize(
    ("body", "environ", "field", "expected", "default"),
    [
        pytest.param(
            f'provider="gemini"\napi_key="{FILE_KEY}"\n',
            {},
            "provider",
            GEMINI_PROVIDER,
            DEFAULT_PROVIDER,
            id="provider",
        ),
        pytest.param(
            f'provider="gemini"\nmodel="gemini-3.8-flash"\napi_key="{FILE_KEY}"\n',
            {},
            "model_identifier",
            "gemini-3.8-flash",
            DEFAULT_GEMINI_MODEL,
            id="model",
        ),
        pytest.param(
            f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
            f'base_url="{FILE_URL}"\n',
            {},
            "base_url",
            FILE_URL,
            DEFAULT_OPENAI_BASE_URL,
            id="base_url",
        ),
        pytest.param(
            f'provider="gemini"\napi_key="{FILE_KEY}"\n',
            {"GEMINI_API_KEY": OTHER_KEY},
            "api_key",
            FILE_KEY,
            OTHER_KEY,
            id="key",
        ),
    ],
)
def test_the_settings_file_beats_the_provider_default(
    tmp_path: Path, body: str, environ: dict[str, str], field: str, expected: str, default: str
) -> None:
    """What the file names is used in place of what would apply with no file.

    If this failed, a private settings file would be read and then ignored for that setting.
    For the key, the default is the vendor's own variable, which the file's key outranks.
    """

    config = resolve_provider_config(environ, settings_file=settings(tmp_path, body))

    assert expected != default
    assert getattr(config, field) == expected


def test_the_default_stands_when_neither_source_names_the_setting(tmp_path: Path) -> None:
    """With nothing said, each setting falls to its declared default and not to a guess.

    If this failed, an unconfigured setting would resolve to something no source declared.
    """

    unconfigured = resolve_provider_config({"ANTHROPIC_API_KEY": OTHER_KEY})
    assert unconfigured.provider == DEFAULT_PROVIDER
    assert unconfigured.model_identifier == CODING_MODEL_IDENTIFIER
    assert unconfigured.base_url is None

    free = resolve_provider_config(
        {"GEMINI_API_KEY": OTHER_KEY}, settings_file=settings(tmp_path, 'provider="gemini"\n')
    )
    assert free.model_identifier == DEFAULT_GEMINI_MODEL
    assert free.api_key == OTHER_KEY

    official = resolve_provider_config(
        {},
        settings_file=settings(
            tmp_path, f'provider="openai"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
        ),
    )
    assert official.base_url == DEFAULT_OPENAI_BASE_URL


def test_the_official_address_is_the_only_one_the_openai_provider_accepts(
    tmp_path: Path,
) -> None:
    """The address default exists for ``openai`` alone, and a file cannot replace it there.

    If this failed, a custom endpoint could be reached under the official provider's name. A
    file naming another address must select ``openai-compatible``, which has no default.
    """

    custom = settings(
        tmp_path,
        f'provider="openai"\nmodel="file-model"\napi_key="{FILE_KEY}"\nbase_url="{FILE_URL}"\n',
    )
    with pytest.raises(ClubNewsError, match="Use openai-compatible") as refusal:
        resolve_provider_config({}, settings_file=custom)
    assert FILE_KEY not in str(refusal.value)

    missing = settings(
        tmp_path, f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
    )
    with pytest.raises(ClubNewsError, match="requires an explicit base_url"):
        resolve_provider_config({}, settings_file=missing)


def test_an_environment_base_url_beats_the_file_base_url_for_the_same_provider(
    tmp_path: Path,
) -> None:
    """Same provider in both places, two addresses: the environment's is the one asked.

    If this failed, a run pointed at another endpoint by variable would still call the file's.
    """

    path = settings(
        tmp_path,
        f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
        f'base_url="{FILE_URL}"\n',
    )
    assert resolve_provider_config({}, settings_file=path).base_url == FILE_URL

    config = resolve_provider_config(
        {
            BASE_URL_ENVIRONMENT_VARIABLE: OTHER_URL,
            MODEL_ENVIRONMENT_VARIABLE: "environment-model",
            KEY_ENVIRONMENT_VARIABLE: OTHER_KEY,
        },
        settings_file=path,
    )

    assert config.provider == "openai-compatible"
    assert config.base_url == OTHER_URL


# --- B. nothing bound to the file's destination follows an override ----------

_OPENAI_FILE = f'provider="openai"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
_COMPATIBLE_FILE = (
    f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
    f'base_url="{FILE_URL}"\nresponse_format="json_object"\nmax_completion_tokens=4096\n'
    "allow_local_http=true\n"
)
_LOOPBACK_FILE = (
    f'provider="openai-compatible"\nmodel="file-model"\napi_key="{FILE_KEY}"\n'
    'base_url="http://127.0.0.1:9000/v1"\nallow_local_http=true\n'
)
_SAME_ADDRESS_OTHER_PROVIDER = {
    PROVIDER_ENVIRONMENT_VARIABLE: "openai-compatible",
    BASE_URL_ENVIRONMENT_VARIABLE: DEFAULT_OPENAI_BASE_URL,
}


@pytest.mark.parametrize(
    ("body", "environ", "refusal"),
    [
        pytest.param(
            'provider="gemini"\napi_key_env="MY_NEWS_KEY"\n',
            {PROVIDER_ENVIRONMENT_VARIABLE: DEFAULT_PROVIDER, "MY_NEWS_KEY": FILE_KEY},
            "ANTHROPIC_API_KEY\\) is unset",
            id="provider-override-with-the-referenced-variable-set",
        ),
        pytest.param(
            'provider="openai-compatible"\nmodel="file-model"\napi_key_env="MY_NEWS_KEY"\n'
            f'base_url="{FILE_URL}"\n',
            {
                BASE_URL_ENVIRONMENT_VARIABLE: OTHER_URL,
                MODEL_ENVIRONMENT_VARIABLE: "environment-model",
                "MY_NEWS_KEY": FILE_KEY,
            },
            "SQUADOPT_LLM_API_KEY is unset",
            id="address-override-with-the-referenced-variable-set",
        ),
        pytest.param(
            _OPENAI_FILE,
            _SAME_ADDRESS_OTHER_PROVIDER,
            "declares no default model",
            id="official-address-under-the-compatible-name-drops-the-model",
        ),
        pytest.param(
            _OPENAI_FILE,
            {**_SAME_ADDRESS_OTHER_PROVIDER, MODEL_ENVIRONMENT_VARIABLE: "environment-model"},
            "SQUADOPT_LLM_API_KEY is unset",
            id="official-address-under-the-compatible-name-drops-the-key",
        ),
        pytest.param(
            'provider="openai"\nmodel="file-model"\napi_key_env="OPENAI_API_KEY"\n',
            {
                **_SAME_ADDRESS_OTHER_PROVIDER,
                MODEL_ENVIRONMENT_VARIABLE: "environment-model",
                "OPENAI_API_KEY": FILE_KEY,
            },
            "SQUADOPT_LLM_API_KEY is unset",
            id="official-address-under-the-compatible-name-drops-the-vendor-key",
        ),
        pytest.param(
            _LOOPBACK_FILE,
            {
                BASE_URL_ENVIRONMENT_VARIABLE: "http://localhost:9001/v1",
                MODEL_ENVIRONMENT_VARIABLE: "environment-model",
                KEY_ENVIRONMENT_VARIABLE: OTHER_KEY,
            },
            "HTTP requires explicit permission",
            id="local-http-permission-is-not-carried",
        ),
    ],
)
def test_an_override_without_its_own_settings_is_refused_and_never_quotes_the_file_key(
    tmp_path: Path, body: str, environ: dict[str, str], refusal: str
) -> None:
    """The file's key, model and permissions belong to the file's destination only.

    If this failed, a credential or permission written for one destination would be used at
    another, or the refusal would print the key it declined to send.
    """

    with pytest.raises(ClubNewsError, match=refusal) as refused:
        resolve_provider_config(environ, settings_file=settings(tmp_path, body))

    assert FILE_KEY not in str(refused.value)


def test_the_official_address_under_the_compatible_name_is_a_different_destination(
    tmp_path: Path,
) -> None:
    """A destination is the provider name and the address together, not the address alone.

    If this failed, a key filed for ``openai`` would be sent on a request built by the
    ``openai-compatible`` selection without the operator having supplied one for it.
    """

    path = settings(
        tmp_path,
        _OPENAI_FILE + 'response_format="json_object"\nmax_completion_tokens=4096\n',
    )
    carried = resolve_provider_config({}, settings_file=path)
    assert (carried.api_key, carried.response_format, carried.max_completion_tokens) == (
        FILE_KEY,
        "json_object",
        4096,
    )

    config = resolve_provider_config(
        {
            **_SAME_ADDRESS_OTHER_PROVIDER,
            MODEL_ENVIRONMENT_VARIABLE: "environment-model",
            KEY_ENVIRONMENT_VARIABLE: OTHER_KEY,
        },
        settings_file=path,
    )

    assert config.provider == "openai-compatible"
    assert config.base_url == DEFAULT_OPENAI_BASE_URL
    assert config.api_key == OTHER_KEY
    assert config.model_identifier == "environment-model"
    assert config.response_format == "json_schema"
    assert config.max_completion_tokens == DEFAULT_MAX_COMPLETION_TOKENS


@pytest.mark.parametrize(
    ("environ", "provider", "base_url"),
    [
        pytest.param(
            {
                BASE_URL_ENVIRONMENT_VARIABLE: OTHER_URL,
                MODEL_ENVIRONMENT_VARIABLE: "environment-model",
                KEY_ENVIRONMENT_VARIABLE: OTHER_KEY,
            },
            "openai-compatible",
            OTHER_URL,
            id="another-address",
        ),
        pytest.param(
            {PROVIDER_ENVIRONMENT_VARIABLE: DEFAULT_PROVIDER, "ANTHROPIC_API_KEY": OTHER_KEY},
            DEFAULT_PROVIDER,
            None,
            id="another-provider",
        ),
    ],
)
def test_request_settings_do_not_follow_a_destination_change(
    tmp_path: Path, environ: dict[str, str], provider: str, base_url: str | None
) -> None:
    """Response format, token limit and local HTTP permission stay with the file's endpoint.

    If this failed, a request to a new destination would be shaped by, or refused for,
    settings the operator wrote for a different one.
    """

    path = settings(tmp_path, _COMPATIBLE_FILE)
    kept = resolve_provider_config({}, settings_file=path)
    assert (kept.response_format, kept.max_completion_tokens, kept.allow_local_http) == (
        "json_object",
        4096,
        True,
    )

    config = resolve_provider_config(environ, settings_file=path)

    assert (config.provider, config.base_url) == (provider, base_url)
    assert config.api_key == OTHER_KEY
    assert config.model_identifier != "file-model"
    assert config.response_format == "json_schema"
    assert config.max_completion_tokens == DEFAULT_MAX_COMPLETION_TOKENS
    assert config.allow_local_http is False


# --- the command, offline -----------------------------------------------------


def _environment(name: str, model: str = "matrix-model-1") -> dict[str, str]:
    return {
        PROVIDER_ENVIRONMENT_VARIABLE: name,
        MODEL_ENVIRONMENT_VARIABLE: model,
        KEY_ENVIRONMENT_VARIABLE: FILE_KEY,
    }


def _run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    environ: Mapping[str, str],
    *extra: str,
) -> tuple[int, str]:
    """One run of the command on the synthetic week; returns its code and all it printed."""

    roster_id = _roster_snapshot(tmp_path / "snapshots")
    clock = _Clock()
    # Capture completion is its own clock; keep it on this synthetic week's timeline.
    monkeypatch.setattr(
        club_news_acquire,
        "_utc_now",
        lambda: _text(clock.readings[-1] + timedelta(seconds=30)),
    )
    code = main(
        _command(tmp_path, roster_id, *extra),
        environ=environ,
        opener=_opener(None),
        now=clock,
        sleeper=lambda _: None,
    )
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# --- C. a changed model needs no source edit ----------------------------------


@pytest.mark.parametrize("model", ["matrix-configured-model", "vendor/another-model:2"])
def test_the_model_named_in_the_settings_file_is_the_one_asked_and_recorded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    """Editing one line of the private file changes the model and the record follows it.

    If this failed, a capture would name a model other than the one configured, or lose the
    difference between the model asked for and the version that answered.
    """

    served = "matrix-served-revision-007"
    used: list[tuple[str, str]] = []

    class _Configured(_Provider):
        def __init__(self, config: CodingProviderConfig) -> None:
            super().__init__()
            self._asked = config.model_identifier

        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            used.append((self._asked, served))
            return replace(
                super().code(documents, roster),
                model_identifier=self._asked,
                model_version=served,
            )

    name = "matrix-model-change"
    register_provider(name, _Configured)
    private = tmp_path / "private.toml"
    private.write_text(
        f'[llm]\nprovider="{name}"\nmodel="{model}"\napi_key="{FILE_KEY}"\n', encoding="utf-8"
    )

    code, printed = _run(tmp_path, capsys, monkeypatch, {}, "--settings-file", str(private))

    assert code == 0, printed
    assert FILE_KEY not in printed
    capture_id = next(
        line.split()[-1] for line in printed.splitlines() if line.startswith("Capture")
    )
    recorded = read_captured_responses(read_snapshot(tmp_path / "snapshots", capture_id))
    assert [entry.club for entry in recorded] == ["Arsenal", "Man Utd"]
    assert used == [(model, served)] * 2
    assert model != CODING_MODEL_IDENTIFIER
    for entry in recorded:
        assert entry.provider == name
        assert entry.response.model_identifier == model
        assert entry.response.model_version == served
        assert entry.prompt_sha256 == coding_prompt_sha256(model)
        assert entry.prompt_sha256 != coding_prompt_sha256()


# --- D. the offline check explains a bad setting ------------------------------


@pytest.mark.parametrize(
    ("body", "explanation"),
    [
        pytest.param(
            f'provider="openai"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\ntemperature="0"\n',
            "unsupported setting",
            id="unsupported-key",
        ),
        pytest.param(
            f'provider="openai"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\n'
            'max_completion_tokens="4096"\n',
            "wrong type",
            id="token-limit-as-text",
        ),
        pytest.param(
            f'provider="openai"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\n'
            'api_key_env="MY_NEWS_KEY"\n',
            "either api_key or api_key_env",
            id="key-and-key-reference",
        ),
        pytest.param(
            f'provider="openai-compatible"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\n',
            "requires an explicit base_url",
            id="compatible-without-an-address",
        ),
        pytest.param(
            f'provider="gemini"\nmodel="unlisted-model"\napi_key="{FILE_KEY}"\n',
            "'unlisted-model' is not in the provider's model list",
            id="unlisted-gemini-model",
        ),
        pytest.param(
            f'provider="gemini"\napi_key="{FILE_KEY}"\nresponse_format="json_schema"\n',
            OPENAI_ONLY,
            id="response-format-with-gemini",
        ),
    ],
)
def test_check_config_explains_a_bad_setting_without_crossing_any_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    explanation: str,
) -> None:
    """The check reads the settings and nothing else, and says what is wrong with them.

    If this failed, a bad file would pass the check, or the check would read the registry or
    a capture, build a provider, write something, contact a host or print the key.
    """

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("The offline check crossed a boundary.")

    for boundary in (
        "load_club_sources",
        "read_snapshot",
        "bind_coding_provider",
        "write_club_news_capture",
    ):
        monkeypatch.setattr(club_news_acquire, boundary, forbidden)
    path = settings(tmp_path, body)
    before = sorted(str(entry.relative_to(tmp_path)) for entry in tmp_path.rglob("*"))

    code = main(["--settings-file", str(path), "--check-config"], environ={}, opener=forbidden)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.startswith("Refused:")
    assert explanation in captured.out
    assert "Configuration valid" not in captured.out
    assert FILE_KEY not in captured.out + captured.err
    assert sorted(str(entry.relative_to(tmp_path)) for entry in tmp_path.rglob("*")) == before


def test_check_config_states_the_provider_the_model_and_the_request_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid file is confirmed with the settings that will shape the request.

    If this failed, an operator could not see from the check which model, response format
    and completion token limit the next run would ask with.
    """

    monkeypatch.setattr(club_news_provider.importlib.util, "find_spec", lambda _name: object())
    path = settings(
        tmp_path,
        f'provider="openai"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\n'
        'response_format="json_object"\nmax_completion_tokens=4096\n',
    )

    code = main(["--settings-file", str(path), "--check-config"], environ={})

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert "Configuration valid: provider 'openai', model 'chosen-model'." in lines
    assert "Response format 'json_object', completion token limit 4096." in lines
    assert not any(FILE_KEY in line for line in lines)


# --- E. no silent format or vendor fallback -----------------------------------

_OPENAI_ONLY_SETTINGS = {
    "response_format": (
        'response_format="json_schema"\n',
        FORMAT_ENVIRONMENT_VARIABLE,
        "json_schema",
    ),
    "base_url": (f'base_url="{FILE_URL}"\n', BASE_URL_ENVIRONMENT_VARIABLE, FILE_URL),
    "max_completion_tokens": ("max_completion_tokens=4096\n", TOKENS_ENVIRONMENT_VARIABLE, "4096"),
    "allow_local_http": ("allow_local_http=false\n", LOCAL_HTTP_ENVIRONMENT_VARIABLE, "false"),
}


@pytest.mark.parametrize("source", ["file", "environment"])
@pytest.mark.parametrize("setting", sorted(_OPENAI_ONLY_SETTINGS))
@pytest.mark.parametrize("provider", [DEFAULT_PROVIDER, GEMINI_PROVIDER])
def test_an_openai_request_setting_with_another_adapter_is_refused(
    tmp_path: Path, provider: str, setting: str, source: str
) -> None:
    """A setting the selected adapter cannot honour is refused, never dropped in silence.

    If this failed, an operator who asked for a response format, an address or a token limit
    would get a run that ignored it and recorded nothing about the difference.
    """

    line, variable, value = _OPENAI_ONLY_SETTINGS[setting]
    body = f'provider="{provider}"\napi_key="{FILE_KEY}"\n'
    # Without the setting the same selection resolves, so the setting is what is refused.
    assert resolve_provider_config({}, settings_file=settings(tmp_path, body)).provider == provider
    environ = {variable: value} if source == "environment" else {}
    path = settings(tmp_path, body + line if source == "file" else body)

    with pytest.raises(ClubNewsError, match=OPENAI_ONLY) as refusal:
        resolve_provider_config(environ, settings_file=path)

    assert FILE_KEY not in str(refusal.value)


@pytest.mark.parametrize("provider", ["openai", "openai-compatible"])
def test_an_unknown_response_format_is_refused_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """Only the two declared formats exist; anything else stops at configuration.

    If this failed, a mistyped format would reach the endpoint, or be replaced by a default
    the operator did not choose.
    """

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("A refused configuration built a provider.")

    monkeypatch.setattr(club_news_provider, "OpenAIClubNewsProvider", forbidden)
    address = f'base_url="{FILE_URL}"\n' if provider == "openai-compatible" else ""
    path = settings(
        tmp_path,
        f'provider="{provider}"\nmodel="chosen-model"\napi_key="{FILE_KEY}"\n{address}'
        'response_format="markdown"\n',
    )

    for resolve in (resolve_provider_config, check_coding_provider):
        with pytest.raises(ClubNewsError, match="json_schema or json_object") as refusal:
            resolve({}, settings_file=path)
        assert FILE_KEY not in str(refusal.value)


# --- F. the declared ceiling ---------------------------------------------------


@pytest.mark.parametrize("value", ["-1", "21"])
def test_a_call_ceiling_outside_zero_to_twenty_stops_the_command(
    capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """The ceiling is bounded where it is declared, before anything else is read.

    If this failed, a mistyped ceiling could authorise more paid requests than the command
    says it allows.
    """

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("A refused ceiling still reached a host.")

    with pytest.raises(SystemExit) as stopped:
        main(["--check-config", "--max-model-calls", value], environ={}, opener=forbidden)

    assert stopped.value.code == 2
    assert "--max-model-calls must be between zero and twenty" in capsys.readouterr().err


@pytest.mark.parametrize("value", [0, 20])
def test_the_two_ends_of_the_call_ceiling_are_accepted(value: int) -> None:
    """Zero and twenty are inside the range the help text states.

    If this failed, a run could not be limited to no calls at all, or to the stated maximum.
    """

    arguments = club_news_acquire._parse_arguments(
        ["--check-config", "--max-model-calls", str(value)]
    )

    assert arguments.max_model_calls == value


def test_a_ceiling_of_zero_given_to_the_command_sends_no_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The option reaches the coding stage, which stops before the provider is called.

    If this failed, the declared ceiling would be parsed and then not applied.
    """

    class _NeverAsked(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            raise AssertionError("A request was sent past a ceiling of zero.")

    name = "matrix-zero-ceiling"
    register_provider(name, lambda config: _NeverAsked())

    code, printed = _run(
        tmp_path, capsys, monkeypatch, _environment(name), "--max-model-calls", "0"
    )

    assert code == 1
    assert "Call budget   0; 0 attempted; no automatic provider retry" in printed
    assert "Call budget exhausted; no model request was sent." in printed
    assert "Nothing was coded, so there is no week to capture." in printed


# --- G. a failure never prints the key ----------------------------------------


def _assert_nothing_secret(printed: str) -> None:
    assert FILE_KEY not in printed
    lowered = printed.lower()
    assert [word for word in HEADER_WORDS if word in lowered] == []


@pytest.mark.parametrize(
    "message",
    [
        pytest.param("The request did not complete (ReadTimeout).", id="timeout"),
        pytest.param("Coding response exceeds the byte limit.", id="oversized-response"),
        pytest.param("The coding endpoint did not return valid JSON.", id="malformed-json"),
        pytest.param("The model declined the coding request.", id="refusal"),
    ],
)
def test_a_failed_call_is_reported_by_its_reason_and_nothing_else(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    """What the command prints for a failed club is the provider's reason, as given.

    If this failed, the command would be adding the key, or a header that carries it, to
    the report of a failure.
    """

    class _Failing(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            raise ClubNewsError(message)

    name = "matrix-failing-provider"
    register_provider(name, lambda config: _Failing())

    code, printed = _run(tmp_path, capsys, monkeypatch, _environment(name))

    assert code == 1
    assert f"  refused     Arsenal: {message}" in printed
    assert f"  refused     Man Utd: {message}" in printed
    assert "Call budget   3; 2 attempted" in printed
    _assert_nothing_secret(printed)


class _RaisingTransport:
    """A transport, or an SDK client, whose one request raises what a test decides."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def post(self, url: str, **_: object) -> Any:
        raise self._error

    @property
    def messages(self) -> "_RaisingTransport":
        return self

    def create(self, **_: object) -> Any:
        raise self._error


class _SdkError(Exception):
    """Stands in for the SDK's own error type, so no SDK is needed to raise one."""

    status_code = 401


def _openai_adapter(config: CodingProviderConfig, error: Exception) -> ClubNewsProvider:
    return OpenAIClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
        transport=_RaisingTransport(error),
    )


def _gemini_adapter(config: CodingProviderConfig, error: Exception) -> ClubNewsProvider:
    return GeminiClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
        transport=_RaisingTransport(error),
    )


def _anthropic_adapter(config: CodingProviderConfig, error: Exception) -> ClubNewsProvider:
    return AnthropicClubNewsProvider(
        client=_RaisingTransport(error),
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
    )


def _library_error(adapter: str, text: str) -> Exception:
    """The failure each adapter's own client library raises, carrying ``text``."""

    if adapter == "gemini":
        import httpx2

        return httpx2.ConnectTimeout(text)
    if adapter == "anthropic":
        return _SdkError(text)
    return RuntimeError(text)


_ADAPTERS: dict[str, Callable[[CodingProviderConfig, Exception], ClubNewsProvider]] = {
    "openai": _openai_adapter,
    "gemini": _gemini_adapter,
    "anthropic": _anthropic_adapter,
}


@pytest.mark.parametrize(
    ("adapter", "kind"),
    [
        pytest.param("openai", "library", id="openai-library-error"),
        pytest.param("gemini", "library", id="gemini-library-error"),
        pytest.param("anthropic", "library", id="anthropic-library-error"),
        pytest.param("openai", "other", id="openai-other-error"),
        # Two adapters catch only their client library's own error type. An error of
        # another type leaves them with its message intact, and the coding stage is what
        # keeps it from the output: it names the type and withholds the message.
        pytest.param("gemini", "other", id="gemini-other-error"),
        pytest.param("anthropic", "other", id="anthropic-other-error"),
    ],
)
def test_a_transport_failure_that_quotes_the_key_does_not_reach_the_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    adapter: str,
    kind: str,
) -> None:
    """Each real adapter, with a transport whose error text holds the key and its header.

    If this failed, one club's connection error would write the credential into the run's
    output. The adapters' own tests cover the library error at the adapter; this is the same
    failure, and one of another type, followed to what the command prints.
    """

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(APIError=_SdkError))
    text = f"request with Authorization: Bearer {FILE_KEY} and x-api-key: {FILE_KEY} failed"
    error = _library_error(adapter, text) if kind == "library" else OSError(text)
    name = f"matrix-raising-{adapter}"
    register_provider(name, lambda config: _ADAPTERS[adapter](config, error))
    model = DEFAULT_GEMINI_MODEL if adapter == "gemini" else "matrix-model-1"

    code, printed = _run(tmp_path, capsys, monkeypatch, _environment(name, model))

    assert code == 1
    _assert_nothing_secret(printed)
    # One club's call each, not the week: both clubs are named with their own refusal.
    assert "  refused     Arsenal: " in printed
    assert "  refused     Man Utd: " in printed
    assert not printed.startswith("Refused:")


# --- H. what makes two coding requests the same request -----------------------

_TARGET: dict[str, object] = {
    "season": "2026-27",
    "gameweek": 6,
    "deadline": "2026-10-10T10:00:00Z",
    "as_of": "2026-10-02T00:00:00Z",
}
_CONFIG = CodingProviderConfig(
    provider="openai-compatible",
    model_identifier="matrix-model-1",
    api_key=FILE_KEY,
    base_url=FILE_URL,
    response_format="json_schema",
    max_completion_tokens=4096,
    target_context=_TARGET,
)
_CONTENT = b"<p>Saka trained fully.</p>"
_DOCUMENT = RawDocument(
    club="Arsenal",
    requested_url="https://club.example/arsenal/team-news",
    final_url="https://club.example/arsenal/team-news",
    http_status=200,
    content_type="text/html; charset=utf-8",
    byte_length=len(_CONTENT),
    fetched_at_utc="2026-10-01T10:00:00Z",
    content=_CONTENT,
    readable=b"Saka trained fully.",
    last_modified_utc="2026-10-01T09:00:00Z",
)
_ROSTER = (RosterPlayer(player_id=1, web_name="Saka", team_name="Arsenal"),)

_Change = Callable[[CodingProviderConfig, RawDocument], tuple[CodingProviderConfig, RawDocument]]


def _target(**changed: object) -> _Change:
    return lambda config, document: (
        replace(config, target_context={**_TARGET, **changed}),
        document,
    )


def _configured(**changed: Any) -> _Change:
    return lambda config, document: (replace(config, **changed), document)


def _fetched(**changed: Any) -> _Change:
    return lambda config, document: (config, replace(document, **changed))


_CHANGED_CONTENT = b"<p>Saka trained alone.</p>"
_NEW_QUESTION: dict[str, _Change] = {
    "content-bytes-at-the-same-url": _fetched(
        content=_CHANGED_CONTENT, byte_length=len(_CHANGED_CONTENT)
    ),
    "readable-bytes-at-the-same-url": _fetched(readable=b"Saka trained alone."),
    "last-modified": _fetched(last_modified_utc="2026-10-01T09:30:00Z"),
    "last-modified-absent": _fetched(last_modified_utc=None),
    "deadline": _target(deadline="2026-10-10T11:00:00Z"),
    "season": _target(season="2025-26"),
    "gameweek": _target(gameweek=7),
    "base-url": _configured(base_url=OTHER_URL),
    "completion-token-limit": _configured(max_completion_tokens=4097),
    "response-format": _configured(response_format="json_object"),
    "model": _configured(model_identifier="matrix-model-2"),
    "provider": _configured(provider="openai"),
}
_SAME_QUESTION: dict[str, _Change] = {
    "as-of": _target(as_of="2026-10-02T01:00:00Z"),
    "fetched-at": _fetched(fetched_at_utc="2026-10-01T11:00:00Z"),
}


def _fingerprint(change: _Change | None = None) -> str:
    config, document = (_CONFIG, _DOCUMENT) if change is None else change(_CONFIG, _DOCUMENT)
    return coding_input_fingerprint(config, (document,), _ROSTER)


@pytest.mark.parametrize("changed", sorted(_NEW_QUESTION))
def test_one_changed_input_is_a_new_coding_request(changed: str) -> None:
    """Source bytes, the target and the instrument each decide what was asked.

    If this failed, an answer given for other words, another week or another instrument
    would be reused as though it answered this request.
    """

    assert _fingerprint(_NEW_QUESTION[changed]) != _fingerprint()


@pytest.mark.parametrize("changed", sorted(_SAME_QUESTION))
def test_a_later_look_at_the_same_inputs_is_the_same_coding_request(changed: str) -> None:
    """When the run looked, and when a page was read, are clocks and not content.

    If this failed, every later run of an unchanged week would pay for the same answer again.
    """

    assert _fingerprint(_SAME_QUESTION[changed]) == _fingerprint()
