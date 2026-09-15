"""Which model codes a week, and how the environment says so.

Every test here hands in a mapping rather than touching the real environment, and none of them
builds a real client: what is asserted is the decision, not the call. A test that needed a key
would not be an offline test, and this whole lane's point is that the offline path and the live
path are the same code with different bytes.
"""

from collections.abc import Mapping, Sequence

import pytest

from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import CODING_MODEL_IDENTIFIER, coding_prompt_sha256
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
        {KEY_ENVIRONMENT_VARIABLE: "generic-key", VENDOR_VARIABLE: "vendor-key"}
    )

    assert config.api_key == "generic-key"


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


def _response(text: str = "{}") -> ClaimResponse:
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


def test_each_club_is_one_call_and_no_call_carries_two_clubs() -> None:
    """Counted, not assumed. The ceiling is per call, so the unit decides what it costs."""

    documents = [
        _document("Arsenal", "arsenal/team-news"),
        _document("Man Utd", "united/press"),
        _document("Man Utd", "united/injuries"),
        _document("Everton", "everton/news"),
    ]
    recorder = _Recorder()

    coded, refused = code_week_by_club(recorder, CONFIG, documents, ())

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

    coded, refused = code_week_by_club(_Recorder(fails_for="Man Utd"), CONFIG, documents, ())

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

    code_week_by_club(recorder, CONFIG, documents, ())

    assert len(recorder.calls) == 1


def test_every_coded_club_carries_the_fingerprint_of_the_model_that_was_asked() -> None:
    """A response is only interpretable against the question that produced it."""

    coded, _refused = code_week_by_club(
        _Recorder(), CONFIG, [_document("Arsenal", "arsenal/team-news")], ()
    )

    assert coded[0].prompt_sha256 == coding_prompt_sha256(CODING_MODEL_IDENTIFIER)


def test_a_different_model_produces_a_different_recorded_question() -> None:
    """Genericity does not blur the record: two weeks coded by two models stay apart."""

    other = CodingProviderConfig(
        provider=DEFAULT_PROVIDER, model_identifier="another-model", api_key="k"
    )

    coded, _refused = code_week_by_club(
        _Recorder(), other, [_document("Arsenal", "arsenal/team-news")], ()
    )

    assert coded[0].prompt_sha256 != coding_prompt_sha256(CODING_MODEL_IDENTIFIER)
