"""Private club-news settings; parsing never imports a client or accesses a network."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from squadopt.data.sources.club_news import ClubNewsError
from squadopt.platform.club_news_openai import validate_openai_configuration

_PREFIX = "SQUADOPT_LLM_"
_FIELDS = {
    "provider": "PROVIDER",
    "model": "MODEL",
    "api_key": "API_KEY",
    "base_url": "BASE_URL",
    "response_format": "RESPONSE_FORMAT",
    "max_completion_tokens": "MAX_COMPLETION_TOKENS",
    "allow_local_http": "ALLOW_LOCAL_HTTP",
}
_VENDOR_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _read(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        # Parser errors can quote the line containing a secret.
        raise ClubNewsError("The private settings file is unreadable or invalid TOML.") from None
    if set(document) != {"llm"} or not isinstance(document["llm"], dict):
        raise ClubNewsError("Private settings must contain exactly one [llm] table.")
    values: dict[str, object] = document["llm"]
    unsupported = set(values) - {*_FIELDS, "api_key_env"}
    if unsupported:
        field = sorted(unsupported)[0]
        raise ClubNewsError(f"The [llm] table has an unsupported setting {field!r}.")
    if not isinstance(values.get("provider"), str) or not str(values["provider"]).strip():
        raise ClubNewsError("The [llm] table must explicitly name its provider.")
    for field, value in values.items():
        if field == "max_completion_tokens":
            valid = type(value) is int
        elif field == "allow_local_http":
            valid = type(value) is bool
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise ClubNewsError(f"The [llm] setting {field!r} has the wrong type or is empty.")
    if "api_key" in values and "api_key_env" in values:
        raise ClubNewsError("Choose either api_key or api_key_env in [llm], not both.")
    reference = values.get("api_key_env")
    if reference is not None and (
        not isinstance(reference, str) or not _ENV_NAME.fullmatch(reference)
    ):
        raise ClubNewsError("api_key_env must name one environment variable.")
    for provider, variable in _VENDOR_KEYS.items():
        if reference == variable and values["provider"] != provider:
            raise ClubNewsError("api_key_env names a different provider's credential.")
    return values


def _destination(provider: str, base_url: str) -> tuple[str, str]:
    default = "https://api.openai.com/v1" if provider == "openai" else ""
    endpoint = base_url.strip() or default
    if provider in {"openai", "openai-compatible"} and endpoint:
        # This compares destinations only. The effective local HTTP permission is
        # checked separately before the provider can be built or used.
        endpoint = validate_openai_configuration(
            model_identifier="configuration-binding", base_url=endpoint, allow_local_http=True
        )
    return provider, endpoint.rstrip("/")


def configured_environment(path: Path | None, environ: Mapping[str, str]) -> dict[str, str]:
    """Apply file defaults without changing os.environ or crossing key destinations."""
    source = dict(environ)
    if path is None:
        return source
    values = _read(path)
    file_provider = str(values["provider"]).strip()
    provider = source.get(_PREFIX + "PROVIDER", "").strip() or file_provider
    file_base = str(values.get("base_url", "")).strip()
    base = source.get(_PREFIX + "BASE_URL", "").strip()
    if not base and provider == file_provider:
        base = file_base
    same_destination = _destination(provider, base) == _destination(file_provider, file_base)
    source[_PREFIX + "PROVIDER"] = provider
    if base:
        source[_PREFIX + "BASE_URL"] = base
    for field, suffix in _FIELDS.items():
        if field in {"provider", "base_url", "api_key"}:
            continue
        if same_destination and field in values and not source.get(_PREFIX + suffix, "").strip():
            value = values[field]
            source[_PREFIX + suffix] = (
                str(value).lower() if isinstance(value, bool) else str(value).strip()
            )
    if not source.get(_PREFIX + "API_KEY", "").strip() and same_destination:
        if "api_key_env" in values:
            key = source.get(str(values["api_key_env"]), "").strip()
            if not key:
                raise ClubNewsError("The environment variable named by api_key_env is unset.")
            source[_PREFIX + "API_KEY"] = key
        elif "api_key" in values:
            source[_PREFIX + "API_KEY"] = str(values["api_key"]).strip()
    return source
