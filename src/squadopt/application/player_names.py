"""The short name a published page shows for a player: the one the game itself shows.

Every published player record carries two names: ``name``, the full name the capture's
``first_name`` and ``second_name`` join into, and ``short_name``, the label a pitch plate
or a list has room for. The short name used to be cut from the full name, its last word,
which is how the pages came to call Igor Thiago "Rodrigues", João Pedro "Jesus" and
David Raya "Martín". The bootstrap also publishes ``web_name``, the name the game's own
pages use and the one a member knows the player by, so that is the label published.

It is set where a document is written, not carried through the projection: the planners
never read a name, and the projection's tables are part of what they fingerprint. A
player the bootstrap gives no ``web_name`` keeps the label he had; a label is not worth
refusing a publication over.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import pandas as pd

#: Letters the decomposition below leaves whole, folded by hand to the letter the game
#: writes for them, so ``Odegaard`` still meets ``Ødegaard``. One letter for one letter:
#: a word whose folded length changed could not be spelled back position by position.
#: The dotless i is written as its escape, the one letter here a reader could take for
#: another.
_SINGLE_LETTER_FOLDS: Final = str.maketrans(
    {"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "\u0131": "i"}
)

#: A run of letters: the unit a short name and a full name are compared in.
_WORD: Final = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True, slots=True)
class GameName:
    """One player's two names as a capture states them."""

    name: str
    """The full name, exactly as the capture's roster carries it."""
    short_name: str
    """The game's ``web_name``, with the full name's accents (:func:`with_full_name_accents`)."""


def _folded(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.translate(_SINGLE_LETTER_FOLDS))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def with_full_name_accents(short: str, full: str) -> str:
    """``short`` with the accents ``full`` spells its words with.

    The game writes some short names without the accents its own full name keeps:
    ``Kinsky`` for Antonín Kinský, ``Vuskovic`` for Luka Vušković. A word of the short
    name that matches exactly one word of the full name, letter for letter once accents
    are set aside, takes that word's accent on each letter the game wrote plain. Accents
    are only ever added: the game writes ``Šeško`` where the full name has ``Sesko``, and
    that letter keeps the game's accent. Every letter keeps its own capital, and the
    initials, dots and spaces of ``B.Fernandes`` or ``Bruno G.`` stay as the game wrote
    them.
    """

    spellings: dict[str, set[str]] = {}
    for word in _WORD.findall(full):
        spellings.setdefault(_folded(word), set()).add(word)

    def spelled(match: re.Match[str]) -> str:
        word = match.group(0)
        candidates = spellings.get(_folded(word), set())
        if len(candidates) != 1:
            return word
        (accented,) = candidates
        if len(accented) != len(word):
            return word
        return "".join(
            (letter.upper() if own.isupper() else letter.lower())
            if _folded(own) == own.casefold()
            else own
            for own, letter in zip(word, accented, strict=True)
        )

    return _WORD.sub(spelled, short)


def game_names(bootstrap: bytes, players: pd.DataFrame) -> dict[int, GameName]:
    """Each rostered player's names, keyed by the persistent ``code`` pages use.

    ``players`` is the roster the publication read out of the same capture
    (``RecommendationInputs.players``): its ``name`` is the one every published record
    carries, so it is the name a record is matched on. The bootstrap is read here only for
    ``web_name``, keyed on the same ``code``.
    """

    short: dict[int, str] = {}
    for record in json.loads(bootstrap).get("elements", []):
        code, web_name = record.get("code"), record.get("web_name")
        if isinstance(code, int) and isinstance(web_name, str) and web_name.strip():
            short[code] = web_name.strip()
    return {
        int(code): GameName(str(name), with_full_name_accents(short[int(code)], str(name)))
        for code, name in zip(players["player_id"], players["name"], strict=True)
        if int(code) in short
    }


def with_game_short_names(
    document: Mapping[str, object], names: Mapping[int, GameName]
) -> Mapping[str, object]:
    """``document`` with every player record's ``short_name`` set to the game's.

    A player record is a mapping with ``name``, ``short_name`` and ``position``, keyed by
    his code under ``player_id`` (the league documents) or ``id`` (the device-plan
    tables). One whose code ``names`` does not hold, or whose ``name`` is not the name the
    capture gives that code, is left as it is: the label follows the identity, never the
    other way round. With no names the document itself is returned, so its bytes cannot
    move.
    """

    if not names:
        return document

    def relabelled(value: object) -> object:
        if isinstance(value, Mapping):
            record = {key: relabelled(item) for key, item in value.items()}
            code = record.get("player_id", record.get("id"))
            if (
                "short_name" in record
                and "position" in record
                and isinstance(code, int)
                and not isinstance(code, bool)
            ):
                known = names.get(code)
                if known is not None and record.get("name") == known.name:
                    record["short_name"] = known.short_name
            return record
        if isinstance(value, list | tuple):
            return [relabelled(item) for item in value]
        return value

    return {key: relabelled(item) for key, item in document.items()}
