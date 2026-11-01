"""`scripts/paper_figures.py` on small fixture tables, never the committed records.

The fixture tables have the columns `scripts/paper_record_tables.py` writes and a handful of
rows each, chosen so that one changed value leaves every axis where it was: a test that changes
a value can then require that exactly that value's mark moves. Every mark carries a `<title>`
naming its row, which is how a mark is found here.
"""

from __future__ import annotations

import csv
import hashlib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import paper_figures as figures
from scripts import paper_record_tables as tables

SVG = "{http://www.w3.org/2000/svg}"
REC_1 = "docs/phase_d_component_squad_calibration.json"
REC_2 = "docs/research/moe_sampler.json"
FIG1, FIG2, FIG3, FIG4, FIG5 = (figure.file for figure in figures.FIGURES)

FOLDS = [
    ("Arm A", "2021-22-gw02", "2021-22", 2.0),
    ("Arm A", "2021-22-gw03", "2021-22", -4.0),
    ("Arm A", "2021-22-gw04", "2021-22", 0.0),
    ("Arm A", "2022-23-gw02", "2022-23", 10.0),
    ("Arm A", "2022-23-gw03", "2022-23", -10.0),
    ("Arm B, with a comma", "2021-22-gw02", "2021-22", 6.0),
    ("Arm B, with a comma", "2021-22-gw03", "2021-22", 1.0),
    ("Arm B, with a comma", "2021-22-gw04", "2021-22", -2.0),
    ("Arm B, with a comma", "2022-23-gw02", "2022-23", 3.0),
    ("Arm B, with a comma", "2022-23-gw03", "2022-23", -8.0),
]

SEASON_MEANS = [
    ("Arm A", "2021-22", -1.0),
    ("Arm A", "2022-23", 0.5),
    ("Arm B, with a comma", "2021-22", 2.0),
    ("Arm B, with a comma", "2022-23", -2.5),
]

#: Arm, squad points, pooled MAE, and (MAE, observations) for 2021-22, 2022-23 and 2025-26.
MAE_ROWS = [
    ("Linear components", 60.0, 1.066667, (1.2, 10), (1.0, 30), (1.1, 20)),
    ("Arm A", 62.0, 1.03, (1.1, 10), (0.98, 30), (1.05, 20)),
    ("Arm B, with a comma", 58.0, 1.08, (1.25, 20), (1.02, 20), (1.0, 20)),
]

#: Sampler, record, arm and the fold PITs of each sampler arm.
PITS = [
    ("foundation", REC_1, "/verdict", (0.05, 0.1, 0.55, 0.58, 1.0)),
    ("team_match_joint", REC_2, "/candidate_arm", (0.0, 0.35, 0.35, 0.95)),
]


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _write_tables(folder: Path, change: Callable[[dict[str, list[list[Any]]]], None]) -> Path:
    rows: dict[str, list[list[Any]]] = {
        "folds": [[c, f, s, 50.0 + d, 50.0, d, "docs/x.json"] for c, f, s, d in FOLDS],
        "means": [[c, s, m, "docs/x.json"] for c, s, m in SEASON_MEANS],
        "mae": [
            [arm, squad, pooled, *first, *second, *third, "docs/x.json"]
            for arm, squad, pooled, first, second, third in MAE_ROWS
        ],
        "pit": [
            [sampler, arm, f"2021-22-gw{index + 11:02d}", "2021-22", pit, pit < 0.1, record]
            for sampler, record, arm, pits in PITS
            for index, pit in enumerate(pits)
        ],
        "s2": [
            ["foundation", "/verdict", "pooled", 5, 1, REC_1],
            ["team_match_joint", "/candidate_arm", "pooled", 4, 2, REC_2],
            ["team_match_joint", "/candidate_arm", "2021-22", 2, 1, REC_2],
        ],
        "calibration": [
            ["foundation", REC_1, "/verdict", "", ""],
            ["team_match_joint", REC_2, "/candidate_arm", 0.04, 0.16],
        ],
    }
    change(rows)
    folder.mkdir(parents=True, exist_ok=True)
    _write_csv(
        folder / "figure_decision_fold_differences.csv",
        [
            "candidate",
            "fold_id",
            "season",
            "candidate_score",
            "linear_score",
            "difference",
            "record",
        ],
        rows["folds"],
    )
    _write_csv(
        folder / "figure_decision_by_season.csv",
        ["candidate", "season", "candidate_minus_linear_mean", "record"],
        rows["means"],
    )
    seasons = ("2021-22", "2022-23", "2025-26")
    _write_csv(
        folder / "figure_points_mae_against_squad_points.csv",
        [
            "arm",
            "squad_points_decision_folds",
            "points_mae_pooled_all_seasons",
            *(
                f"{kind}_{season}"
                for season in seasons
                for kind in ("points_mae", "points_observations")
            ),
            "record",
        ],
        rows["mae"],
    )
    _write_csv(
        folder / "figure_sampler_pit.csv",
        ["sampler", "arm", "fold_id", "season", "pit", "realized_below_q10", "record"],
        rows["pit"],
    )
    _write_csv(
        folder / "figure_s2_counts.csv",
        ["sampler", "arm", "scope", "fold_count", "below_q10_count", "record"],
        rows["s2"],
    )
    _write_csv(
        folder / "table_sampler_calibration.csv",
        ["sampler", "record", "arm", "s2_bounds_low", "s2_bounds_high"],
        rows["calibration"],
    )
    return folder


def _unchanged(rows: dict[str, list[list[Any]]]) -> None:
    del rows


def _draw(root: Path, name: str, change: Callable[..., None] = _unchanged) -> Path:
    source = _write_tables(root / "tables" / name, change)
    output = root / "artifacts" / name
    code = figures.main(["--root", str(root), "--tables", str(source), "--output-dir", str(output)])
    assert code == 0
    return output


def _parse(path: Path) -> ElementTree.Element:
    return ElementTree.fromstring(path.read_text(encoding="utf-8"))


def _elements(path: Path) -> list[tuple[str, dict[str, str], str]]:
    """Every drawn element in document order: its tag, attributes and title (or '')."""

    root = _parse(path)
    listed = []
    for element in root.iter():
        tag = element.tag.removeprefix(SVG)
        if tag in {"svg", "title", "desc"}:
            continue
        title = element.find(f"{SVG}title")
        listed.append((tag, dict(element.attrib), "" if title is None else title.text or ""))
    return listed


def _key(title: str) -> str:
    return title.rsplit(": ", 1)[0]


def _marks(path: Path) -> dict[str, dict[str, str]]:
    """Each titled mark by its title up to the value."""

    marks: dict[str, dict[str, str]] = {}
    for _, attributes, title in _elements(path):
        if title:
            assert _key(title) not in marks, title
            marks[_key(title)] = attributes
    return marks


def test_every_figure_renders_from_a_small_fixture_table(tmp_path: Path) -> None:
    output = _draw(tmp_path, "base")

    assert sorted(path.name for path in output.iterdir()) == sorted(
        figure.file for figure in figures.FIGURES
    )
    for figure in figures.FIGURES:
        root = _parse(output / figure.file)
        assert root.tag == f"{SVG}svg"
        assert root.find(f"{SVG}title") is not None
        width, height = float(root.attrib["width"]), float(root.attrib["height"])
        assert root.attrib["viewBox"] == f"0 0 {width:.2f} {height:.2f}"
        assert width > 300
        assert height > 150
        for tag, attributes, _ in _elements(output / figure.file):
            for axis, limit in (("x", width), ("cx", width), ("y", height), ("cy", height)):
                if axis in attributes and tag != "text":
                    assert -0.01 <= float(attributes[axis]) <= limit + 0.01, (figure.file, tag)
    marks = {figure.file: _marks(output / figure.file) for figure in figures.FIGURES}
    folds = [key for key in marks[FIG1] if "mean of" not in key]
    assert sorted(folds) == sorted(f"{c}, {f}" for c, f, _, _ in FOLDS)
    assert sum("mean of" in key for key in marks[FIG1]) == 4
    assert sorted(marks[FIG2]) == sorted(f"{c}, {s}" for c, s, _ in SEASON_MEANS)
    assert sorted(marks[FIG3]) == sorted(
        f"{arm}, {kind}" for arm, *_ in MAE_ROWS for kind in ("pooled", "matched")
    )
    assert len(marks[FIG4]) == 2 * figures.PIT_BINS
    assert sorted(marks[FIG5]) == [
        "S2 bounds of moe_sampler /candidate_arm",
        "moe_sampler /candidate_arm",
        "phase_d_component_squad_calibration /verdict",
    ]


def test_the_histogram_counts_every_fold_once_and_a_pit_on_an_edge_in_the_upper_bin(
    tmp_path: Path,
) -> None:
    output = _draw(tmp_path, "base")

    counts: dict[str, list[int]] = {}
    for _, _, title in _elements(output / FIG4):
        if title:
            panel = title.split(", PIT ")[0]
            counts.setdefault(panel, []).append(int(title.rsplit(": ", 1)[1]))
    # 0.05 and 0.1 fall in [0, 0.1) and [0.1, 0.2); 0.55 and 0.58 share a bin; 1.0 is in the last.
    assert counts["phase_d_component_squad_calibration /verdict"] == [1, 1, 0, 0, 0, 2, 0, 0, 0, 1]
    assert counts["moe_sampler /candidate_arm"] == [1, 0, 0, 2, 0, 0, 0, 0, 0, 1]
    assert figures._bin("x", 0.3, 10) == 3
    assert figures._bin("x", 0.7, 10) == 7
    with pytest.raises(figures.FigureError, match="outside"):
        figures._bin("x", 1.01, 10)


def test_the_matched_mae_is_the_observation_weighted_mean_of_the_decision_seasons(
    tmp_path: Path,
) -> None:
    output = _draw(tmp_path, "base")

    titles = [title for _, _, title in _elements(output / FIG3) if title]
    # Linear components: (1.2 * 10 + 1.0 * 30) / 40 over 2021-22 and 2022-23; 2025-26 is left out.
    assert "Linear components, matched: points MAE 1.050000, squad points 60.000000" in titles
    assert "Linear components, pooled: points MAE 1.066667, squad points 60.000000" in titles
    label = [
        element.text
        for element in _parse(output / FIG3).iter(f"{SVG}text")
        if element.text and "observation-weighted" in element.text
    ]
    assert label == ["points MAE over 2021-22 to 2022-23, observation-weighted"]


def test_the_output_is_byte_stable_across_two_runs(tmp_path: Path) -> None:
    first = _draw(tmp_path, "one")
    second = _draw(tmp_path, "two")

    for figure in figures.FIGURES:
        one = (first / figure.file).read_bytes()
        assert one == (second / figure.file).read_bytes(), figure.file
        assert b"\r\n" not in one
        assert b"-0.00" not in one


def _set_fold(value: float) -> Callable[[dict[str, list[list[Any]]]], None]:
    def change(rows: dict[str, list[list[Any]]]) -> None:
        rows["folds"][1][5] = value

    return change


def _set_mean(rows: dict[str, list[list[Any]]]) -> None:
    rows["means"][0][2] = -2.0


def _set_squad_points(rows: dict[str, list[list[Any]]]) -> None:
    rows["mae"][0][1] = 59.0


def _move_pit(rows: dict[str, list[list[Any]]]) -> None:
    rows["pit"][6][4] = 0.75


def _set_count(rows: dict[str, list[list[Any]]]) -> None:
    rows["s2"][0][4] = 0


@pytest.mark.parametrize(
    ("figure", "change", "moved", "untitled"),
    [
        (
            FIG1,
            _set_fold(-1.0),
            {"Arm A, 2021-22-gw03", "Arm A, 2021-22 mean of 3 folds"},
            set(),
        ),
        (FIG2, _set_mean, {"Arm A, 2021-22"}, {"polyline"}),
        (
            FIG3,
            _set_squad_points,
            {"Linear components, pooled", "Linear components, matched"},
            {"text", "line"},
        ),
        (
            FIG4,
            _move_pit,
            {
                "moe_sampler /candidate_arm, PIT [0.3, 0.4)",
                "moe_sampler /candidate_arm, PIT [0.7, 0.8)",
            },
            set(),
        ),
        (FIG5, _set_count, {"phase_d_component_squad_calibration /verdict"}, {"text"}),
    ],
)
def test_a_changed_value_moves_its_own_mark_and_no_other(
    tmp_path: Path,
    figure: str,
    change: Callable[[dict[str, list[list[Any]]]], None],
    moved: set[str],
    untitled: set[str],
) -> None:
    before = _elements(_draw(tmp_path, "before") / figure)
    after = _elements(_draw(tmp_path, "after", change) / figure)

    assert len(before) == len(after)
    # Geometry only: a title names its value, so it changes with the value whether or not
    # the mark moved.
    changed = [(old, new) for old, new in zip(before, after, strict=True) if old[1] != new[1]]
    assert {_key(old[2]) for old, _ in changed if old[2]} == moved
    assert {old[0] for old, _ in changed if not old[2]} <= untitled


def test_a_mark_moves_the_way_its_value_moves(tmp_path: Path) -> None:
    base = _marks(_draw(tmp_path, "base") / FIG1)["Arm A, 2021-22-gw03"]
    higher = _marks(_draw(tmp_path, "higher", _set_fold(-1.0)) / FIG1)["Arm A, 2021-22-gw03"]
    lower = _marks(_draw(tmp_path, "lower", _set_fold(-6.0)) / FIG1)["Arm A, 2021-22-gw03"]

    assert float(higher["cy"]) < float(base["cy"]) < float(lower["cy"])
    assert higher["cx"] == base["cx"] == lower["cx"]
    bar = "phase_d_component_squad_calibration /verdict"
    wide = _marks(_draw(tmp_path, "wide") / FIG5)[bar]
    narrow = _marks(_draw(tmp_path, "narrow", _set_count) / FIG5)[bar]
    assert float(narrow["width"]) < float(wide["width"])


def test_a_missing_column_or_table_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write_tables(tmp_path / "tables", _unchanged)
    with (source / "figure_decision_fold_differences.csv").open(encoding="utf-8") as handle:
        header = handle.readline()
    text = (source / "figure_decision_fold_differences.csv").read_text(encoding="utf-8")
    (source / "figure_decision_fold_differences.csv").write_text(
        text.replace(header, header.replace(",difference,", ",diff,")), encoding="utf-8"
    )
    output = tmp_path / "artifacts" / "figures"
    code = figures.main(
        ["--root", str(tmp_path), "--tables", str(source), "--output-dir", str(output)]
    )

    assert code == 1
    assert "no column difference" in capsys.readouterr().out
    assert not output.exists()

    (source / "figure_sampler_pit.csv").unlink()
    assert figures.main(["--root", str(tmp_path), "--tables", str(source)]) == 1
    assert "figure_sampler_pit.csv: no such table file" in capsys.readouterr().out


def test_inside_the_checkout_only_a_folder_under_artifacts_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write_tables(tmp_path / "artifacts" / "tables", _unchanged)

    for output in ("docs/paper/figures", "data/figures", "artifacts"):
        code = figures.main(
            ["--root", str(tmp_path), "--tables", str(source), "--output-dir", output]
        )
        assert code == 1
        assert "Paper figures refused" in capsys.readouterr().out
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "data").exists()


def test_ticks_are_round_steps_that_cover_the_range() -> None:
    axis = figures.ticks(-41.0, 42.0, 6)
    assert axis.values[0] <= -41.0
    assert axis.values[-1] >= 42.0
    assert [axis.label(value) for value in axis.values] == [
        "-60",
        "-40",
        "-20",
        "0",
        "20",
        "40",
        "60",
    ]
    fine = figures.ticks(1.0399, 1.0924, 4)
    assert [fine.label(value) for value in fine.values] == [
        "1.02",
        "1.04",
        "1.06",
        "1.08",
        "1.10",
    ]
    assert not figures.ticks(-0.001, 0.0, 4).label(-0.0).startswith("-")
    flat = figures.ticks(5.0, 5.0)
    assert flat.low < 5.0 < flat.high


def test_spread_keeps_the_order_and_the_gap_and_the_range_when_they_fit() -> None:
    placed = figures.spread([10.0, 11.0, 50.0, 99.0, 100.0], 14.0, 0.0, 100.0)

    assert placed == [10.0, 24.0, 50.0, 86.0, 100.0]
    crowded = figures.spread([0.0, 0.0, 0.0], 14.0, 0.0, 20.0)
    assert crowded == [-8.0, 6.0, 20.0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fake_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    """`extract` replaced by a copy of the fixture tables and a records.csv of one record."""

    def extract(root: Path, output_dir: Path) -> tuple[list[tables.Check], str | None]:
        _write_tables(output_dir, _unchanged)
        _write_csv(
            output_dir / "records.csv",
            ["record", "sha256_lf", "git_blob_lf", "commit", "blob_at_commit", "matches_commit"],
            [[REC_1, "a" * 64, "b" * 40, "c" * 40, "b" * 40, "true"]],
        )
        check = tables.Check("fixture", REC_1, "", 1, 1, True)
        return [check], "c" * 40

    monkeypatch.setattr(tables, "extract", extract)


def _manifest(tmp_path: Path) -> str:
    """A manifest in the form of docs/paper/README.md, written from one regeneration."""

    directory = tmp_path / "artifacts" / "first"
    figures.regenerate(tmp_path, directory)
    own = tables.Digest.of(figures.SCRIPT_SOURCE.read_bytes())
    lines = [
        "| Key | Record | Git blob | SHA-256 |",
        "| --- | --- | --- | --- |",
        f"| R1 | `{REC_1}` | `{'b' * 40}` | `{'a' * 64}` |",
        f"| C2 | `{figures.SCRIPT}` | `{own.blob_lf}` | `{own.sha256_lf}` |",
        "",
        "| Output | Command | SHA-256 |",
        "| --- | --- | --- |",
    ]
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        name = path.relative_to(directory).as_posix()
        if name == "tables/records.csv":
            lines.append(f"| `{name}` | `python -m scripts.x` | names the checked-out commit |")
        else:
            lines.append(f"| `{name}` | `python -m scripts.x` | `{_sha256(path)}` |")
    return "\n".join(lines) + "\n"


@pytest.mark.usefixtures("fake_extract")
def test_the_check_passes_on_matching_digests_and_names_each_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.md"
    text = _manifest(tmp_path)
    manifest.write_text(text, encoding="utf-8")

    assert figures.main(["--root", str(tmp_path), "--check", str(manifest)]) == 0
    out = capsys.readouterr().out
    assert "  ok        figures/fig1_decision_fold_differences.svg" in out
    assert "  unpinned  tables/records.csv" in out

    fig4 = next(line for line in text.splitlines() if FIG4 in line)
    altered = text.replace(fig4, fig4[: fig4.rindex("`") - 64] + "0" * 64 + "` |")
    manifest.write_text(altered, encoding="utf-8")
    assert figures.main(["--root", str(tmp_path), "--check", str(manifest)]) == 1
    assert f"  DIFFERS   figures/{FIG4}: manifest {'0' * 64}" in capsys.readouterr().out

    manifest.write_text(text.replace(fig4 + "\n", ""), encoding="utf-8")
    assert figures.main(["--root", str(tmp_path), "--check", str(manifest)]) == 1
    assert f"  NO ROW    figures/{FIG4}" in capsys.readouterr().out

    manifest.write_text(text.replace("b" * 40, "d" * 40), encoding="utf-8")
    assert figures.main(["--root", str(tmp_path), "--check", str(manifest)]) == 1
    assert f"  DIFFERS   {REC_1}" in capsys.readouterr().out


def test_the_committed_manifest_names_every_output_and_input_once() -> None:
    text = (figures.REPOSITORY_ROOT / "docs" / "paper" / "README.md").read_text(encoding="utf-8")

    manifest = figures.read_manifest(text)

    written = {
        *(
            f"tables/table_{name}.csv"
            for name in (
                "candidates_player_level",
                "candidates_decision_level",
                "candidates_reading_status",
                "sampler_calibration",
                "joint_sampler_seeds",
                "joint_sampler_seed_summary",
                "mixture_distribution",
                "mixture_log_score_folds",
                "planning_measurements",
            )
        ),
        *(f"tables/{table}" for figure in figures.FIGURES for table in figure.tables),
        "tables/provenance.csv",
        "tables/records.csv",
        "tables/checks.csv",
        "tables/tables.md",
        *(f"figures/{figure.file}" for figure in figures.FIGURES),
    }
    assert set(manifest.outputs) == written
    unpinned = {name for name, digest in manifest.outputs.items() if digest is None}
    assert unpinned == {"tables/records.csv", "tables/tables.md"}
    records = {
        tables.GBM,
        tables.FEATURES_V2,
        tables.GBM_POINTS,
        tables.REGIME,
        tables.MIXTURE,
        tables.FROZEN_EVALUATION,
        tables.FOUNDATION,
        tables.BLOCK,
        tables.JOINT,
        tables.RANK_SHRINKAGE,
        tables.MEAN_REVERSION,
    }
    assert set(manifest.inputs) == records | {tables.EXTRACTOR, figures.SCRIPT}
