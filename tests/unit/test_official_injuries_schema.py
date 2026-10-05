"""The public projection validates without source bytes or internal provenance."""

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from tests.unit.test_official_injuries import report

from squadopt.contracts.injuries import official_injuries_schema


@pytest.mark.parametrize("selected", [[], [10]])
def test_actual_public_projection_matches_schema(selected):
    Draft202012Validator(official_injuries_schema(), format_checker=FormatChecker()).validate(
        report().public_record(selected)
    )


@pytest.mark.parametrize("extra", ["source_span", "raw_quote", "page_sha256"])
def test_schema_refuses_internal_fact_fields(extra):
    value = report().public_record([10])
    value["facts"][0][extra] = "not public"
    with pytest.raises(ValidationError):
        Draft202012Validator(official_injuries_schema()).validate(value)


def test_schema_preserves_noninstant_source_date_and_refuses_unsafe_link():
    value = report().public_record([10])
    value["facts"][0]["source_date"] = "September 2026"
    validator = Draft202012Validator(official_injuries_schema())
    validator.validate(value)
    value["facts"][0]["details_urls"] = ["javascript:alert(1)"]
    with pytest.raises(ValidationError):
        validator.validate(value)
