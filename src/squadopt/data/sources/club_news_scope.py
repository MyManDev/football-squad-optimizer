"""Conservative competition/time scope from a cited sentence, not model confidence."""

import re

from squadopt.data.sources.club_news import ROTATION_DISPOSITIONS

FIXTURE_SCOPES = (
    "upcoming_premier_league",
    "other_competition",
    "past",
    "ambiguous",
    "unspecified",
)
CLAIM_SCOPE_VERSION = "source_fixture_scope_v1"
_MATCH = r"(?:the )?(?:upcoming|next) (?:premier )?league (?:match|game)"

#: What may stand between a sentence boundary and the quote: space, and a quotation mark
#: or bracket that opens (before) or closes (after) the sentence the quote is.
_SPACE = " \t"
_MARKS = "\"'\u201c\u201d\u2018\u2019()[]"
_SENTENCE_END = ".!?"
_BOUNDARY = _SENTENCE_END + "\n\r"
#: What may stand before the quoted statement: a boundary, or the colon that introduces
#: reported words ("Arteta said: ...", "Coach: ...").
_OPENING = _BOUNDARY + ":"
#: What may close the quoted statement itself: a period, an exclamation mark or a line end.
_STATEMENT_END = ".!\n\r"


def verified_fixture_scope(
    quote: bytes, disposition: str, *, player_name: str | None = None
) -> tuple[str, bool]:
    """Only explicit unconditional upcoming league wording can authorize a change.

    Unrecognised wording remains unverified. This is deliberately a finite English
    rule, not a claim to resolve arbitrary natural-language fixture references.
    """
    if disposition not in ROTATION_DISPOSITIONS:
        return "ambiguous", False
    try:
        text = " ".join(quote.decode("utf-8").casefold().replace("\u2019", "'").split())
    except UnicodeError:
        return "ambiguous", False
    if re.search(
        r"\b(?:if|unless|might|may|could|unlikely|perhaps|possibly|unclear|uncertain)\b"
        r"|\b(?:not true|not saying|did not say|didn't say|no longer|not the case|not ruled out)\b",
        text,
    ):
        return "ambiguous", False
    past = bool(
        re.search(
            r"\b(?:previous|last|yesterday's) (?:premier )?league (?:match|game)\b|\byesterday\b",
            text,
        )
    )
    other = bool(
        re.search(
            r"\b(?:cup|champions league|europa league|conference league|national team|"
            r"internationals?|nations league|friendly|friendlies|qualifiers?|qualifying)\b",
            text,
        )
    )
    upcoming = bool(re.search(r"\b(?:upcoming|next) (?:premier )?league (?:match|game)\b", text))
    if past or other:
        return ("ambiguous" if upcoming else "past" if past else "other_competition"), False
    if not upcoming:
        return "unspecified", False
    if disposition in ("stated_expected_absent", "stated_full_match_unavailable") and re.search(
        r"\b(?:training|rehabilitation|workout|session)\b", text
    ):
        return "ambiguous", False
    if disposition == "stated_full_match_unavailable" and not _full_match_inability(
        text, player_name
    ):
        return "ambiguous", False
    if disposition == "stated_expected_absent" and re.search(
        r"\b(?:full|whole|entire|ninety|90|minutes|start|starting|bench|cameo)\b", text
    ):
        return "ambiguous", False
    absence = (
        rf"(?:will miss {_MATCH}"
        rf"|(?:will not|won't|cannot|can't) (?:play|feature|travel|be available) "
        rf"(?:(?:in|for|to) )?{_MATCH}"
        rf"|(?:is|has been|will be) (?:ruled out|unavailable|out) (?:for|of) {_MATCH})"
    )
    if disposition == "stated_expected_absent" and not _named_clause(text, player_name, absence):
        return "ambiguous", False
    rotation = rf"(?:is a rotation risk|will be (?:rested|rotated)) (?:for|in) {_MATCH}"
    if disposition == "stated_rotation_risk" and not _named_clause(text, player_name, rotation):
        return "ambiguous", False
    return "upcoming_premier_league", True


def is_whole_sentence(text: bytes, first: int, last: int) -> bool:
    """Whether ``text[first:last]`` is a complete sentence of ``text``, not part of one.

    :func:`verified_fixture_scope` reads the quote alone, and "Saka will miss the next
    Premier League match." is also a substring of "It is not true that Saka will miss the
    next Premier League match." So a claim's scope is verified only where the source's own
    text bounds the quote: before it, the start of the text, a line break, the end of a
    sentence or the colon that introduces reported words; after it, the end of the text, a
    line break or the end of a sentence. A question mark is not the end of a statement, and
    an ellipsis is not the end of anything.

    The manager-word reader holds a copy of this rule
    (``squadopt.application.manager_words._is_whole_sentence``), and the two must agree: a
    table flag set by one definition and refused by the other says something no consumer
    acts on. A test holds both copies to the same answers.
    """
    try:
        before = text[:first].decode("utf-8")
        quoted = text[first:last].decode("utf-8")
        after = text[last:].decode("utf-8")
    except UnicodeDecodeError:
        return False
    lead = before.rstrip(_SPACE).rstrip(_MARKS).rstrip(_SPACE)
    if lead and lead[-1] not in _OPENING:
        return False
    rest = after.lstrip(_SPACE).lstrip(_MARKS).lstrip(_SPACE)
    if rest.startswith((".", "\u2026")):
        # "... if he fails a late test": the sentence goes on, whatever the quote ends with.
        return False
    core = quoted.strip().rstrip(_MARKS)
    if core.endswith(("..", "\u2026")):
        return False
    if core.endswith((".", "!")):
        return True
    if core.endswith("?") or rest.startswith("?"):
        return False
    return not rest or rest[0] in _STATEMENT_END


def _named_clause(text: str, player_name: str | None, predicate: str) -> bool:
    """Require the named subject and predicate to occupy the entire cited clause.

    No inferred surname, pronoun or substring aliases: callers use the coded name,
    and the artifact reader independently uses the captured roster's exact name.
    Unknown name variants remain readable evidence without authority to constrain a plan.
    """
    if not player_name or not player_name.strip():
        return False
    name = " ".join(player_name.casefold().replace("\u2019", "'").split())
    return re.fullmatch(rf"{re.escape(name)} {predicate}[.!]?", text) is not None


def _full_match_inability(text: str, player_name: str | None) -> bool:
    """Require the named player's inability and the match in one complete clause."""
    inability = (
        r"(?:cannot|can't|will not(?: be able to)?|won't(?: be able to)?|is unable to) "
        r"(?:complete|finish|play|last) (?:the )?"
    )
    full = r"(?:full|whole|entire)"
    minutes = r"(?:full )?(?:90|ninety) minutes"
    direct = rf"{inability}{full} (?:upcoming|next) (?:premier )?league (?:match|game)"
    followed = rf"{inability}(?:{full} (?:match|game)|{minutes}) (?:in|during|of) {_MATCH}"
    if _named_clause(text, player_name, rf"(?:{direct}|{followed})"):
        return True
    context = re.match(rf"^(?:in|for|during) {_MATCH}, ", text)
    return context is not None and _named_clause(
        text[context.end() :], player_name, rf"{inability}(?:{full} (?:match|game)|{minutes})"
    )
