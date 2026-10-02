"""Which model codes a week's club news, decided by configuration rather than by an import.

The port itself was never the problem. ``ClubNewsProvider`` already speaks the domain's
vocabulary -- ``fetch(url)`` and ``code(documents, roster) -> ClaimResponse`` -- and names no
vendor. What named one was everything around it: a key read from ``ANTHROPIC_API_KEY``, a model
identifier frozen into the coding contract at the request site and again at the record site,
and a client protocol shaped like one SDK's ``messages.create``.

This module is the one place that decides. It reads three variables, none of which contains a
vendor's name, and returns the provider they select:

``SQUADOPT_LLM_PROVIDER``
    Which adapter. The default is the only one installed today, so a checkout behaves as it
    did before this module existed.
``SQUADOPT_LLM_MODEL``
    Which model that adapter should ask. Optional: each adapter names its own default, and the
    coding contract's model stays the default for the vendor it was written against.
``SQUADOPT_LLM_API_KEY``
    The key. A vendor's own variable is still read as a **compatibility path** -- an operator
    with ``ANTHROPIC_API_KEY`` already exported is not asked to rename it -- but the generic
    one wins where both are set, because the contract is the generic one and the vendor one is
    the courtesy.

**Genericity is about wiring, never about blurring a record.** Whatever model answered goes
into the manifest exactly as it was asked for, and
:func:`~squadopt.data.sources.club_news_coding.coding_prompt_sha256` takes the identifier as an
argument for the same reason it always folded the constant in: the same words put to a
different model are a different question, so a week coded by one model and a week coded by
another must stay distinguishable forever.

**A missing key is loud.** There is no fall back to the fixture. "We could not ask" and "the
fixture said" are different facts, and the lane spends a lot of effort keeping facts like those
apart; a convenience default here would undo it in one line.
"""

import hashlib
import importlib.util
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Final

from squadopt.data.sources.club_news import (
    ClubNewsError,
    ClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import CodedClub
from squadopt.data.sources.club_news_coding import (
    CODING_MODEL_IDENTIFIER,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    build_user_content,
    coding_prompt_sha256,
    require_requested_coding_contract,
)
from squadopt.data.sources.club_news_selection import (
    SELECTION_POLICY_VERSION,
    DocumentSelection,
    select_coding_documents,
)

# Eager, and the laziness that matters is kept where it belongs. Registration needs the name
# when this module is imported, so deferring the class while importing its constants would
# defer nothing; the adapter's own heavy import, the HTTP client, stays behind a function call.
from squadopt.platform.club_news_gemini import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_PROVIDER,
    GeminiClubNewsProvider,
    validate_gemini_model,
)
from squadopt.platform.club_news_openai import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_OPENAI_BASE_URL,
    OpenAIClubNewsProvider,
    validate_openai_configuration,
)
from squadopt.platform.club_news_settings import configured_environment

#: Which adapter codes the week. No vendor name, by contract.
PROVIDER_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_PROVIDER"

#: Which model that adapter asks. Optional; the adapter's own default stands otherwise.
MODEL_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_MODEL"

#: The key, read from the environment and never committed.
KEY_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_API_KEY"
BASE_URL_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_BASE_URL"
FORMAT_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_RESPONSE_FORMAT"
TOKENS_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_MAX_COMPLETION_TOKENS"
LOCAL_HTTP_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_ALLOW_LOCAL_HTTP"
_OPENAI_PROVIDERS: Final = frozenset({"openai", "openai-compatible"})

#: The provider selected when nothing says otherwise: the adapter the coding contract was
#: written against. A second adapter does not change it, because the model a run asks is
#: recorded forever and an unconfigured run should keep asking the one the contract names.
DEFAULT_PROVIDER: Final = "anthropic"

#: Each adapter's own historical key variable, read only when the generic one is unset. This
#: is a compatibility path and not the contract, which is why it is a lookup rather than a
#: constant: a second adapter adds a row here and changes nothing else.
VENDOR_KEY_VARIABLES: Final[Mapping[str, str]] = {
    "anthropic": "ANTHROPIC_API_KEY",
    GEMINI_PROVIDER: "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class ClubNewsProviderError(ClubNewsError):
    """The configuration does not name a provider that can be built."""


@dataclass(frozen=True, slots=True)
class CodingProviderConfig:
    """What the environment said, resolved once so nothing downstream re-reads it.

    ``api_key`` is here rather than fetched inside the adapter because the refusal for a
    missing key belongs at the moment of configuration, where it can name the variable that
    was empty, rather than halfway through a week's run.
    """

    provider: str
    model_identifier: str
    #: Out of the repr, because a dataclass prints itself into any log line, traceback or
    #: debugger frame that touches it, and the one field here that must never appear in
    #: one is this.
    api_key: str = field(repr=False)
    base_url: str | None = None
    response_format: str = "json_schema"
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    allow_local_http: bool = False
    target_context: Mapping[str, object] | None = None


#: Name -> a factory taking the resolved configuration. A second provider is one entry here
#: and one adapter module; the port, the export, the capture and the contract do not move.
_FACTORIES: Final[dict[str, Callable[[CodingProviderConfig], ClubNewsProvider]]] = {}


def register_provider(
    name: str, factory: Callable[[CodingProviderConfig], ClubNewsProvider]
) -> None:
    """Make ``name`` selectable by configuration.

    Registration is explicit rather than discovered by scanning a package, so the set of
    providers a checkout can reach is a list somebody wrote rather than a consequence of which
    files happen to be importable. A test registers its own fake through this same door, which
    is what makes the rehearsal a rehearsal: the fake is selected by environment variable
    alone, exactly as a real provider would be.
    """

    if not name.strip():
        raise ClubNewsProviderError("A provider needs a name to be selected by.")
    _FACTORIES[name] = factory


def registered_providers() -> tuple[str, ...]:
    """Every selectable provider name, sorted, for a refusal that can list the alternatives."""

    return tuple(sorted(_FACTORIES))


def _read_key(provider: str, source: Mapping[str, str]) -> str:
    """The generic variable, then the vendor's own, then a refusal that names both."""

    key = source.get(KEY_ENVIRONMENT_VARIABLE, "").strip()
    if key:
        return key
    vendor_variable = VENDOR_KEY_VARIABLES.get(provider)
    if vendor_variable is not None:
        key = source.get(vendor_variable, "").strip()
        if key:
            return key
    named = KEY_ENVIRONMENT_VARIABLE
    if vendor_variable is not None:
        named = f"{KEY_ENVIRONMENT_VARIABLE} (or {vendor_variable})"
    raise ClubNewsProviderError(
        f"{named} is unset, so provider {provider!r} cannot be built. The key is read from "
        "the environment and is never committed, so a checkout alone cannot code a week's "
        "club news. There is deliberately no fall back to the fixture: a week nobody could "
        "ask about and a week the fixture answered are different facts."
    )


def resolve_provider_config(
    environ: Mapping[str, str] | None = None,
    *,
    settings_file: Path | None = None,
) -> CodingProviderConfig:
    """Read the three variables, or refuse by name.

    ``environ`` is injectable so tests never touch the real environment, and so the rehearsal
    can select a fake provider by handing in a mapping rather than by editing anything.
    """

    source = configured_environment(settings_file, os.environ if environ is None else environ)
    declared = source.get(PROVIDER_ENVIRONMENT_VARIABLE, "").strip()
    # The generic key carries no vendor, so with no provider line the default is a guess
    # about whose key this is, and the guess is acted on by sending the key to that vendor.
    # A key that reaches the wrong vendor has left this machine before anything can refuse
    # it, and no later check can call it back. The vendor's own variable is a different
    # case: it names its vendor, so the default stays safe and is left alone.
    if not declared and source.get(KEY_ENVIRONMENT_VARIABLE, "").strip():
        raise ClubNewsProviderError(
            f"{KEY_ENVIRONMENT_VARIABLE} is set and {PROVIDER_ENVIRONMENT_VARIABLE} is not, "
            f"so which adapter this key belongs to would be a guess. Unset, the provider is "
            f"{DEFAULT_PROVIDER!r}, and a key sent to the wrong vendor leaves this machine "
            f"before any refusal can reach it. Name the provider in the same shell as the "
            f"key; registered providers: {list(registered_providers())!r}. A vendor's own "
            f"key variable names its vendor and needs no provider line."
        )
    provider = declared or DEFAULT_PROVIDER
    if provider not in _FACTORIES:
        raise ClubNewsProviderError(
            f"{PROVIDER_ENVIRONMENT_VARIABLE} names {provider!r}, which is not registered. "
            f"Registered providers: {list(registered_providers())!r}."
        )
    model = source.get(MODEL_ENVIRONMENT_VARIABLE, "").strip() or _default_model(provider)
    base_url = source.get(BASE_URL_ENVIRONMENT_VARIABLE, "").strip() or None
    response_format = source.get(FORMAT_ENVIRONMENT_VARIABLE, "").strip() or "json_schema"
    tokens = source.get(TOKENS_ENVIRONMENT_VARIABLE, "").strip()
    local_http = source.get(LOCAL_HTTP_ENVIRONMENT_VARIABLE, "").strip().lower()
    option_names = (
        BASE_URL_ENVIRONMENT_VARIABLE,
        FORMAT_ENVIRONMENT_VARIABLE,
        TOKENS_ENVIRONMENT_VARIABLE,
        LOCAL_HTTP_ENVIRONMENT_VARIABLE,
    )
    if provider not in _OPENAI_PROVIDERS and any(
        source.get(name, "").strip() for name in option_names
    ):
        raise ClubNewsProviderError(
            "Endpoint and completion settings apply only to OpenAI adapters."
        )
    if provider == "openai-compatible" and base_url is None:
        raise ClubNewsProviderError("The openai-compatible provider requires an explicit base_url.")
    if provider == "openai" and base_url is None:
        base_url = DEFAULT_OPENAI_BASE_URL
    if tokens and not (tokens.isascii() and tokens.isdecimal()):
        raise ClubNewsProviderError("max_completion_tokens must be a positive integer.")
    if local_http not in ("", "true", "false"):
        raise ClubNewsProviderError("allow_local_http must be true or false.")
    if provider in _OPENAI_PROVIDERS:
        base_url = validate_openai_configuration(
            model_identifier=model,
            base_url=base_url or DEFAULT_OPENAI_BASE_URL,
            response_format=response_format,
            max_completion_tokens=int(tokens) if tokens else DEFAULT_MAX_COMPLETION_TOKENS,
            allow_local_http=local_http == "true",
        )
    if provider == "openai" and base_url != DEFAULT_OPENAI_BASE_URL:
        raise ClubNewsProviderError(
            "Use openai-compatible for an explicitly configured custom endpoint."
        )
    return CodingProviderConfig(
        provider=provider,
        model_identifier=model,
        api_key=_read_key(provider, source),
        base_url=base_url,
        response_format=response_format,
        max_completion_tokens=int(tokens) if tokens else DEFAULT_MAX_COMPLETION_TOKENS,
        allow_local_http=local_http == "true",
    )


def _default_model(provider: str) -> str:
    """The model an adapter asks when the environment does not say.

    Two providers declare one. The contract's own vendor defaults to the identifier that is
    part of the frozen prompt's fingerprint, so an unconfigured run keeps producing exactly the
    digest the contract describes. The free adapter declares the model its free tier serves,
    which is what lets an operator select it with one variable instead of two. Any other
    provider must be told, because there is no model this repository has declared for it, and a
    guessed identifier would be recorded as though it had been chosen.
    """

    if provider == DEFAULT_PROVIDER:
        return CODING_MODEL_IDENTIFIER
    if provider == GEMINI_PROVIDER:
        return DEFAULT_GEMINI_MODEL
    raise ClubNewsProviderError(
        f"{MODEL_ENVIRONMENT_VARIABLE} is unset and provider {provider!r} declares no default "
        "model. Name the model: which one answered is recorded forever, so it is not a thing "
        "to guess."
    )


def validate_provider_config(config: CodingProviderConfig) -> None:
    """Validate local settings without constructing an SDK or HTTP client."""
    if not re.fullmatch(r"[\x21-\x7e]+", config.api_key):
        raise ClubNewsProviderError("The API key must be a single printable token.")
    if config.provider == GEMINI_PROVIDER:
        validate_gemini_model(config.model_identifier)
    elif config.provider in _OPENAI_PROVIDERS:
        validate_openai_configuration(
            model_identifier=config.model_identifier,
            base_url=config.base_url or DEFAULT_OPENAI_BASE_URL,
            response_format=config.response_format,
            max_completion_tokens=config.max_completion_tokens,
            allow_local_http=config.allow_local_http,
        )
    elif not re.fullmatch(r"[A-Za-z0-9._:/-]+", config.model_identifier):
        raise ClubNewsProviderError("The configured model identifier is invalid.")


def check_coding_provider(
    environ: Mapping[str, str] | None = None, *, settings_file: Path | None = None
) -> CodingProviderConfig:
    """Offline configuration/dependency check; never authenticates or creates a client."""
    config = resolve_provider_config(environ, settings_file=settings_file)
    validate_provider_config(config)
    require_provider_dependency(config)
    return config


def require_provider_dependency(config: CodingProviderConfig) -> None:
    """Refuse a provider whose client library is not installed, without importing it.

    The adapters refuse the same thing when they are built. This is the check for a caller
    that builds its adapter later than it wants the refusal: the acquisition command builds
    after the pages are read, and a missing library is a reason to read none of them.
    """

    dependency = {
        DEFAULT_PROVIDER: "anthropic",
        GEMINI_PROVIDER: "httpx2",
        "openai": "httpx2",
        "openai-compatible": "httpx2",
    }.get(config.provider)
    if dependency and importlib.util.find_spec(dependency) is None:
        raise ClubNewsProviderError(
            "The selected provider needs the project's llm extra installed."
        )


def build_coding_provider(
    environ: Mapping[str, str] | None = None,
    *,
    settings_file: Path | None = None,
    target_context: Mapping[str, object] | None = None,
) -> tuple[ClubNewsProvider, CodingProviderConfig]:
    """The configured provider, and the configuration it was built from.

    Both are returned because the caller needs the second: the capture records which model was
    asked, and reading it back off the adapter would ask the adapter to be honest about itself.
    """

    config = resolve_provider_config(environ, settings_file=settings_file)
    return bind_coding_provider(config, target_context)


def bind_coding_provider(
    config: CodingProviderConfig, target_context: Mapping[str, object] | None
) -> tuple[ClubNewsProvider, CodingProviderConfig]:
    """Build the provider for an already-resolved configuration and one target context.

    Resolution and binding are separate so the acquisition command can refuse a bad
    configuration before any page is fetched and still build the adapter afterwards, once
    the instant the coding observes from is known. The adapter keeps the context it is built
    with, so a provider built before the fetch would tell the model an earlier time than the
    one the documents were selected at.
    """

    config = replace(config, target_context=target_context)
    validate_provider_config(config)
    return _FACTORIES[config.provider](config), config


def coding_as_of(config: CodingProviderConfig) -> str | None:
    """The instant the coding observes from, or ``None`` when no target was declared."""

    if config.target_context and "as_of" in config.target_context:
        return str(config.target_context["as_of"])
    return None


def coding_input_fingerprint(
    config: CodingProviderConfig, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
) -> str:
    """Reuse unchanged held evidence only within the same declared pre-deadline target.

    Retrieval/as-of clocks are not fresh editorial content. Original responses and their
    source publication dates remain unchanged; reuse never manufactures a new statement.
    A different target, roster, instrument or any source bytes demands another call.
    """
    build_user_content(documents, roster, target_context=config.target_context)
    target = dict(config.target_context or {})
    target.pop("as_of", None)
    value = {
        "provider": config.provider,
        "model": config.model_identifier,
        "selection_policy": SELECTION_POLICY_VERSION,
        "prompt": coding_prompt_sha256(config.model_identifier),
        "target": target,
        "instrument": {
            "endpoint": hashlib.sha256((config.base_url or "").encode()).hexdigest(),
            "format": config.response_format,
            "max_tokens": config.max_completion_tokens,
        },
        "documents": [
            {
                "club": d.club,
                "url": d.final_url,
                "content_type": d.content_type.split(";", 1)[0].strip().lower(),
                "content": hashlib.sha256(d.content).hexdigest(),
                "readable": hashlib.sha256(d.readable).hexdigest(),
                "last_modified": d.last_modified_utc,
            }
            for d in documents
        ],
        "roster": sorted(
            [asdict(player) for player in roster], key=lambda row: json.dumps(row, sort_keys=True)
        ),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class WeekCoding:
    """One week's coding: the answers, the refusals, and how many requests were sent.

    ``calls_attempted`` counts calls to the provider that were begun, whether they came
    back as an answer or as an error. A reused answer, a club stopped by the budget and a
    club refused before its call began attempted none.

    ``refusal_kinds`` names, club by club and in the order of ``refused``, which of four
    different things a refusal was. The sentence in ``refused`` is for a person; the kind is
    for a report that must not mix them.
    """

    coded: tuple[CodedClub, ...]
    refused: tuple[tuple[str, str], ...]
    calls_attempted: int
    refusal_kinds: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if [club for club, _ in self.refusal_kinds] != [club for club, _ in self.refused]:
            raise ValueError("Each refusal has its kind, in the order the refusals are listed.")


#: No document of the club was selected for coding, so there was nothing to ask about.
REFUSAL_NOTHING_SELECTED: Final = "nothing_selected"
#: The run's call budget was spent before this club's turn. No call was attempted.
REFUSAL_BUDGET: Final = "budget_stopped"
#: The club's input was refused before any call was attempted.
REFUSAL_BEFORE_CALL: Final = "refused_before_call"
#: A call was attempted and did not produce a usable answer.
REFUSAL_CALL_FAILED: Final = "call_failed"


def code_week_by_club(
    provider: ClubNewsProvider,
    config: CodingProviderConfig,
    documents: Sequence[RawDocument],
    roster: Sequence[RosterPlayer],
    *,
    max_calls: int | None = None,
    previous: Sequence[CodedClub] = (),
    selection: DocumentSelection | None = None,
) -> tuple[tuple[CodedClub, ...], tuple[tuple[str, str], ...]]:
    """What :func:`code_week` coded and refused, without its count of requests."""

    week = code_week(
        provider,
        config,
        documents,
        roster,
        max_calls=max_calls,
        previous=previous,
        selection=selection,
    )
    return week.coded, week.refused


def code_week(
    provider: ClubNewsProvider,
    config: CodingProviderConfig,
    documents: Sequence[RawDocument],
    roster: Sequence[RosterPlayer],
    *,
    max_calls: int | None = None,
    previous: Sequence[CodedClub] = (),
    selection: DocumentSelection | None = None,
) -> WeekCoding:
    """Code a week one club at a time, returning what was coded and why the rest was not.

    ``selection`` is the caller's own selection of these documents, when it has already made
    one. Passing it means the documents that are coded and the documents the caller reports
    as selected are one result and cannot drift apart; left out, the selection is made here
    from the configuration's own ``as_of``.

    **The request unit is one club, and that is a decision about failure rather than about
    tidiness.** ``MAX_OUTPUT_TOKENS`` and ``REQUEST_TIMEOUT_SECONDS`` are each justified in
    their own comments for one club's page and a squad list, and
    :func:`~squadopt.platform.club_news_model._claim_response` *raises* when a response stops
    at the ceiling rather than degrading. Put every club in one call and that ceiling costs
    the entire week's read; put one club in each and it costs that club, which is the failure
    this lane already models correctly -- the same shape
    :func:`~squadopt.platform.club_news_fetch.fetch_registered_documents` returns, for the
    same reason.

    The arithmetic behind it, measured on the committed fixture: thirteen claims came to 5,121
    bytes, about 393 bytes each. A full registry is twenty clubs against a 656-player roster;
    if a quarter of those players are written about, one call's answer is roughly 164 claims,
    some 64 KB, which is about sixteen thousand tokens -- the ceiling exactly. Half of them
    and it is double. Per club that answer is a twentieth of the size and nowhere near it.

    **The roster is not narrowed to the club.** It would shrink each call further, and it
    would also change what a claim can resolve to: a club's page that mentions an opponent's
    player would stop resolving. That is a semantic change wearing a performance change's
    clothes, so it is not made here. The input budget does not need it -- one club's pages and
    the whole roster come to a few tens of kilobytes against
    :data:`~squadopt.data.sources.club_news_coding.MAXIMUM_USER_CONTENT_BYTES`, which is two
    megabytes.

    Clubs are coded in the order their documents arrive, so two runs over one capture ask the
    same questions in the same order. A club whose call fails is named with its reason and the
    week carries on.
    """

    if max_calls is not None and (
        isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 0
    ):
        raise ClubNewsProviderError("Call budget must be a nonnegative integer.")
    selected = (
        selection
        if selection is not None
        else select_coding_documents(documents, as_of=coding_as_of(config))
    )
    by_club: dict[str, list[RawDocument]] = {}
    for document in selected.documents:
        by_club.setdefault(document.club, []).append(document)

    prompt_sha256 = coding_prompt_sha256(config.model_identifier)
    coded: list[CodedClub] = []
    refused: list[tuple[str, str]] = [
        (club, "No current first-team document selected for coding.")
        for club in dict.fromkeys(d.club for d in documents)
        if club not in by_club
    ]
    kinds: list[tuple[str, str]] = [(club, REFUSAL_NOTHING_SELECTED) for club, _ in refused]
    previous_by_club = {item.club: item for item in previous}
    attempted = 0
    for club, club_documents in by_club.items():
        called = False
        try:
            fingerprint = coding_input_fingerprint(config, club_documents, roster)
            held = previous_by_club.get(club)
            if (
                config.target_context is not None
                and held is not None
                and held.request_fingerprint == fingerprint
                and held.provider == config.provider
                and held.prompt_sha256 == prompt_sha256
                and held.response.model_identifier == config.model_identifier
            ):
                # A held answer that no longer meets the contract is refused with no call
                # attempted, like an input refused before its question is built.
                require_requested_coding_contract(held.response)
                coded.append(held)
                continue
            if max_calls is not None and attempted >= max_calls:
                refused.append((club, "Call budget exhausted; no model request was sent."))
                kinds.append((club, REFUSAL_BUDGET))
                continue
            attempted += 1
            called = True
            response = provider.code(club_documents, roster)
            require_requested_coding_contract(response)
        except ClubNewsError as error:
            refused.append((club, str(error)))
            kinds.append((club, REFUSAL_CALL_FAILED if called else REFUSAL_BEFORE_CALL))
            continue
        coded.append(
            CodedClub(
                club=club,
                response=response,
                request_fingerprint=fingerprint,
                prompt_contract_version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                prompt_sha256=prompt_sha256,
                # Which adapter was asked, beside which model answered. The two are not
                # recoverable from each other: a fake adapter can name any model, and one
                # vendor's identifier can be served through another's compatible endpoint.
                provider=config.provider,
                request_configuration=(
                    {
                        "protocol": "openai_chat_completions_v1",
                        "endpoint_sha256": hashlib.sha256(
                            (str(config.base_url) + "/chat/completions").encode("utf-8")
                        ).hexdigest(),
                        "response_format": config.response_format,
                        "max_completion_tokens": config.max_completion_tokens,
                    }
                    if config.provider in _OPENAI_PROVIDERS
                    else None
                ),
            )
        )
    return WeekCoding(tuple(coded), tuple(refused), attempted, tuple(kinds))


def _anthropic(config: CodingProviderConfig) -> ClubNewsProvider:
    """Build the one adapter that ships, importing it only when it is selected."""

    from squadopt.platform.club_news_model import AnthropicClubNewsProvider

    return AnthropicClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
        # The acquisition budget counts requests, so SDK retries cannot spend more
        # requests behind one counted call. Direct adapter callers keep their default.
        max_transport_retries=0,
    )


def _gemini(config: CodingProviderConfig) -> ClubNewsProvider:
    """Build the free-tier adapter. Its HTTP client is built here and not before."""

    return GeminiClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
    )


def _openai(config: CodingProviderConfig) -> ClubNewsProvider:
    return OpenAIClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        target_context=config.target_context,
        base_url=config.base_url or DEFAULT_OPENAI_BASE_URL,
        response_format=config.response_format,
        max_completion_tokens=config.max_completion_tokens,
        allow_local_http=config.allow_local_http,
    )


register_provider(DEFAULT_PROVIDER, _anthropic)
register_provider(GEMINI_PROVIDER, _gemini)
register_provider("openai", _openai)
register_provider("openai-compatible", _openai)


__all__ = [
    "DEFAULT_PROVIDER",
    "KEY_ENVIRONMENT_VARIABLE",
    "MODEL_ENVIRONMENT_VARIABLE",
    "PROVIDER_ENVIRONMENT_VARIABLE",
    "REFUSAL_BEFORE_CALL",
    "REFUSAL_BUDGET",
    "REFUSAL_CALL_FAILED",
    "REFUSAL_NOTHING_SELECTED",
    "VENDOR_KEY_VARIABLES",
    "ClubNewsProviderError",
    "CodingProviderConfig",
    "WeekCoding",
    "bind_coding_provider",
    "build_coding_provider",
    "check_coding_provider",
    "code_week",
    "code_week_by_club",
    "coding_as_of",
    "register_provider",
    "registered_providers",
    "require_provider_dependency",
    "resolve_provider_config",
    "validate_provider_config",
]
