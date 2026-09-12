"""The served advice contract, tied to the strategy envelope at the field names.

``PUBLISHABLE_FIELDS`` is the authority on what a strategy may publish; the schema the
api and the static site serve re-spells those names by hand, and its payload keeps
``additionalProperties`` open. This is the seam between the two: a name the schema
declares is either publishable or one of the envelope names admitted below, by hand,
each with its reason — so a field can only reach the contract on purpose.
"""

import json
import re
from collections.abc import Iterator
from typing import Any, Final

from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN, PUBLISHABLE_FIELDS
from squadopt.platform.advice_documents import ADVICE_READ_SCHEMA_PATH

#: Names the served document carries that no strategy publishes: the address of the
#: answer, its provenance, and the producer's own account of its inputs.
ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "season",  # address: the season the week belongs to
        "gameweek",  # address: the week the advice is for
        "entry_id",  # address: whose squad the advice stands on
        "league_id",  # address: whose rivals it was solved against
        "mode",  # address: the strategy slug the document answers for
        "window",  # address: how many weeks the plan spans (1, 3, 5)
        "source_snapshot_id",  # provenance: the capture the advice was computed from
        "rival_entry_id",  # provenance: the rival the strategy was solved against
        "rival_label",  # provenance: that rival's display name, or null
        "data_quality",  # the producer's account of what it could read
        "missing_fields",  # the inputs it could not read, by name
    }
)


def _payload_schema() -> dict[str, Any]:
    document = json.loads(ADVICE_READ_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload: dict[str, Any] = document["properties"]["payload"]
    return payload


def _declared_names(schema: object) -> Iterator[str]:
    """Every property name the schema declares, at any depth."""

    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            yield from properties
        for value in schema.values():
            yield from _declared_names(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _declared_names(value)


def test_every_payload_name_the_schema_declares_is_publishable_or_admitted_here() -> None:
    declared = frozenset(_payload_schema()["properties"])

    assert declared - PUBLISHABLE_FIELDS - ENVELOPE_FIELDS == frozenset()
    # The admitted list cannot hide a publishable name, and cannot rot past the schema.
    assert ENVELOPE_FIELDS.isdisjoint(PUBLISHABLE_FIELDS)
    assert declared >= ENVELOPE_FIELDS


def test_the_required_core_is_the_envelope_plus_the_moves() -> None:
    required = frozenset(_payload_schema()["required"])

    assert required <= ENVELOPE_FIELDS | {"moves"}


def test_no_declared_name_reads_as_a_probability() -> None:
    """The envelope's stop-rule, applied to the served contract at every depth."""

    names = sorted(set(_declared_names(_payload_schema())))

    assert names, "the schema declares no properties at all"
    assert [name for name in names if re.search(FORBIDDEN_FIELD_PATTERN, name)] == []
