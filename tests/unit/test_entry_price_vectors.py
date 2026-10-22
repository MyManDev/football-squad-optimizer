"""The device purchase-price port keeps the accepted server replay and fallback."""

import json

from scripts.export_entry_price_vectors import FIXTURE, build_vectors


def test_entry_price_vectors_equal_the_current_python_rules():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(
        json.dumps(build_vectors())
    )


def test_vectors_pin_repurchase_free_hit_precision_and_the_late_joiner_cap():
    cases = {row["name"]: row for row in build_vectors()["cases"]}
    assert cases["sold-and-bought-back"]["expected"]["prices"][1] == 70
    assert cases["sold-and-bought-back"]["expected_selling"]["sell_tenths"][1] == 72
    assert cases["free-hit-reverts"]["expected"]["free_hit_skipped"] == 1
    assert cases["distinct-microseconds-are-not-tied"]["expected"]["known"] is True
    assert cases["distinct-microseconds-are-not-tied"]["expected"]["sales_checked"] == 0
    assert cases["tied-sale-and-repurchase"]["expected"]["sales_checked"] == 2
    fallback = cases["late-joiner-market-cap"]["expected_selling"]
    assert fallback["purchase_prices_known"] is False
    assert fallback["squad_sell_value_tenths"] == 900
    assert sum(fallback["sell_tenths"].values()) == 915
