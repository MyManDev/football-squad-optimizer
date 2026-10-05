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
CLAIM_SCOPE_VERSION = "source_fixture_scope_v2"
_NOUN = r"(?:match|game|fixture)"
_MATCH = rf"(?:the )?(?:upcoming|next) (?:premier )?league {_NOUN}"


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
            rf"\b(?:previous|last|yesterday's) (?:premier )?league {_NOUN}\b|\byesterday\b",
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
    upcoming = bool(re.search(rf"\b(?:upcoming|next) (?:premier )?league {_NOUN}\b", text))
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
        rf"(?:(?:will miss|misses) {_MATCH}"
        rf"|will play no part in {_MATCH}"
        rf"|(?:will not|won't|cannot|can't) (?:play|feature|travel|be available) "
        rf"(?:(?:in|for|to) )?{_MATCH}"
        rf"|(?:is not|isn't) available for {_MATCH}"
        rf"|(?:is|has been|will be) (?:ruled out|unavailable|out|sidelined) (?:for|of) {_MATCH})"
    )
    if disposition == "stated_expected_absent" and not _named_clause(text, player_name, absence):
        return "ambiguous", False
    rotation = rf"(?:is a rotation risk|will be (?:rested|rotated)) (?:for|in) {_MATCH}"
    if disposition == "stated_rotation_risk" and not _named_clause(text, player_name, rotation):
        return "ambiguous", False
    return "upcoming_premier_league", True


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
    direct = rf"{inability}{full} (?:upcoming|next) (?:premier )?league {_NOUN}"
    followed = rf"{inability}(?:{full} (?:match|game)|{minutes}) (?:in|during|of) {_MATCH}"
    if _named_clause(text, player_name, rf"(?:{direct}|{followed})"):
        return True
    context = re.match(rf"^(?:in|for|during) {_MATCH}, ", text)
    return context is not None and _named_clause(
        text[context.end() :], player_name, rf"{inability}(?:{full} (?:match|game)|{minutes})"
    )
