"""One entry point for the whole member menu: the batch's payloads, one address at a time.

``advise_menu_entry`` decides nothing about advice. It validates a combination, computes
what the chosen producer needs first, and calls the producer the batch calls. So the tests
here are equalities: a plain request is ``advise_entry``'s payload, and every other address
is the payload ``render_member`` produced for the same member from the same inputs.
"""

import json
from dataclasses import replace
from typing import Any

import pytest
import tests.unit.test_advice_variants as variants_module
from tests.unit.test_advice_variants import RIVAL
from tests.unit.test_member_windows import ENTRY, LEAGUE, SEASON
from tests.unit.test_top100_weight import _words

from squadopt.application.advice import AdviseEntryRequest, advise_entry
from squadopt.application.advice_capabilities import (
    TOP100_WEIGHTS,
    advice_capabilities,
    menu_capabilities,
    validate_advice_selection,
)
from squadopt.application.advice_menu import (
    MANAGER_WORDS_INPUT,
    TOP100_COUNTS_INPUT,
    ManagersWordNotSolved,
    MenuInputUnavailable,
    MenuRequest,
    advise_menu_entry,
)
from squadopt.application.entries import EntryError
from squadopt.application.league_views import MemberRenderTask, render_member
from squadopt.application.top100_weight import TOP100_WEIGHTS as PRODUCER_WEIGHTS

window_world = variants_module.window_world  # re-register the fixtures in this module
world = variants_module._world


def _request(**overrides: Any) -> MenuRequest:
    fields: dict[str, Any] = {
        "season": SEASON,
        "gameweek": 2,
        "league_id": LEAGUE,
        "entry_id": ENTRY,
    }
    fields.update(overrides)
    return MenuRequest(**fields)


def _collaborators(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": world["provider"],
        "inputs": world["inputs"],
        "projection": world["projection"],
        "rules": world["rules"],
        "horizon_builder": world["builder"],
    }


# -- what may be asked --------------------------------------------------------------------


def test_the_old_selection_rules_are_untouched_when_the_new_arguments_are_left_alone() -> None:
    assert advice_capabilities()["ortak-koru"].windows == (1,)
    validate_advice_selection(strategy="saf-puan", window=5, entry_id=1, rival_entry_id=None)
    validate_advice_selection(strategy="ortak-koru", window=1, entry_id=1, rival_entry_id=2)
    with pytest.raises(EntryError, match="supports windows"):
        validate_advice_selection(strategy="ortak-koru", window=3, entry_id=1, rival_entry_id=2)
    # The list ``advise_entry`` answers offers no switch, so asking for one is refused.
    with pytest.raises(EntryError, match="Top 100 influence is not computed"):
        validate_advice_selection(
            strategy="saf-puan", window=1, entry_id=1, rival_entry_id=None, top100_weight=20
        )
    with pytest.raises(EntryError, match="manager's word applies"):
        validate_advice_selection(
            strategy="saf-puan", window=1, entry_id=1, rival_entry_id=None, managers_word=True
        )


def test_the_menu_offers_what_the_batch_publishes() -> None:
    menu = menu_capabilities()
    assert set(menu) == set(advice_capabilities())
    assert PRODUCER_WEIGHTS is TOP100_WEIGHTS
    for slug, capability in menu.items():
        assert capability.windows == (1, 3, 5)
        assert capability.top100_windows == (1, 3, 5)
        assert capability.managers_word_windows == ((1,) if slug == "saf-puan" else ())

    def check(**selection: Any) -> None:
        fields = {"strategy": "saf-puan", "window": 1, "entry_id": 1, "rival_entry_id": None}
        validate_advice_selection(**{**fields, **selection}, capabilities=menu)

    check(top100_weight=50, managers_word=True)
    check(window=5, top100_weight=5)
    check(strategy="fark-yarat", window=3, rival_entry_id=2, top100_weight=10)
    with pytest.raises(EntryError, match="manager's word applies"):
        check(window=3, managers_word=True)
    with pytest.raises(EntryError, match="manager's word applies"):
        check(strategy="ortak-koru", rival_entry_id=2, managers_word=True)
    with pytest.raises(EntryError, match="needs a rival"):
        check(strategy="ortak-koru", window=3)
    for bad in (15, True, 20.0, "20", None, -5):
        with pytest.raises(EntryError, match="must be one of"):
            check(top100_weight=bad)
    with pytest.raises(EntryError, match="true or false"):
        check(managers_word=1)


def test_a_request_refuses_what_it_cannot_carry() -> None:
    with pytest.raises(EntryError, match="top100_weight must be an integer"):
        _request(top100_weight=True)
    with pytest.raises(EntryError, match="managers_word must be true or false"):
        _request(managers_word="yes")
    with pytest.raises(EntryError, match="positive integer"):
        _request(entry_id=0)
    assert _request().is_plain and not _request(top100_weight=5).is_plain
    assert _request(top100_weight=5, managers_word=True).entry_request() == AdviseEntryRequest(
        season=SEASON, gameweek=2, league_id=LEAGUE, entry_id=ENTRY
    )


# -- a plain request is advise_entry -------------------------------------------------------


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"window": 3},
        {"strategy": "ortak-koru", "rival_entry_id": RIVAL},
        {"strategy": "fark-yarat", "rival_entry_id": RIVAL},
    ],
)
def test_a_plain_request_is_advise_entrys_own_payload(
    world: dict[str, Any], selection: dict[str, Any]
) -> None:
    collaborators = _collaborators(world)
    request = _request(**selection)
    expected = advise_entry(request.entry_request(), **collaborators)
    # Whatever the capture offers the switches, a request that asks for none ignores it.
    got = advise_menu_entry(request, **collaborators, top100_counts=world["counts"])
    assert got == expected
    assert json.dumps(got, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_a_switch_without_its_input_is_refused_by_name(world: dict[str, Any]) -> None:
    collaborators = _collaborators(world)
    with pytest.raises(MenuInputUnavailable, match="top100_counts is missing") as top100:
        advise_menu_entry(_request(top100_weight=20), **collaborators)
    assert top100.value.input_name == TOP100_COUNTS_INPUT
    with pytest.raises(MenuInputUnavailable, match="manager_words is missing") as word:
        advise_menu_entry(_request(managers_word=True), **collaborators)
    assert word.value.input_name == MANAGER_WORDS_INPUT
    assert isinstance(word.value, EntryError)
    with pytest.raises(EntryError, match="is not the capture's"):
        advise_menu_entry(
            _request(gameweek=3, strategy="ortak-koru", window=3, rival_entry_id=RIVAL),
            **collaborators,
        )


def test_a_word_that_cannot_be_applied_under_a_setting_is_refused_by_its_own_name(
    world: dict[str, Any],
) -> None:
    """The capture has the club news; this member's plan under it has no answer."""

    another_week = replace(_words(1), gameweek=3)
    with pytest.raises(ManagersWordNotSolved, match="gameweek 3, not") as refused:
        advise_menu_entry(
            _request(top100_weight=50, managers_word=True),
            **_collaborators(world),
            top100_counts=world["counts"],
            manager_words=another_week,
        )
    # Still the error every caller already catches, and not the missing-input one.
    assert isinstance(refused.value, EntryError)
    assert not isinstance(refused.value, MenuInputUnavailable)


# -- every other address is the batch's payload -------------------------------------------


def _rendered(world: dict[str, Any]) -> Any:
    task = MemberRenderTask(
        entry_id=ENTRY,
        label="member-a",
        season=SEASON,
        gameweek=2,
        league_id=LEAGUE,
        rival_ids=(RIVAL,),
        default_rival_id=RIVAL,
        rival_strategies=("ortak-koru", "fark-yarat"),
        windows=(3,),
        top100_weights=(50,),
    )
    rendered = render_member(
        task,
        provider=world["provider"],
        inputs=world["inputs"],
        projection=world["projection"],
        rules=world["rules"],
        horizon_builder=world["builder"],
        top100_counts=world["counts"],
    )
    assert rendered.baseline is not None
    assert not rendered.variant_unavailable and not rendered.top100_unavailable
    return rendered


def test_every_variant_address_is_the_batchs_payload(world: dict[str, Any]) -> None:
    rendered = _rendered(world)
    collaborators = _collaborators(world)
    addresses = {(s, w, r, t) for s, w, r, t, _ in rendered.variant_payloads}
    assert addresses == {
        ("saf-puan", 3, None, 50),
        *(
            (strategy, window, RIVAL, weight)
            for strategy in ("ortak-koru", "fark-yarat")
            for window, weight in ((1, 50), (3, 0), (3, 50))
        ),
    }
    for strategy, window, rival, weight, payload in rendered.variant_payloads:
        got = advise_menu_entry(
            _request(strategy=strategy, window=window, rival_entry_id=rival, top100_weight=weight),
            **collaborators,
            top100_counts=world["counts"],
        )
        assert got == payload, (strategy, window, rival, weight)
    for weight, word, payload in rendered.top100_payloads:
        assert not word
        got = advise_menu_entry(
            _request(top100_weight=weight),
            **collaborators,
            top100_counts=world["counts"],
        )
        assert got == payload, weight


def test_a_prerequisite_read_back_from_stored_bytes_changes_nothing(
    world: dict[str, Any],
) -> None:
    """A caller that keeps answers hands back JSON, not the dict that was serialised."""

    rendered = _rendered(world)
    collaborators = _collaborators(world)
    stored: dict[MenuRequest, str] = {
        _request(window=window): json.dumps(payload) for window, payload in rendered.window_payloads
    }
    for strategy, rival, payload in rendered.rival_payloads:
        stored[_request(strategy=strategy, rival_entry_id=rival)] = json.dumps(payload)
    for strategy, window, rival, weight, payload in rendered.variant_payloads:
        if weight == 0:
            stored[_request(strategy=strategy, window=window, rival_entry_id=rival)] = json.dumps(
                payload
            )
    asked: list[MenuRequest] = []

    def lookup(address: MenuRequest) -> dict[str, Any] | None:
        asked.append(address)
        held = stored.get(address)
        return None if held is None else json.loads(held)

    for strategy, window, rival, weight, payload in rendered.variant_payloads:
        got = advise_menu_entry(
            _request(strategy=strategy, window=window, rival_entry_id=rival, top100_weight=weight),
            **collaborators,
            top100_counts=world["counts"],
            prerequisite=lookup,
        )
        assert got == payload, (strategy, window, rival, weight)
    assert all(address.is_plain for address in asked)
    # Each dependency was asked for: the window at 0, the strategy at 0, its window at 0.
    assert {(a.strategy, a.window) for a in asked} == {
        ("saf-puan", 3),
        *((s, w) for s in ("ortak-koru", "fark-yarat") for w in (1, 3)),
    }


def test_the_word_and_the_pair_are_the_batchs_payloads(world: dict[str, Any]) -> None:
    plain = advise_entry(_request().entry_request(), **_collaborators(world))
    # A word about the captain the plain plan picks: it binds, so the word's plan is a
    # second solve and the pair's is a third.
    words = _words(int(plain["captain"]["player_id"]))  # type: ignore[index,call-overload]
    rendered = render_member(
        MemberRenderTask(
            entry_id=ENTRY,
            label="member-a",
            season=SEASON,
            gameweek=2,
            league_id=LEAGUE,
            rival_ids=(),
            default_rival_id=None,
            rival_strategies=(),
            top100_weights=(50,),
        ),
        provider=world["provider"],
        inputs=world["inputs"],
        projection=world["projection"],
        rules=world["rules"],
        manager_words=words,
        top100_counts=world["counts"],
    )
    assert rendered.evidence_payload is not None and not rendered.top100_unavailable
    assert rendered.evidence_payload["evidence"]["binding"] is True
    collaborators = {
        **_collaborators(world),
        "top100_counts": world["counts"],
        "manager_words": words,
    }

    def ask(**selection: Any) -> dict[str, object]:
        return advise_menu_entry(_request(**selection), **collaborators)

    assert ask() == rendered.baseline
    assert ask(managers_word=True) == rendered.evidence_payload
    by_address = {(weight, word): payload for weight, word, payload in rendered.top100_payloads}
    assert set(by_address) == {(50, False), (50, True)}
    assert ask(top100_weight=50) == by_address[(50, False)]
    assert ask(top100_weight=50, managers_word=True) == by_address[(50, True)]
