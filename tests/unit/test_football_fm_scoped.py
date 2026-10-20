"""Temporal full-export FM scoping and its actual UnitInputCatalog handoff."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone

import pytest
from tests.unit.test_football_fm_attributes import CSV, CUTOFF, _source, _specs

from squadopt.features.football_fm_attributes import (
    FM_SCOPED_ATTRIBUTES_VERSION,
    read_fm_attributes,
    read_scoped_fm_attributes,
)
from squadopt.features.football_unit_inputs import (
    ClubUnit,
    PlayerAttributes,
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


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"source": _source(CSV, kind="provider")}, "explicit FM source"),
        ({"cutoff": CUTOFF.replace(tzinfo=None)}, "explicit timezone"),
        ({"source": _source(CSV, valid_until=CUTOFF - timedelta(seconds=1))}, "stale"),
    ],
)
def test_scoped_source_and_clock_refusals_precede_csv_decoding(options, reason):
    with pytest.raises(ValueError, match=reason):
        scoped(payload=b"not csv", **options)


def test_scoped_reader_passes_explicit_unnamed_index_policy_to_the_full_reader():
    payload = b",UID,Heading,Positioning\n0,1001,12,14\n"
    with pytest.raises(ValueError, match="named header"):
        scoped(payload=payload)
    with pytest.raises(ValueError, match="explicit boolean"):
        scoped(payload=payload, allow_unnamed_index=1)
    result = scoped(payload=payload, allow_unnamed_index=True)
    assert dict(result.player_attributes[0].values) == {"heading": 12.0, "positioning": 14.0}


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


def base_catalog():
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
    return UnitInputCatalog(
        season="2024-25",
        gameweek=1,
        fixture_id=1,
        decision_cutoff=CUTOFF,
        sources=(base,),
        attributes=(),
        mappings=baseline_mappings,
        player_attributes=(),
        baseline_source_id="native",
        reference_source_id="native",
        projection_source_id="native",
    )


def test_scoped_rows_enter_the_catalog_while_the_wide_unmapped_export_refuses():
    result = scoped((mapping(), mapping("1002", 12, 20)))
    original = base_catalog()
    catalog = result.add_to_catalog(original, attributes=_specs())
    catalog.validate_unit(
        ClubUnit(10, tuple(UnitPlayer(p, "GK" if p == 1 else "DEF") for p in range(1, 12)))
    )
    assert catalog.value(1, _specs()[0]) == 12
    assert catalog.value(12, _specs()[0]) is None
    assert catalog.value(12, _specs()[1]) == 20
    assert catalog.value(11, _specs()[0]) is None
    assert original.sources == catalog.sources[:1]
    assert original.player_attributes == ()
    full = read_fm_attributes(
        CSV,
        source=_source(CSV),
        cutoff=CUTOFF,
        attributes=_specs(),
        attribute_columns={"heading": "Heading", "positioning": "Positioning"},
        uid_column="UID",
    )
    with pytest.raises(ValueError, match="one active persistent player mapping"):
        replace(catalog, player_attributes=full)


def test_later_scoped_receipt_cannot_drop_a_mapping_at_an_earlier_catalog_cutoff():
    mappings = (mapping(), mapping("1002", 12, 20, valid_until=CUTOFF + timedelta(hours=6)))
    earlier = scoped(mappings)
    later = scoped(mappings, cutoff=CUTOFF + timedelta(hours=12))
    original = base_catalog()
    assert [row.source_player_id for row in later.player_attributes] == ["1001"]
    assert earlier.add_to_catalog(original, attributes=_specs()).value(12, _specs()[1]) == 20
    with pytest.raises(ValueError, match="cutoff must equal"):
        later.add_to_catalog(original, attributes=_specs())


def test_earlier_scoped_receipt_cannot_be_reused_for_a_later_catalog_cutoff():
    original = replace(base_catalog(), decision_cutoff=CUTOFF + timedelta(hours=12))
    with pytest.raises(ValueError, match="cutoff must equal"):
        scoped().add_to_catalog(original, attributes=_specs())


def test_equivalent_timezone_representation_is_the_same_catalog_cutoff():
    result = scoped(cutoff=CUTOFF.astimezone(timezone(timedelta(hours=3))))
    assert result.add_to_catalog(base_catalog(), attributes=_specs()).value(1, _specs()[0]) == 12


@pytest.mark.parametrize(
    "attributes", [(), list(_specs()), (replace(_specs()[0], source_id="other"),)]
)
def test_scoped_handoff_requires_exact_source_definitions(attributes):
    with pytest.raises(ValueError, match="definitions for its exact source"):
        scoped().add_to_catalog(base_catalog(), attributes=attributes)


def test_scoped_handoff_keeps_catalog_duplicate_and_scale_guards():
    receipt = scoped()
    catalog = receipt.add_to_catalog(base_catalog(), attributes=_specs())
    with pytest.raises(ValueError, match="Attribute definitions must be unique"):
        receipt.add_to_catalog(catalog, attributes=_specs())
    with pytest.raises(ValueError, match="supported 1 to 20 scale"):
        receipt.add_to_catalog(base_catalog(), attributes=(replace(_specs()[0], maximum=21),))


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"contract_version": "unknown"}, "Unsupported"),
        ({"source": _source(CSV, kind="provider")}, "explicit FM source"),
        ({"cutoff": CUTOFF.replace(tzinfo=None)}, "explicit timezone"),
        ({"source": _source(CSV, valid_until=CUTOFF - timedelta(seconds=1))}, "stale"),
        (
            {"mappings": (mapping(), mapping("1002", 2, valid_from=CUTOFF + timedelta(hours=1)))},
            "all be active",
        ),
        ({"mappings": [mapping()]}, "immutable explicit player mappings"),
        ({"player_attributes": []}, "immutable typed attribute rows"),
        ({"player_attributes": (None,)}, "immutable typed attribute rows"),
        ({"player_attributes": ()}, "exact source and mappings"),
        (
            {"player_attributes": (PlayerAttributes("other", "1001", (("heading", 12),)),)},
            "exact source and mappings",
        ),
        (
            {
                "player_attributes": (
                    PlayerAttributes("synthetic-fm-export", "1002", (("heading", 12),)),
                )
            },
            "exact source and mappings",
        ),
        ({"source_player_count": True}, "count must cover"),
        ({"source_player_count": 0}, "count must cover"),
        ({"source_player_count": 1.5}, "count must cover"),
    ],
)
def test_direct_scoped_receipt_construction_validates_its_contract(changes, reason):
    with pytest.raises(ValueError, match=reason):
        replace(scoped(), **changes)


@pytest.mark.parametrize(
    "values", [(), (("", 12),), (("heading", 0),), (("heading", 21),), (("heading", 1.5),)]
)
def test_direct_scoped_receipt_rejects_non_fm_attribute_rows(values):
    with pytest.raises(ValueError, match=r"attribute names|integer 1 to 20"):
        replace(
            scoped(), player_attributes=(PlayerAttributes("synthetic-fm-export", "1001", values),)
        )


def test_direct_scoped_receipt_rejects_duplicate_rows_and_inconsistent_fields():
    receipt = scoped((mapping(), mapping("1002", 2)))
    with pytest.raises(ValueError, match="exact source and mappings"):
        replace(receipt, player_attributes=(receipt.player_attributes[0],) * 2)
    with pytest.raises(ValueError, match="same integer 1 to 20 fields"):
        replace(
            receipt,
            player_attributes=(
                receipt.player_attributes[0],
                replace(receipt.player_attributes[1], values=(("heading", None),)),
            ),
        )
