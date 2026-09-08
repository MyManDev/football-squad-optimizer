"""Resolve a claim that names a player in text to the persistent code it means.

A club's own words name a player the way a person would -- "Saka", "Bukayo Saka",
"Fernandes" -- and everything downstream keys on the platform's persistent ``code``. This
module is the bridge, and it sits beside :mod:`squadopt.data.identity` for the same reason
that one gives: a reconciliation knows two sides, so it lives above the adapters that each
know one.

**It refuses rather than guesses, and refusing is a result, not a crash.** Ambiguity here is
a real state, not a failure: a bare surname two players in one club share is exactly what a
press conference produces, and picking the more famous of them would attribute a manager's
words to the wrong person. So the resolver returns an outcome. A caller drops the claim it
could not resolve and counts it; nothing raises, because a claim nobody can place must not
take the week's whole export with it.

Three unresolved reasons, and they are kept apart because they mean different things: the
claim named a club the roster does not carry, the club is there and the name matches nobody,
or the name matches more than one player. Only the third is ambiguity, and only the second
means the model named somebody who is not in the game.

**Two tiers, and the second is not a guess.** An exact match on the normalised short name
comes first. Failing that, a match on the *surname* within the same club -- and a **unique**
surname inside one squad is the same person, not a likelier one. A surname that is not
unique refuses. That is the whole rule; there is no third tier, no scoring and no
approximate matching. The repository has never carried a text-similarity library and this
does not add one: a near match is precisely the guess the lane forbids.

``opta_code`` is present and unique on every element the platform publishes, and is read
nowhere in this repository. It is the exact join key a licensed provider would hand us, and
it is noted here rather than built on: a name join is what an unlicensed source leaves us.
"""

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataValidationError
from squadopt.data.sources.club_news import RosterPlayer

#: The normalisation rule, versioned. Changing how names are folded changes which claims
#: resolved yesterday, so a stored resolution is only reproducible beside the rule's name.
CLAIM_NAME_FOLD_VERSION: Final = "claim_name_fold_v1"

#: Why a claim could not be placed. Three states, never collapsed into one another.
UNRESOLVED_REASONS: Final[tuple[str, ...]] = ("unknown_team", "no_match", "ambiguous")

#: Which tier resolved a claim, so a caller can record it.
MATCH_BASES: Final[tuple[str, ...]] = ("web_name", "surname")

#: Characters that separate the parts of a published short name. The platform writes an
#: initial-and-surname as ``B.Fernandes`` while a person writes ``Bukayo Saka``, so both
#: the dot and the space have to end a part -- and the dot has to be a separator rather
#: than punctuation to strip, or ``B.Fernandes`` would fold to one word and its surname
#: would be lost.
#: The curly apostrophe is spelled as an escape rather than typed: it is the one a club's
#: own page actually publishes, and a linter cannot tell it from the straight one on sight.
_NAME_SEPARATORS: Final = ".-' \u2019\t\n"


#: Letters that carry no combining mark for decomposition to drop, folded to what
#: English-language football coverage writes -- which is the vocabulary this join actually
#: meets, on a club's own page and in the platform's payload. A closed table, following the
#: same shape as ``data/schema.py``'s position aliases: nine entries, each restatable, and
#: nothing outside it is touched. This is not transliteration and is not a substitute for
#: it; a Norwegian spelling of ``\u00f8`` as ``oe`` is a different convention and would be a
#: different table, which is why an unlisted letter refuses instead of being guessed at.
_UNDECOMPOSED_LETTERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "\u00d8": "O",
        "\u00f8": "o",
        "\u00c6": "AE",
        "\u00e6": "ae",
        "\u0152": "OE",
        "\u0153": "oe",
        "\u00df": "ss",
        "\u00d0": "D",
        "\u00f0": "d",
        "\u00de": "TH",
        "\u00fe": "th",
        "\u0110": "D",
        "\u0111": "d",
        "\u0141": "L",
        "\u0142": "l",
    }
)


def normalise_claim_name(value: str) -> str:
    """Fold one name to the form both sides of the join are compared in.

    Decomposed, stripped of combining marks, case-folded, punctuation turned into spaces
    and runs of space collapsed. So ``Ødegaard``, ``ODEGAARD`` and ``  odegaard `` all
    arrive at one key, and a club page written in NFC matches a payload written in NFD.

    Marks are dropped rather than transliterated, which is a rule anyone can restate. It
    does not reach every letter: a stroke or a ligature is one code point with no combining
    mark to drop, so ``Ødegaard`` would survive decomposition intact and never meet a page
    that writes ``Odegaard``. Those letters get the closed table below -- and only those.
    An unlisted letter is left alone and the claim refuses, which is the right side to fail
    on: refusing loses a claim, a wrong fold attributes a manager's words to another player.
    """

    decomposed = unicodedata.normalize("NFKD", value)
    kept: list[str] = []
    for character in decomposed:
        if unicodedata.combining(character):
            continue
        if character in _NAME_SEPARATORS:
            kept.append(" ")
            continue
        kept.append(_UNDECOMPOSED_LETTERS.get(character, character))
    folded = "".join(kept).casefold()
    return " ".join(folded.split())


def claim_surname(value: str) -> str:
    """Return the last part of a normalised name: what a claim usually calls a player.

    Defined once and deliberately, because the fixture's own collision case turns on it:
    ``B.Fernandes`` and ``A.Fernandes`` differ in a part that a bare ``Fernandes`` does not
    carry, so the dot has to separate parts for the surname to be found at all -- and once
    it does, both roster entries share the surname and the join has to refuse.
    """

    parts = normalise_claim_name(value).split()
    return parts[-1] if parts else ""


@dataclass(frozen=True, slots=True)
class ResolvedClaim:
    """The claim named exactly one player, and which tier said so."""

    player_id: int
    matched_on: str

    def __post_init__(self) -> None:
        if self.matched_on not in MATCH_BASES:
            raise ValueError(f"matched_on must be one of {MATCH_BASES!r}, got {self.matched_on!r}.")


@dataclass(frozen=True, slots=True)
class UnresolvedClaim:
    """The claim could not be placed, and the reason is part of the answer.

    ``candidates`` carries the colliding player codes when the reason is ambiguity, so a
    diagnostic can name both sides the way the rest of this layer's refusals do. It is
    empty for the other two reasons, where there is no candidate to name.
    """

    reason: str
    candidates: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.reason not in UNRESOLVED_REASONS:
            raise ValueError(f"reason must be one of {UNRESOLVED_REASONS!r}, got {self.reason!r}.")
        if self.reason != "ambiguous" and self.candidates:
            raise ValueError(
                f"Only an ambiguous claim names candidates; {self.reason!r} carries "
                f"{self.candidates!r}."
            )
        if self.reason == "ambiguous" and len(self.candidates) < 2:
            raise ValueError(
                "An ambiguous claim needs at least two candidates; one candidate is a "
                f"resolution, and {self.candidates!r} names fewer than two."
            )


#: What the resolver answers. A caller reads the type, not a flag.
ClaimIdentity = ResolvedClaim | UnresolvedClaim


def resolve_claim_player(
    name: str, team_name: str, roster: Sequence[RosterPlayer]
) -> ClaimIdentity:
    """Resolve one claim's named player against the roster of the club it is about.

    The club narrows the search before the name is looked at, which is what makes the join
    tractable at all: across a whole roster a bare surname is ambiguous for dozens of
    players, and inside one squad it is almost always unique. The fetch is per club, so the
    club is always known.
    """

    club = normalise_claim_name(team_name)
    squad = [player for player in roster if normalise_claim_name(player.team_name) == club]
    if not squad:
        return UnresolvedClaim(reason="unknown_team")

    wanted = normalise_claim_name(name)
    if not wanted:
        return UnresolvedClaim(reason="no_match")

    exact = [player for player in squad if normalise_claim_name(player.web_name) == wanted]
    if len(exact) == 1:
        return ResolvedClaim(player_id=exact[0].player_id, matched_on="web_name")
    if len(exact) > 1:
        return UnresolvedClaim(
            reason="ambiguous", candidates=tuple(sorted(player.player_id for player in exact))
        )

    surname = claim_surname(name)
    by_surname = [player for player in squad if claim_surname(player.web_name) == surname]
    if len(by_surname) == 1:
        return ResolvedClaim(player_id=by_surname[0].player_id, matched_on="surname")
    if len(by_surname) > 1:
        return UnresolvedClaim(
            reason="ambiguous", candidates=tuple(sorted(player.player_id for player in by_surname))
        )
    return UnresolvedClaim(reason="no_match")


def roster_from_short_names(frame: pd.DataFrame) -> tuple[RosterPlayer, ...]:
    """Turn :func:`squadopt.data.sources.fpl_live.short_name_roster`'s table into the seam's shape.

    The bridge sits here rather than in the source adapter, so that adapter keeps knowing
    exactly one source and does not learn the club-news seam's types. It is the same
    reasoning that keeps this whole module out of ``sources/``.
    """

    if not isinstance(frame, pd.DataFrame):
        raise DataValidationError("A short-name roster must be a pandas DataFrame.")
    missing = [
        column for column in ("player_id", "web_name", "team_name") if column not in frame.columns
    ]
    if missing:
        raise DataValidationError(f"A short-name roster is missing columns {missing!r}.")
    # Columns are pulled out as typed lists rather than walked with itertuples(), whose
    # rows carry no element type and so cannot be narrowed without a cast.
    identifiers = frame["player_id"].astype("int64").tolist()
    short_names = frame["web_name"].astype("string").tolist()
    clubs = frame["team_name"].astype("string").tolist()
    return tuple(
        RosterPlayer(player_id=int(identifier), web_name=str(short_name), team_name=str(club))
        for identifier, short_name, club in zip(identifiers, short_names, clubs, strict=True)
    )
