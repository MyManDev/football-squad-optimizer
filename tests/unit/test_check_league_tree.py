"""Release checks keep their findings when run through one command."""

import json
from pathlib import Path

import pytest
from scripts.check_league_tree import main


def _write(root: Path, path: str, payload: dict) -> None:
    target = root / "league" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"payload": payload}), encoding="utf-8")


def _tree(root: Path) -> None:
    _write(root, "members.json", {"members": [{"entry_id": 1, "member_kind": "human"}]})
    _write(root, "advice/1/saf-puan/1.json", {})
    paths, documents = {}, []
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
    _write(
        root,
        "advice/1/index.json",
        {
            "default_rival_entry_id": None,
            "windows": {},
            "computed": [],
            "evidence": {"available": False, "reason": "no_evidence_this_run"},
            "top100": {"available": True, "paths": paths, "word_paths": {}, "documents": documents},
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
