import json

import pytest

from squadopt.platform.advice_cache import AdviceCacheConflictError, FileAdviceCache
from squadopt.platform.advice_plan_cache import PlanAdviceCache

KEY = "a" * 64
DATA = "b" * 64


def encoded(payload):
    return json.dumps(
        {"payload": {"window": 1, **payload}}, sort_keys=True, separators=(",", ":")
    ).encode()


def test_only_computed_components_regain_provenance_and_ordinary_bytes_stay_immutable(tmp_path):
    open_cache = PlanAdviceCache(tmp_path, llmopt_vnext=True)
    closed = PlanAdviceCache(tmp_path, llmopt_vnext=False)
    disk = FileAdviceCache(tmp_path)
    bundle = {
        "name": "plan_data_id",
        "preference_bundle_result": {
            "components": [{"payload": {"net": 1}}, {"payload": None}],
            "selected": {"payload": {"net": 2}},
        },
    }
    canonical = encoded(bundle)
    bundle["preference_bundle_result"]["selected"]["payload"]["plan_data_id"] = DATA
    versioned = encoded(bundle)
    open_cache.put(KEY, versioned)
    assert closed.get(KEY) == disk.get(KEY) == canonical
    assert open_cache.get(KEY) == versioned
    closed.put(KEY, canonical)
    assert open_cache.get(KEY) == versioned
    with pytest.raises(AdviceCacheConflictError):
        closed.put(KEY, encoded({"net": 5}))
    assert disk.get(KEY) == canonical


def test_old_embedded_provenance_is_projected_without_rewriting_and_conflicts_still_fail(tmp_path):
    original = encoded({"net": 5, "plan_data_id": DATA})
    disk = FileAdviceCache(tmp_path)
    disk.put(KEY, original)
    canonical = encoded({"net": 5})
    closed = PlanAdviceCache(tmp_path, llmopt_vnext=False)
    assert closed.get(KEY) == canonical
    closed.put(KEY, canonical)
    with pytest.raises(AdviceCacheConflictError):
        closed.put(KEY, encoded({"net": 6}))
    assert disk.get(KEY) == PlanAdviceCache(tmp_path, llmopt_vnext=True).get(KEY) == original


@pytest.mark.parametrize("malformed", [[], {}, {"main": []}, {"selected": DATA}, {"main": "bad"}])
def test_a_malformed_optional_receipt_preserves_the_plain_answer(tmp_path, malformed):
    cache = PlanAdviceCache(tmp_path, llmopt_vnext=True)
    plain = encoded({"net": 5})
    cache.put(KEY, encoded({"net": 5, "plan_data_id": DATA}))
    (receipt,) = (tmp_path / "plan-provenance").rglob("*.json")
    receipt.write_bytes(json.dumps(malformed).encode())
    assert cache.get(KEY) == plain


def test_partial_rollback_reads_only_one_week_provenance_and_keeps_private_witnesses(
    tmp_path, monkeypatch
):
    both = PlanAdviceCache(tmp_path, llmopt_vnext=True, llmopt_vnext_three_week=True)
    partial = PlanAdviceCache(tmp_path, llmopt_vnext=True)
    one_key, three_key, closed_key = ("1" * 64, "3" * 64, "c" * 64)
    one = encoded({"window": 1, "plan_data_id": DATA})
    three = encoded({"window": 3, "plan_data_id": DATA})
    plain = encoded({"window": 3})
    both.put(one_key, one)
    both.put(three_key, three)
    assert partial.get(one_key) == one
    assert partial.repair_witness(three_key) == three
    partial.put(closed_key, three)
    assert both.repair_witness(closed_key) == plain

    def no_receipt_read(_key):
        pytest.fail("A closed window read must use ordinary advice bytes directly")

    monkeypatch.setattr(partial._receipts, "get", no_receipt_read)
    assert partial.get(three_key) == plain
