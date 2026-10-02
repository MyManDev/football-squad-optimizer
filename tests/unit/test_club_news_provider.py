"""Which model codes a week, and how the environment says so.

Every test here hands in a mapping rather than touching the real environment, and none of them
builds a real client: what is asserted is the decision, not the call. A test that needed a key
would not be an offline test, and this whole lane's point is that the offline path and the live
path are the same code with different bytes.
"""

import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_club_news_model import _RecordingSdk

from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import (
    CODING_MODEL_IDENTIFIER,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.platform import club_news_provider
from squadopt.platform.club_news_gemini import (
    GEMINI_PROVIDER,
    ClubNewsGeminiError,
    GeminiClubNewsProvider,
)
from squadopt.platform.club_news_model import AnthropicClubNewsProvider
from squadopt.platform.club_news_provider import (
    DEFAULT_PROVIDER,
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    VENDOR_KEY_VARIABLES,
    ClubNewsProviderError,
    CodingProviderConfig,
    build_coding_provider,
    code_week_by_club,
    register_provider,
    registered_providers,
    resolve_provider_config,
)

VENDOR_VARIABLE = VENDOR_KEY_VARIABLES[DEFAULT_PROVIDER]


class _Fake:
    """A provider that codes nothing, so the wiring can be tested without a call."""

    def __init__(self, config: CodingProviderConfig) -> None:
        self.config = config

    def fetch(self, url: str) -> RawDocument:  # pragma: no cover - never called here
        raise AssertionError(f"the fake provider does not fetch {url!r}")

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:  # pragma: no cover - never called here
        raise AssertionError("the fake provider does not code")


@pytest.fixture(name="fake")
def _fake() -> str:
    """Register a fake under a name nothing else uses, the way a rehearsal would."""

    name = "fake-for-tests"
    register_provider(name, _Fake)
    return name


# --- what the environment decides -------------------------------------------


def test_an_unconfigured_checkout_selects_the_one_adapter_that_ships() -> None:
    """Behaviour before this module existed, preserved: no variable, same provider."""

    config = resolve_provider_config({VENDOR_VARIABLE: "k"})

    assert config.provider == DEFAULT_PROVIDER
    assert config.model_identifier == CODING_MODEL_IDENTIFIER


def test_a_provider_is_selected_by_environment_variable_alone(fake: str) -> None:
    """The rehearsal's whole premise: no code edit, one variable."""

    provider, config = build_coding_provider(
        {
            PROVIDER_ENVIRONMENT_VARIABLE: fake,
            MODEL_ENVIRONMENT_VARIABLE: "fake-model-1",
            KEY_ENVIRONMENT_VARIABLE: "not-a-real-key",
        }
    )

    assert isinstance(provider, _Fake)
    assert config.provider == fake
    assert config.model_identifier == "fake-model-1"


def test_configured_anthropic_acquisition_has_no_hidden_transport_retries(monkeypatch) -> None:
    sdk = _RecordingSdk()
    monkeypatch.setitem(sys.modules, "anthropic", sdk)
    provider, config = build_coding_provider({VENDOR_VARIABLE: "synthetic-key"})
    assert isinstance(provider, AnthropicClubNewsProvider)
    assert config.provider == DEFAULT_PROVIDER
    assert sdk.kwargs["max_retries"] == 0


def test_openai_context_is_forwarded_to_adapter_after_offline_config_validation(
    monkeypatch,
) -> None:
    context = {
        "season": "2026-27",
        "gameweek": 6,
        "deadline": "2026-10-10T10:00:00Z",
        "as_of": "2026-10-02T00:00:00Z",
    }
    recorder = {}

    def factory(**kwargs):
        recorder.update(kwargs)
        return _Recorder()

    monkeypatch.setattr(club_news_provider, "OpenAIClubNewsProvider", factory)
    _, config = build_coding_provider(
        {
            PROVIDER_ENVIRONMENT_VARIABLE: "openai",
            MODEL_ENVIRONMENT_VARIABLE: "synthetic-model",
            KEY_ENVIRONMENT_VARIABLE: "synthetic-key",
        },
        target_context=context,
    )
    assert config.target_context == context
    assert recorder["target_context"] == context
    assert recorder["model_identifier"] == "synthetic-model"


def test_an_unregistered_provider_is_refused_and_the_alternatives_are_named() -> None:
    """A typo in a variable should not look like a missing key."""

    with pytest.raises(ClubNewsProviderError, match="not registered"):
        resolve_provider_config(
            {PROVIDER_ENVIRONMENT_VARIABLE: "no-such-provider", KEY_ENVIRONMENT_VARIABLE: "k"}
        )

    assert DEFAULT_PROVIDER in registered_providers()


# --- the key ----------------------------------------------------------------


def test_a_missing_key_is_refused_loudly_and_never_falls_back(fake: str) -> None:
    """ "We could not ask" and "the fixture said" are different facts."""

    with pytest.raises(ClubNewsProviderError) as refusal:
        resolve_provider_config(
            {PROVIDER_ENVIRONMENT_VARIABLE: fake, MODEL_ENVIRONMENT_VARIABLE: "fake-model-1"}
        )

    assert KEY_ENVIRONMENT_VARIABLE in str(refusal.value)
    assert "fall back" in str(refusal.value)


def test_the_vendor_variable_still_works_as_a_compatibility_path() -> None:
    """An operator who already exported the vendor's own name is not asked to rename it."""

    config = resolve_provider_config({VENDOR_VARIABLE: "vendor-key"})

    assert config.api_key == "vendor-key"


def test_the_generic_variable_wins_where_both_are_set() -> None:
    """The contract is the generic one; the vendor one is the courtesy."""

    config = resolve_provider_config(
        {
            PROVIDER_ENVIRONMENT_VARIABLE: DEFAULT_PROVIDER,
            KEY_ENVIRONMENT_VARIABLE: "generic-key",
            VENDOR_VARIABLE: "vendor-key",
        }
    )

    assert config.api_key == "generic-key"


def test_a_generic_key_without_a_provider_is_refused_before_anything_is_sent() -> None:
    """The one configuration where the default provider decides whose key this is.

    ``SQUADOPT_LLM_API_KEY`` carries no vendor. With no provider line the default picks one,
    and the key goes to that vendor with the first club's call. A key that reached the wrong
    vendor has left the machine, and no later refusal can call it back, so this one has to
    happen at configuration rather than at the first request.
    """

    with pytest.raises(ClubNewsProviderError) as refusal:
        resolve_provider_config({KEY_ENVIRONMENT_VARIABLE: "a-key-for-some-vendor"})

    named = str(refusal.value)
    assert KEY_ENVIRONMENT_VARIABLE in named
    assert PROVIDER_ENVIRONMENT_VARIABLE in named
    assert "a-key-for-some-vendor" not in named


def test_a_vendor_key_without_a_provider_still_works_because_it_names_its_vendor() -> None:
    """The compatibility path is not ambiguous, so it is not refused.

    ``ANTHROPIC_API_KEY`` says whose key it is in its own name. The default adapter is then
    not a guess about the key, and an operator who exported that name years ago is not asked
    to add a line to keep it working.
    """

    config = resolve_provider_config({VENDOR_VARIABLE: "vendor-key"})

    assert config.provider == DEFAULT_PROVIDER
    assert config.api_key == "vendor-key"


def test_a_refusal_names_both_variables_when_a_vendor_path_exists() -> None:
    """So an operator is told the name they may already have exported."""

    with pytest.raises(ClubNewsProviderError) as refusal:
        resolve_provider_config({})

    assert KEY_ENVIRONMENT_VARIABLE in str(refusal.value)
    assert VENDOR_VARIABLE in str(refusal.value)


# --- the model, and what it does to the record ------------------------------


def test_a_provider_without_a_declared_model_must_be_told_which_one(fake: str) -> None:
    """Which model answered is recorded forever, so it is not a thing to guess."""

    with pytest.raises(ClubNewsProviderError, match="declares no default model"):
        resolve_provider_config(
            {PROVIDER_ENVIRONMENT_VARIABLE: fake, KEY_ENVIRONMENT_VARIABLE: "k"}
        )


def test_the_prompt_fingerprint_moves_with_the_model() -> None:
    """The contract's own sentence, now holding rather than merely asserted.

    "The same words put to a different model are a different question" was written when the
    identifier was a constant folded into the digest. It is configuration now, so the digest
    has to follow it or the sentence stops being true.
    """

    assert coding_prompt_sha256() == coding_prompt_sha256(CODING_MODEL_IDENTIFIER)
    assert coding_prompt_sha256("another-model") != coding_prompt_sha256()


def test_an_unconfigured_run_still_produces_the_contract_digest() -> None:
    """Nothing about a checkout's recorded fingerprint changes because this module exists."""

    config = resolve_provider_config({VENDOR_VARIABLE: "k"})

    assert coding_prompt_sha256(config.model_identifier) == coding_prompt_sha256()


def test_a_provider_needs_a_name_to_be_selected_by() -> None:
    def _factory(config: CodingProviderConfig) -> _Fake:  # pragma: no cover - never built
        return _Fake(config)

    with pytest.raises(ClubNewsProviderError, match="needs a name"):
        register_provider("   ", _factory)


def test_the_environment_is_not_read_when_a_mapping_is_given() -> None:
    """Pinned because a reader that quietly consulted `os.environ` would make every test above
    depend on the machine it ran on."""

    empty: Mapping[str, str] = {}

    with pytest.raises(ClubNewsProviderError):
        resolve_provider_config(empty)


# --- what the runbook tells the operator ------------------------------------

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "weekly_runbook.md"


def _runbook_bullet_on_the_three_variables() -> str:
    """The runbook's bullet on the coding model, from its bold heading to the next bullet."""

    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index("- **Which model codes the club news")
    return text[start : text.index("\n- ", start + 1)]


def _runbook_snippet(bullet: str) -> dict[str, str]:
    """The ``$env:NAME = "value"`` lines an operator pastes, as the mapping they produce."""

    return dict(re.findall(r'^\s*\$env:(\w+) = "([^"]*)"', bullet, flags=re.MULTILINE))


class _SilentClient:
    """Satisfies ``CodingClient`` and fails if anything is asked of it."""

    @property
    def messages(self) -> "_SilentClient":
        return self

    def create(self, **kwargs: Any) -> Any:  # pragma: no cover - never called here
        raise AssertionError("nothing is asked while an adapter is only being built")


def test_the_runbook_names_the_key_the_default_adapter_reads_when_the_provider_line_is_out() -> (
    None
):
    """The runbook's own lines, minus the provider line, are refused before anything is sent.

    The snippet is read out of the runbook rather than copied here, so this follows what an
    operator would paste. Without its provider line the generic key names no vendor, and the
    default would decide whose key it is by guessing. A key that reaches the wrong vendor has
    left the machine before any refusal can reach it, so the refusal has to come at
    configuration. The runbook's sentence about that path still has to name the generic
    variable first, because that is the one the default adapter reads first.
    """

    bullet = _runbook_bullet_on_the_three_variables()
    snippet = _runbook_snippet(bullet)
    assert snippet.keys() == {
        PROVIDER_ENVIRONMENT_VARIABLE,
        KEY_ENVIRONMENT_VARIABLE,
        MODEL_ENVIRONMENT_VARIABLE,
    }
    assert snippet[PROVIDER_ENVIRONMENT_VARIABLE] == GEMINI_PROVIDER

    del snippet[PROVIDER_ENVIRONMENT_VARIABLE]
    with pytest.raises(ClubNewsProviderError) as refusal:
        resolve_provider_config(snippet)

    named = str(refusal.value)
    assert KEY_ENVIRONMENT_VARIABLE in named
    assert PROVIDER_ENVIRONMENT_VARIABLE in named
    # The key itself is what must not travel, so it is not echoed back either.
    assert snippet[KEY_ENVIRONMENT_VARIABLE] not in named

    unset_provider = bullet[
        bullet.index(f"With `{PROVIDER_ENVIRONMENT_VARIABLE}` unset") : bullet.index(
            f"With `{MODEL_ENVIRONMENT_VARIABLE}` unset"
        )
    ]
    generic, vendor = f"`{KEY_ENVIRONMENT_VARIABLE}`", f"`{VENDOR_VARIABLE}`"
    assert generic in unset_provider
    assert vendor in unset_provider
    assert unset_provider.index(generic) < unset_provider.index(vendor)


def test_the_runbook_heading_claims_a_model_check_only_for_the_adapter_that_makes_one() -> None:
    """The default adapter is built with any model name; only the free adapter refuses one.

    So a heading saying all three variables are checked before anything is fetched overclaims
    for the default adapter: its provider name and its key are checked at configuration, and its
    model is not checked anywhere. The heading has to confine the model check to the adapter
    whose constructor makes it.
    """

    unlisted = "a-model-no-list-holds"

    config = resolve_provider_config(
        {
            PROVIDER_ENVIRONMENT_VARIABLE: DEFAULT_PROVIDER,
            KEY_ENVIRONMENT_VARIABLE: "k",
            MODEL_ENVIRONMENT_VARIABLE: unlisted,
        }
    )
    built = AnthropicClubNewsProvider(client=_SilentClient(), model_identifier=unlisted)
    with pytest.raises(ClubNewsGeminiError, match="not in the provider's model list"):
        GeminiClubNewsProvider(api_key="k", model_identifier=unlisted)

    assert config.provider == DEFAULT_PROVIDER
    assert config.model_identifier == unlisted
    assert built is not None
    heading = _runbook_bullet_on_the_three_variables().split("**")[1]
    assert f"`{GEMINI_PROVIDER}`" in heading


# --- the request unit -------------------------------------------------------


def _document(club: str, path: str) -> RawDocument:
    return RawDocument(
        club=club,
        requested_url=f"https://club.example/{path}",
        final_url=f"https://club.example/{path}",
        http_status=200,
        content_type="text/html; charset=utf-8",
        byte_length=1,
        fetched_at_utc="2026-09-12T14:00:00Z",
        content=b"x",
        readable=b"x",
    )


def _response(text: str | None = None) -> ClaimResponse:
    if text is None:
        text = json.dumps(
            {
                "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                "documents": [],
                "claims": [],
            }
        )
    return ClaimResponse(text=text, model_identifier="m", model_version="v")


class _Recorder:
    """Counts calls and can be told to fail for one named club."""

    def __init__(self, *, fails_for: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._fails_for = fails_for

    def fetch(self, url: str) -> RawDocument:  # pragma: no cover - never called here
        raise AssertionError(f"not a fetcher: {url!r}")

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        clubs = tuple(dict.fromkeys(document.club for document in documents))
        self.calls.append(clubs)
        if self._fails_for is not None and self._fails_for in clubs:
            raise ClubNewsError(
                f"The response reached the ceiling and is truncated, for {self._fails_for}."
            )
        return _response()


CONFIG = CodingProviderConfig(
    provider=DEFAULT_PROVIDER, model_identifier=CODING_MODEL_IDENTIFIER, api_key="k"
)
ROSTER = (
    RosterPlayer(1, "Arsenal Player", "Arsenal"),
    RosterPlayer(2, "United Player", "Man Utd"),
    RosterPlayer(3, "Everton Player", "Everton"),
)


def test_each_club_is_one_call_and_no_call_carries_two_clubs() -> None:
    """Counted, not assumed. The ceiling is per call, so the unit decides what it costs."""

    documents = [
        _document("Arsenal", "arsenal/team-news"),
        _document("Man Utd", "united/press"),
        _document("Man Utd", "united/injuries"),
        _document("Everton", "everton/news"),
    ]
    recorder = _Recorder()

    coded, refused = code_week_by_club(recorder, CONFIG, documents, ROSTER)

    assert refused == ()
    assert len(recorder.calls) == 3
    assert all(len(clubs) == 1 for clubs in recorder.calls)
    assert [club.club for club in coded] == ["Arsenal", "Man Utd", "Everton"]


def test_a_club_whose_answer_hits_the_ceiling_does_not_cost_the_week() -> None:
    """The failure this lane already models: one club failing does not fail the week.

    In one call for the whole week, the same truncation loses every club's read at once --
    which is the reason the unit changed rather than the constants.
    """

    documents = [
        _document("Arsenal", "arsenal/team-news"),
        _document("Man Utd", "united/press"),
        _document("Everton", "everton/news"),
    ]

    coded, refused = code_week_by_club(_Recorder(fails_for="Man Utd"), CONFIG, documents, ROSTER)

    assert [club.club for club in coded] == ["Arsenal", "Everton"]
    assert [club for club, _reason in refused] == ["Man Utd"]
    assert "ceiling" in refused[0][1]


def test_a_club_s_pages_arrive_together_in_its_one_call() -> None:
    """Two registered pages are one question about one club, not two."""

    documents = [
        _document("Man Utd", "united/press"),
        _document("Man Utd", "united/injuries"),
    ]
    recorder = _Recorder()

    code_week_by_club(recorder, CONFIG, documents, ROSTER)

    assert len(recorder.calls) == 1


def test_every_coded_club_carries_the_fingerprint_of_the_model_that_was_asked() -> None:
    """A response is only interpretable against the question that produced it."""

    coded, _refused = code_week_by_club(
        _Recorder(), CONFIG, [_document("Arsenal", "arsenal/team-news")], ROSTER
    )

    assert coded[0].prompt_sha256 == coding_prompt_sha256(CODING_MODEL_IDENTIFIER)


def test_a_different_model_produces_a_different_recorded_question() -> None:
    """Genericity does not blur the record: two weeks coded by two models stay apart."""

    other = CodingProviderConfig(
        provider=DEFAULT_PROVIDER, model_identifier="another-model", api_key="k"
    )

    coded, _refused = code_week_by_club(
        _Recorder(), other, [_document("Arsenal", "arsenal/team-news")], ROSTER
    )

    assert coded[0].prompt_sha256 != coding_prompt_sha256(CODING_MODEL_IDENTIFIER)


def test_contract_mismatch_refuses_one_club_without_retrying_or_losing_other_clubs() -> None:
    class MixedContracts(_Recorder):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            current = super().code(documents, roster)
            if documents[0].club == "Arsenal":
                return _response(
                    json.dumps(
                        {
                            "contract_version": "rotation_claim_coding_v1",
                            "claims": [],
                            "documents": [],
                        }
                    )
                )
            return current

    provider = MixedContracts()
    coded, refused = code_week_by_club(
        provider,
        CONFIG,
        [
            _document("Arsenal", "arsenal/news"),
            _document("Man Utd", "united/news"),
        ],
        ROSTER,
    )
    assert provider.calls == [("Arsenal",), ("Man Utd",)]
    assert [entry.club for entry in coded] == ["Man Utd"]
    assert len(refused) == 1 and refused[0][0] == "Arsenal"
    assert "requested coding contract" in refused[0][1]
    assert coded[0].prompt_contract_version == ROTATION_CLAIM_CODING_CONTRACT_VERSION
    assert (
        json.loads(coded[0].response.text)["contract_version"] == coded[0].prompt_contract_version
    )
