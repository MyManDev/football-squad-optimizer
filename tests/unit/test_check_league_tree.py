"""Release checks keep their findings when run through one command."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from scripts.check_league_tree import Tree, main


def _write(root: Path, path: str, payload: dict) -> None:
    target = root / "league" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"payload": payload}), encoding="utf-8")


def _tree(root: Path) -> None:
    _write(root, "members.json", {"members": [{"entry_id": 1, "member_kind": "human"}]})
    _write(root, "advice/1/saf-puan/1.json", {})
    word = {
        "mode": "saf-puan",
        "window": 1,
        "evidence": {"binding": False, "applied": []},
        "expected_points_cost": 0,
        "expected_points_cost_ceiling": 0,
    }
    _write(root, "advice/1/saf-puan/1/hoca-sozu.json", word)
    paths, word_paths, documents = {}, {}, []
    for weight in (5, 10, 20, 30, 40, 50):
        for window in (1, 3, 5):
            path = f"advice/1/saf-puan/{window}/top100-{weight}.json"
            _write(
                root,
                path,
                {
                    "mode": "saf-puan",
                    "window": window,
                    "rival_entry_id": None,
                    "top100": {"weight": weight},
                    "expected_points_cost": 0,
                    "expected_points_cost_ceiling": 0,
                    "plan_weeks": [{}] * window,
                    "stated_limits": [
                        f"The plan was chosen with the Top 100 influence at {weight}; "
                        "every expected-points number in this document is the base model's, "
                        "without it."
                    ],
                },
            )
            if window == 1:
                paths[str(weight)] = path
                weighted = json.loads((root / "league" / path).read_bytes())["payload"]
                word_path = f"advice/1/saf-puan/1/top100-{weight}-hoca-sozu.json"
                _write(root, word_path, {**weighted, "evidence": word["evidence"]})
                word_paths[str(weight)] = word_path
            else:
                documents.append(
                    {
                        "strategy": "saf-puan",
                        "window": window,
                        "rival_entry_id": None,
                        "weight": weight,
                        "path": path,
                    }
                )
            for strategy in ("ortak-koru", "fark-yarat"):
                rival_path = f"advice/1/{strategy}/{window}/vs-2/top100-{weight}.json"
                payload = json.loads((root / "league" / path).read_bytes())["payload"]
                _write(root, rival_path, {**payload, "mode": strategy, "rival_entry_id": 2})
                documents.append(
                    {
                        "strategy": strategy,
                        "window": window,
                        "rival_entry_id": 2,
                        "weight": weight,
                        "path": rival_path,
                    }
                )
    _write(
        root,
        "advice/1/index.json",
        {
            "default_rival_entry_id": 2,
            "windows": {"ortak-koru": [1, 3, 5], "fark-yarat": [1, 3, 5]},
            "computed": [],
            "evidence": {
                "available": True,
                "binding": False,
                "applied_count": 0,
                "path": "advice/1/saf-puan/1/hoca-sozu.json",
            },
            "top100": {
                "available": True,
                "paths": paths,
                "word_paths": word_paths,
                "documents": documents,
            },
        },
    )


@pytest.mark.parametrize("defect", [None, "variants", "top100", "word"])
def test_the_three_checks_keep_their_clean_and_defective_outcomes(
    tmp_path: Path, defect: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path)
    if defect == "variants":
        path = tmp_path / "league/advice/1/saf-puan/3/top100-5.json"
        document = json.loads(path.read_bytes())
        document["payload"]["plan_weeks"] = []
        path.write_text(json.dumps(document), encoding="utf-8")
    elif defect == "top100":
        path = tmp_path / "league/advice/1/saf-puan/1/top100-5.json"
        document = json.loads(path.read_bytes())
        document["payload"]["top100"]["weight"] = 10
        path.write_text(json.dumps(document), encoding="utf-8")
    elif defect == "word":
        _write(tmp_path, "advice/1/saf-puan/1/hoca-sozu.json", {})
    assert main([str(tmp_path)]) == (0 if defect is None else 1)
    output = capsys.readouterr().out
    assert all(f"Checking {name}" in output for name in ("variants", "top100", "word"))
    if defect is None:
        assert output.count("ALL GOOD") == 3
        assert "('ortak-koru', 3, True)" in output
        assert "non-binding keeps the captain" in output
    else:
        assert output.count("ALL GOOD") == 2


def test_a_truncated_unavailable_word_file_is_still_a_file(tmp_path, capsys):
    _tree(tmp_path)
    index_path = tmp_path / "league/advice/1/index.json"
    index = json.loads(index_path.read_bytes())["payload"]
    index["evidence"] = {"available": False, "reason": "no_evidence_this_run"}
    index["top100"]["word_paths"] = {}
    _write(tmp_path, "advice/1/index.json", index)
    (tmp_path / "league/advice/1/saf-puan/1/hoca-sozu.json").write_text('{"payload":')
    assert main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "BAD 1: unavailable" in output
    assert output.count("ALL GOOD") == 2


def test_invalid_json_and_wrong_root_name_the_problem(tmp_path, capsys):
    assert main([str(tmp_path)]) == 1
    assert "directory containing league/" in capsys.readouterr().out
    _tree(tmp_path)
    path = tmp_path / "league/advice/1/saf-puan/1/top100-5.json"
    path.write_text("{")
    assert main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert f"{path} exists and does not parse" in output


def test_url_reads_identify_the_checker_and_treat_pages_fallback_as_absent(monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        assert timeout == 30
        return BytesIO(b"{}" if len(requests) == 1 else b"<!doctype html>")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    tree = Tree("https://site.example")
    assert tree.read("members.json") == {}
    assert tree.read("advice/1/saf-puan/1/hoca-sozu.json") is None
    assert all(request.get_header("User-agent") == "squadopt-verify/1.0" for request in requests)


def test_local_word_figure_hit_is_reported_once(tmp_path, capsys):
    _tree(tmp_path)
    path = tmp_path / "league/advice/1/saf-puan/1/hoca-sozu.json"
    document = json.loads(path.read_bytes())
    document["payload"]["note"] = "80%"
    path.write_text(json.dumps(document))
    assert main([str(tmp_path)]) == 1
    assert capsys.readouterr().out.count("league/advice/1/saf-puan/1/hoca-sozu.json") == 1


@pytest.mark.parametrize(
    ("changes", "clean"),
    [
        # A ceiling over a control that was found without a proof is a figure nothing
        # bounds, on every kind of priced document.
        ({"control_solver_status": "FEASIBLE"}, False),
        # The same document without it is what the producer publishes.
        ({"control_solver_status": "FEASIBLE", "expected_points_cost_ceiling": None}, True),
        # Under a proof the ceiling is the price itself, and missing it is a defect.
        ({"control_solver_status": "OPTIMAL", "expected_points_cost_ceiling": 1.5}, False),
        ({"control_solver_status": "OPTIMAL", "expected_points_cost_ceiling": None}, False),
    ],
)
def test_a_ceiling_is_the_price_under_a_proven_control_and_absent_otherwise(
    tmp_path: Path, changes: dict[str, object], clean: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path)
    for relative in (
        "advice/1/saf-puan/3/top100-5.json",
        "advice/1/saf-puan/1/top100-5.json",
    ):
        path = tmp_path / "league" / relative
        document = json.loads(path.read_bytes())
        for key, value in changes.items():
            if value is None:
                document["payload"].pop(key, None)
            else:
                document["payload"][key] = value
        path.write_text(json.dumps(document), encoding="utf-8")
    assert main([str(tmp_path)]) == (0 if clean else 1)
    output = capsys.readouterr().out
    assert output.count("ALL GOOD") == (3 if clean else 1)


@pytest.mark.parametrize("status", ["FEASIBLE", "OPTIMAL"])
def test_a_word_that_binds_nobody_is_its_own_control(
    tmp_path: Path, status: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path)
    path = tmp_path / "league/advice/1/saf-puan/1/hoca-sozu.json"
    document = json.loads(path.read_bytes())
    document["payload"]["solver_status"] = status
    path.write_text(json.dumps(document), encoding="utf-8")
    # A zero price with a zero ceiling is exact only under the plan's own proof.
    code = main([str(tmp_path)])
    output = capsys.readouterr().out
    if status == "OPTIMAL":
        assert code == 0
    else:
        assert code == 1 and "over an unproven control" in output
