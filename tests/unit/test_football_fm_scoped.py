"""Temporal full-export FM scoping and its actual UnitInputCatalog handoff."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest
from tests.unit.test_football_fm_attributes import CSV, CUTOFF, _source, _specs

from squadopt.features.football_fm_attributes import (
    FM_SCOPED_ATTRIBUTES_VERSION,
    read_fm_attributes,
    read_scoped_fm_attributes,
)
from squadopt.features.football_unit_inputs import (
    ClubUnit,
    PlayerMapping,
    UnitInputCatalog,
    UnitPlayer,
)


def mapping(uid="1001", player=1, club=10, **changes):
    return replace(
        PlayerMapping(
            "synthetic-fm-export",
            uid,
            player,
            club,
            CUTOFF - timedelta(days=1),
            CUTOFF + timedelta(days=1),
        ),
        **changes,
    )


DEFAULT_MAPPINGS = (mapping(),)


def scoped(mappings=DEFAULT_MAPPINGS, payload=CSV, **options):
    arguments = dict(
        source=_source(payload),
        cutoff=CUTOFF,
        mappings=mappings,
        attributes=_specs(),
        attribute_columns={"heading": "Heading", "positioning": "Positioning"},
        uid_column="UID",
    )
    return read_scoped_fm_attributes(payload, **(arguments | options))


def test_only_active_exact_uids_leave_the_full_export_and_unknowns_stay_unknown():
    result = scoped(
        (
            mapping("1004", 4),
            mapping("1002", 2),
            mapping("1003", 3, valid_from=CUTOFF + timedelta(seconds=1)),
        )
    )
    assert result.contract_version == FM_SCOPED_ATTRIBUTES_VERSION
    assert result.source_player_count == 4
    assert [r.source_player_id for r in result.player_attributes] == ["1002", "1004"]
    assert [r.source_player_id for r in result.mappings] == ["1002", "1004"]
    assert dict(result.player_attributes[0].values) == {"heading": None, "positioning": 20.0}
    assert all(value is None for _, value in result.player_attributes[1].values)
    assert result.cutoff == CUTOFF
    assert result.source == _source(CSV)
    with pytest.raises(FrozenInstanceError):
        result.cutoff = CUTOFF + timedelta(days=1)


def test_a_transfer_selects_the_exact_nonoverlapping_club_interval():
    before = mapping(valid_until=CUTOFF - timedelta(microseconds=1))
    now = mapping(club=20, valid_from=CUTOFF)
    result = scoped((before, now))
    assert result.mappings == (now,)
    assert result.mappings[0].club == 20
    assert len(result.player_attributes) == 1


@pytest.mark.parametrize(
    "mappings,reason",
    [
        ((), "immutable"),
        ([mapping()], "immutable"),
        ((None,), "exact supplied source"),
        ((mapping(source_id="another-edition"),), "exact supplied source"),
        ((mapping(uid="01001"),), "canonical"),
        ((mapping(), mapping()), "overlapping"),
        ((mapping(), mapping(club=20, valid_from=CUTOFF)), "overlapping"),
        ((mapping(), mapping("1002", 1, 20)), "two FM UIDs"),
        ((mapping(valid_until=CUTOFF - timedelta(seconds=1)),), "No supplied"),
        ((mapping(valid_from=CUTOFF + timedelta(seconds=1)),), "No supplied"),
    ],
)
def test_invalid_scopes_refuse_before_payload_decoding(mappings, reason):
    with pytest.raises(ValueError, match=reason):
        scoped(mappings, payload=b"not csv", source=_source(CSV))


def test_inactive_overlapping_source_intervals_are_not_hidden_by_the_current_cutoff():
    old = mapping(valid_from=CUTOFF - timedelta(days=10), valid_until=CUTOFF - timedelta(days=5))
    with pytest.raises(ValueError, match="overlapping"):
        scoped((old, replace(old, club=20), mapping()))


def test_source_unavailable_at_cutoff_refuses_before_csv_decoding():
    with pytest.raises(ValueError, match="unavailable"):
        scoped(payload=b"not csv", source=_source(CSV, captured_at=CUTOFF + timedelta(seconds=1)))


def test_a_mapped_uid_missing_from_the_actual_bytes_refuses():
    with pytest.raises(ValueError, match="absent from the verified export"):
        scoped((mapping("9999"),))


def test_filtering_does_not_skip_hash_or_unselected_row_validation():
    with pytest.raises(ValueError, match="SHA256"):
        scoped(payload=CSV + b"1005,Extra,5,5,20\n", source=_source(CSV))
    with pytest.raises(ValueError, match="1 to 20"):
        scoped(payload=CSV + b"1005,Extra,21,5,20\n")
    with pytest.raises(ValueError, match="conflicting"):
        scoped(payload=CSV + b"1004,Extra,5,5,20\n")


def test_scoped_rows_enter_the_catalog_while_the_wide_unmapped_export_refuses():
    result = scoped((mapping(), mapping("1002", 12, 20)))
    base = replace(_source(CSV), source_id="native", kind="provider", provider="fictional-native")
    baseline_mappings = tuple(
        PlayerMapping(
            "native",
            str(p),
            p,
            10 if p <= 11 else 20,
            CUTOFF - timedelta(days=1),
            CUTOFF + timedelta(days=1),
        )
        for p in range(1, 23)
    )
    arguments = dict(
        season="2024-25",
        gameweek=1,
        fixture_id=1,
        decision_cutoff=CUTOFF,
        sources=(base, result.source),
        attributes=_specs(),
        mappings=baseline_mappings + result.mappings,
        baseline_source_id="native",
        reference_source_id="native",
        projection_source_id="native",
    )
    catalog = UnitInputCatalog(**arguments, player_attributes=result.player_attributes)
    catalog.validate_unit(
        ClubUnit(10, tuple(UnitPlayer(p, "GK" if p == 1 else "DEF") for p in range(1, 12)))
    )
    assert catalog.value(1, _specs()[0]) == 12
    assert catalog.value(12, _specs()[0]) is None
    assert catalog.value(11, _specs()[0]) is None
    full = read_fm_attributes(
        CSV,
        source=_source(CSV),
        cutoff=CUTOFF,
        attributes=_specs(),
        attribute_columns={"heading": "Heading", "positioning": "Positioning"},
        uid_column="UID",
    )
    with pytest.raises(ValueError, match="one active persistent player mapping"):
        UnitInputCatalog(**arguments, player_attributes=full)
