"""Release checks keep their findings when run through one command."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from scripts.check_league_tree import Tree, main

from squadopt.application.league_views import MemberRenderTask, _refused_member_index
from squadopt.application.top100_weight import NO_TOP100_THIS_RUN


def _write(root: Path, path: str, payload: dict) -> None:
    target = root / "league" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"payload": payload}), encoding="utf-8")


def _read(root: Path, path: str) -> dict:
    return json.loads((root / "league" / path).read_bytes())["payload"]


def _tree(root: Path) -> None:
    _write(root, "members.json", {"members": [{"entry_id": 1, "member_kind": "human"}]})
    for window in (1, 3, 5):
        _write(root, f"advice/1/saf-puan/{window}.json", {})
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
            "strategies": ["saf-puan", "ortak-koru", "fark-yarat"],
            "windows": {"saf-puan": [1, 3, 5], "ortak-koru": [1, 3, 5], "fark-yarat": [1, 3, 5]},
            "computed": [],
            "unavailable": [],
            "evidence": {
                "available": True,
                "binding": False,
                "applied_count": 0,
                "path": "advice/1/saf-puan/1/hoca-sozu.json",
            },
            "top100": {
                "available": True,
                "published_weight": 0,
                "weights": [0, 5, 10, 20, 30, 40, 50],
                "paths": paths,
                "word_paths": word_paths,
                "unavailable": [],
                "documents": documents,
            },
        },
    )


def _skip_top100(root: Path) -> None:
    """Turn the tree into what a ``--skip-top100`` run writes: no menu, and the index says so."""

    index = _read(root, "advice/1/index.json")
    index["top100"] = {"available": False, "reason": NO_TOP100_THIS_RUN}
    _write(root, "advice/1/index.json", index)
    for path in (root / "league/advice/1").rglob("top100-*.json"):
        path.unlink()


def _refuse(root: Path, entry: int, reason: str) -> None:
    """Add a member the run could not advise, with the index the producer writes for one."""

    members = _read(root, "members.json")
    members["members"].append({"entry_id": entry, "member_kind": "human"})
    _write(root, "members.json", members)
    task = MemberRenderTask(
        entry_id=entry,
        label=str(entry),
        season="2026-27",
        gameweek=6,
        league_id=9,
        rival_ids=(1,),
        default_rival_id=1,
        rival_strategies=("ortak-koru", "fark-yarat"),
    )
    _write(root, f"advice/{entry}/index.json", _refused_member_index(task, reason=reason))


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


def test_a_skip_top100_tree_with_a_refused_member_passes_and_names_both_absences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path)
    _skip_top100(tmp_path)
    _refuse(tmp_path, 3, "No current price for player 7.")
    assert main([str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert output.count("ALL GOOD") == 3
    # The variants and Top 100 checks each name both absences, and neither is a finding.
    assert output.count(f"1 member(s): Top 100 menu not published: {NO_TOP100_THIS_RUN} (1)") == 2
    assert output.count("1 member(s): no advice this week: No current price for player 7. (3)") == 2
    assert "ok  3: no advice this week (No current price for player 7.) and no file" in output


@pytest.mark.parametrize(
    ("skip_top100", "missing"),
    [
        (False, "advice/1/fark-yarat/5/vs-2/top100-50.json"),
        (False, "advice/1/saf-puan/1/top100-20.json"),
        (False, "advice/1/saf-puan/3.json"),
        (True, "advice/1/saf-puan/5.json"),
    ],
)
def test_a_document_the_index_lists_and_the_tree_lacks_is_still_a_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], skip_top100: bool, missing: str
) -> None:
    _tree(tmp_path)
    if skip_top100:
        _skip_top100(tmp_path)
    (tmp_path / "league" / missing).unlink()
    assert main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert f"1: {missing} not published" in output
    assert output.count("ALL GOOD") == 2


def test_what_the_index_states_unavailable_is_satisfied_and_what_it_omits_is_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path)
    index = _read(tmp_path, "advice/1/index.json")
    menu = index["top100"]
    # The pure-points window 5 did not solve, so no rival strategy reached it and no weight
    # was solved over it; the one-week ortak-koru pair against the default rival did not
    # solve; and the one-week plan at weight 20 did not solve, with or without the word.
    index["windows"] = {"saf-puan": [1, 3], "ortak-koru": [1, 3], "fark-yarat": [1, 3]}
    index["unavailable"] = [
        {"strategy": "saf-puan", "rival_entry_id": None, "window": 5, "reason": "not_solved"},
        {"strategy": "ortak-koru", "rival_entry_id": 2, "reason": "not_solved"},
    ]
    gone = [
        document
        for document in menu["documents"]
        if document["window"] == 5
        or (document["strategy"] == "ortak-koru" and document["window"] == 1)
    ]
    menu["documents"] = [document for document in menu["documents"] if document not in gone]
    removed = [
        *(document["path"] for document in gone),
        menu["paths"].pop("20"),
        menu["word_paths"].pop("20"),
        "advice/1/saf-puan/5.json",
    ]
    menu["unavailable"] = [
        {"weight": 20, "word": word, "reason": "not_solved"} for word in (False, True)
    ]
    for path in removed:
        (tmp_path / "league" / path).unlink()
    _write(tmp_path, "advice/1/index.json", index)
    assert main([str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert output.count("ALL GOOD") == 3
    assert "1 member(s): saf-puan window 5 not solved: not_solved (1)" in output
    assert "1 member(s): ortak-koru window 1 vs 2 not solved: not_solved (1)" in output
    assert "1 member(s): Top 100 plain 20 not solved: not_solved (1)" in output
    assert "1 member(s): Top 100 word 20 not solved: not_solved (1)" in output

    # The same tree with nothing stated: the absences are findings again.
    index["unavailable"] = []
    menu["unavailable"] = []
    _write(tmp_path, "advice/1/index.json", index)
    assert main([str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "1: no document for ('ortak-koru', 1, 2, 5)" in output
    assert "1: plain 20 missing" in output
    assert "stated absence" not in output


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
