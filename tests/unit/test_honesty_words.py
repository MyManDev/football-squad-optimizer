"""Both engines derive their vocabulary from one plain-string contract."""

import json
from pathlib import Path

import pytest

from squadopt.application.manager_words import QUOTE_WITHHELD_PATTERN
from squadopt.application.strategies.catalog import FORBIDDEN_TEXT_PATTERN
from squadopt.contracts.honesty_stems import EN_STEMS, TR_STEMS

ROOT = Path(__file__).resolve().parents[2]
WORDS = json.loads((ROOT / "docs/contracts/honesty_words.json").read_text(encoding="utf-8"))


def test_packaged_stems_match_the_shared_contract() -> None:
    assert {"en": list(EN_STEMS), "tr": list(TR_STEMS)} == WORDS["stems"], (
        "Regenerate with python scripts/generate_honesty_stems.py"
    )


@pytest.mark.parametrize("stem", [stem for stems in WORDS["stems"].values() for stem in stems])
def test_every_shared_stem_is_forbidden(stem: str) -> None:
    assert FORBIDDEN_TEXT_PATTERN.search(stem)


@pytest.mark.parametrize("copy", [copy for lines in WORDS["allowed"].values() for copy in lines])
def test_shared_factual_sentences_are_allowed(copy: str) -> None:
    assert not FORBIDDEN_TEXT_PATTERN.search(copy)


@pytest.mark.parametrize("ownership", ["owned", "ownership", "sahipli"])
@pytest.mark.parametrize("distance", [0, 40, 41])
@pytest.mark.parametrize("before", [False, True])
def test_ownership_exception_distance(ownership: str, distance: int, before: bool) -> None:
    padding = "\n" * distance
    copy = ownership + padding + "%" if before else "%" + padding + ownership
    assert bool(FORBIDDEN_TEXT_PATTERN.search(copy)) == (distance > 40)
    assert QUOTE_WITHHELD_PATTERN.search(copy)  # Ownership never excuses a quote's percent.


@pytest.mark.parametrize(
    "copy", ["şansl\u0131", "ihtimali", "yüzdesi", "yüzdelik", "spread", "25%"]
)
def test_inflections_and_bare_percent_are_forbidden(copy: str) -> None:
    assert FORBIDDEN_TEXT_PATTERN.search(copy)


def test_ownership_does_not_excuse_another_forbidden_word() -> None:
    assert FORBIDDEN_TEXT_PATTERN.search("12% ownership, lower tail")
