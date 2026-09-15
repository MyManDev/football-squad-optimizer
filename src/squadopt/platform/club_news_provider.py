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

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from squadopt.data.sources.club_news import ClubNewsError, ClubNewsProvider
from squadopt.data.sources.club_news_coding import CODING_MODEL_IDENTIFIER

#: Which adapter codes the week. No vendor name, by contract.
PROVIDER_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_PROVIDER"

#: Which model that adapter asks. Optional; the adapter's own default stands otherwise.
MODEL_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_MODEL"

#: The key, read from the environment and never committed.
KEY_ENVIRONMENT_VARIABLE: Final = "SQUADOPT_LLM_API_KEY"

#: The provider selected when nothing says otherwise: the one adapter that exists.
DEFAULT_PROVIDER: Final = "anthropic"

#: Each adapter's own historical key variable, read only when the generic one is unset. This
#: is a compatibility path and not the contract, which is why it is a lookup rather than a
#: constant: a second adapter adds a row here and changes nothing else.
VENDOR_KEY_VARIABLES: Final[Mapping[str, str]] = {"anthropic": "ANTHROPIC_API_KEY"}


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
    api_key: str


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
) -> CodingProviderConfig:
    """Read the three variables, or refuse by name.

    ``environ`` is injectable so tests never touch the real environment, and so the rehearsal
    can select a fake provider by handing in a mapping rather than by editing anything.
    """

    source = os.environ if environ is None else environ
    provider = source.get(PROVIDER_ENVIRONMENT_VARIABLE, "").strip() or DEFAULT_PROVIDER
    if provider not in _FACTORIES:
        raise ClubNewsProviderError(
            f"{PROVIDER_ENVIRONMENT_VARIABLE} names {provider!r}, which is not registered. "
            f"Registered providers: {list(registered_providers())!r}."
        )
    model = source.get(MODEL_ENVIRONMENT_VARIABLE, "").strip() or _default_model(provider)
    return CodingProviderConfig(
        provider=provider, model_identifier=model, api_key=_read_key(provider, source)
    )


def _default_model(provider: str) -> str:
    """The model an adapter asks when the environment does not say.

    Only the vendor the coding contract was written against has one: its identifier is part of
    the frozen prompt's fingerprint, so defaulting to it keeps an unconfigured run producing
    exactly the digest the contract describes. Any other provider must be told, because there
    is no model this repository has declared for it.
    """

    if provider == DEFAULT_PROVIDER:
        return CODING_MODEL_IDENTIFIER
    raise ClubNewsProviderError(
        f"{MODEL_ENVIRONMENT_VARIABLE} is unset and provider {provider!r} declares no default "
        "model. Name the model: which one answered is recorded forever, so it is not a thing "
        "to guess."
    )


def build_coding_provider(
    environ: Mapping[str, str] | None = None,
) -> tuple[ClubNewsProvider, CodingProviderConfig]:
    """The configured provider, and the configuration it was built from.

    Both are returned because the caller needs the second: the capture records which model was
    asked, and reading it back off the adapter would ask the adapter to be honest about itself.
    """

    config = resolve_provider_config(environ)
    return _FACTORIES[config.provider](config), config


def _anthropic(config: CodingProviderConfig) -> ClubNewsProvider:
    """Build the one adapter that ships, importing it only when it is selected."""

    from squadopt.platform.club_news_model import AnthropicClubNewsProvider

    return AnthropicClubNewsProvider(
        api_key=config.api_key, model_identifier=config.model_identifier
    )


register_provider(DEFAULT_PROVIDER, _anthropic)


__all__ = [
    "DEFAULT_PROVIDER",
    "KEY_ENVIRONMENT_VARIABLE",
    "MODEL_ENVIRONMENT_VARIABLE",
    "PROVIDER_ENVIRONMENT_VARIABLE",
    "VENDOR_KEY_VARIABLES",
    "ClubNewsProviderError",
    "CodingProviderConfig",
    "build_coding_provider",
    "register_provider",
    "registered_providers",
    "resolve_provider_config",
]
