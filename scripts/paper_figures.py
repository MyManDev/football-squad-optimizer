"""Draw the walk-forward paper's five figures as SVG from the paper record tables.

Issue #1152 lets a model extract tables and figures from the committed records and nothing
more: no section of the paper is drafted here. This runner reads the CSV files that
`scripts/paper_record_tables.py` writes, fits and measures nothing, opens no network connection
and uses the standard library only. Every mark is a value of one CSV row, or a count or mean of
the rows named below; the panels, series, seasons, axis ranges and ticks come from the rows. The
output is byte-stable: coordinates are written with two decimals, nothing carries a time, and
rows are read in the order the tables hold them.

    python -m scripts.paper_record_tables --output-dir artifacts/paper/tables
    python -m scripts.paper_figures --tables artifacts/paper/tables \
        --output-dir artifacts/paper/figures
    python -m scripts.paper_figures --check docs/paper/README.md

The figures, each with the table files it reads:

- `fig1_decision_fold_differences.svg` (`figure_decision_fold_differences.csv`): a panel per
  candidate; in each season its paired folds in fold-id order, and the mean of that season's
  fold differences as a bar;
- `fig2_decision_by_season.svg` (`figure_decision_by_season.csv`): each candidate's recorded
  mean difference by season;
- `fig3_points_mae_against_squad_points.svg` (`figure_points_mae_against_squad_points.csv` and
  the seasons of `figure_decision_by_season.csv`): a point per arm, against its pooled points
  MAE as recorded and against the observation-weighted mean of its season MAEs over the
  decision seasons;
- `fig4_sampler_pit.svg` (`figure_sampler_pit.csv`): a PIT histogram per record and arm, with
  the count a uniform PIT puts in each bin;
- `fig5_s2_counts.svg` (`figure_s2_counts.csv` and `table_sampler_calibration.csv`): each
  arm's pooled count of folds realized below the scenario tenth percentile, with its S2 bounds
  as fold counts where its record holds them.

The output directory (default `artifacts/paper_figures/`, git-ignored) must sit under
`artifacts/` when it is inside the checkout, as the extractor's does. `--check` regenerates the
tables (through `scripts/paper_record_tables.py`) and the figures into a temporary folder and
compares the SHA-256 of every file it writes, and the digests of every record read and of both
scripts, with the rows of the Markdown manifest it names; the exit status is 1 when a digest
differs, a file or a row is missing, or a record check fails.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import tempfile
from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from scripts import paper_record_tables

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
#: This file's path in a checkout, the key of its row in a manifest.
SCRIPT = "scripts/paper_figures.py"
SCRIPT_SOURCE = Path(__file__).resolve()
OUTPUT_ROOT = "artifacts"
DEFAULT_TABLES = Path(OUTPUT_ROOT) / "paper_record_tables"
DEFAULT_OUTPUT = Path(OUTPUT_ROOT) / "paper_figures"
PIT_BINS = 10

FONT = "Helvetica, Arial, sans-serif"
SURFACE = "#ffffff"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BAND = "#ebe9e3"
#: Categorical slots in fixed order; a figure with more series than slots is refused.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
#: One marker shape per series, so a series is told apart in grey print as well.
MARKERS = (
    "circle",
    "square",
    "triangle",
    "diamond",
    "triangle_down",
    "circle",
    "square",
    "diamond",
)


class FigureError(ValueError):
    """A table file is missing, lacks a column a figure reads, or holds a value it cannot draw."""


Rows = list[dict[str, str]]


def read_rows(path: Path) -> Rows:
    if not path.is_file():
        raise FigureError(f"{path.name}: no such table file in {path.parent}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _require(name: str, rows: Rows, columns: Sequence[str]) -> None:
    if not rows:
        raise FigureError(f"{name}: no rows")
    missing = [column for column in columns if column not in rows[0]]
    if missing:
        raise FigureError(f"{name}: no column {', '.join(missing)}")


def _float(name: str, row: dict[str, str], column: str) -> float:
    try:
        value = float(row[column])
    except ValueError as error:
        raise FigureError(f"{name}: {column} {row[column]!r} is not a number") from error
    if not math.isfinite(value):
        raise FigureError(f"{name}: {column} {row[column]!r} is not finite")
    return value


def _ordered(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _number(value: float) -> str:
    """A coordinate with two decimals, never `-0.00`."""

    text = f"{value:.2f}"
    return "0.00" if text == "-0.00" else text


def _width(text: str, size: float) -> float:
    """The width a label is given in the layout: an average glyph of 0.56 em."""

    return len(text) * size * 0.56


def _span(seasons: Sequence[str]) -> str:
    return seasons[0] if len(seasons) == 1 else f"{seasons[0]} to {seasons[-1]}"


def _attributes(attributes: dict[str, str | float | int]) -> str:
    parts = []
    for key, value in attributes.items():
        if isinstance(value, float):
            value = _number(value)
        parts.append(f"{key}={quoteattr(str(value))}")
    return " ".join(parts)


class Svg:
    """An SVG document built element by element, rendered with fixed number formatting."""

    def __init__(self, width: float, height: float, title: str, description: str) -> None:
        self.width = width
        self.height = height
        self.title = title
        self.description = description
        self.parts: list[str] = []

    def element(
        self, name: str, attributes: dict[str, str | float | int], title: str | None = None
    ) -> None:
        opening = f"<{name} {_attributes(attributes)}"
        if title is None:
            self.parts.append(opening + "/>")
        else:
            self.parts.append(f"{opening}><title>{escape(title)}</title></{name}>")

    def line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        stroke: str,
        width: float = 1.0,
        dash: str | None = None,
        title: str | None = None,
    ) -> None:
        attributes: dict[str, str | float | int] = {
            "x1": start[0],
            "y1": start[1],
            "x2": end[0],
            "y2": end[1],
            "stroke": stroke,
            "stroke-width": width,
        }
        if dash:
            attributes["stroke-dasharray"] = dash
        self.element("line", attributes, title)

    def rect(
        self,
        corner: tuple[float, float],
        size: tuple[float, float],
        fill: str,
        title: str | None = None,
    ) -> None:
        attributes: dict[str, str | float | int] = {
            "x": corner[0],
            "y": corner[1],
            "width": max(size[0], 0.0),
            "height": max(size[1], 0.0),
            "fill": fill,
        }
        self.element("rect", attributes, title)

    def text(
        self,
        position: tuple[float, float],
        content: str,
        size: float = 11.0,
        anchor: str = "start",
        fill: str = INK,
        bold: bool = False,
        rotate: bool = False,
        halo: bool = False,
    ) -> None:
        attributes: dict[str, str | float | int] = {
            "x": position[0],
            "y": position[1],
            "font-size": size,
            "fill": fill,
            "text-anchor": anchor,
        }
        if bold:
            attributes["font-weight"] = "bold"
        if halo:
            # A ring of the surface colour under the glyphs, so a label stays legible on a mark.
            attributes |= {
                "stroke": SURFACE,
                "stroke-width": 3,
                "stroke-linejoin": "round",
                "paint-order": "stroke",
            }
        if rotate:
            attributes["transform"] = f"rotate(-90 {_number(position[0])} {_number(position[1])})"
        self.parts.append(f"<text {_attributes(attributes)}>{escape(content)}</text>")

    def marker(
        self, shape: str, centre: tuple[float, float], fill: str, title: str | None = None
    ) -> None:
        x, y = centre
        ring: dict[str, str | float | int] = {
            "fill": fill,
            "stroke": SURFACE,
            "stroke-width": 1.5,
        }
        if shape == "circle":
            self.element("circle", {"cx": x, "cy": y, "r": 4.5, **ring}, title)
            return
        r = 4.5
        corners = {
            "square": ((-r, -r), (r, -r), (r, r), (-r, r)),
            "triangle": ((0.0, -r - 1), (r + 1, r), (-r - 1, r)),
            "triangle_down": ((0.0, r + 1), (r + 1, -r), (-r - 1, -r)),
            "diamond": ((0.0, -r - 1), (r + 1, 0.0), (0.0, r + 1), (-r - 1, 0.0)),
        }[shape]
        points = " ".join(f"{_number(x + dx)},{_number(y + dy)}" for dx, dy in corners)
        self.element("polygon", {"points": points, **ring}, title)

    def polyline(self, points: Sequence[tuple[float, float]], stroke: str, width: float) -> None:
        listed = " ".join(f"{_number(x)},{_number(y)}" for x, y in points)
        self.element(
            "polyline",
            {"points": listed, "fill": "none", "stroke": stroke, "stroke-width": width},
        )

    def render(self) -> str:
        width, height = _number(self.width), _number(self.height)
        header = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="{FONT}" role="img">'
        )
        lines = [
            header,
            f"<title>{escape(self.title)}</title>",
            f"<desc>{escape(self.description)}</desc>",
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="{SURFACE}"/>',
            *self.parts,
            "</svg>",
        ]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Scale:
    """A linear map from a data interval to a pixel interval."""

    low: float
    high: float
    start: float
    end: float

    def __call__(self, value: float) -> float:
        return self.start + (value - self.low) / (self.high - self.low) * (self.end - self.start)


@dataclass(frozen=True)
class Ticks:
    values: tuple[float, ...]
    decimals: int

    @property
    def low(self) -> float:
        return self.values[0]

    @property
    def high(self) -> float:
        return self.values[-1]

    def label(self, value: float) -> str:
        text = f"{value:.{self.decimals}f}"
        return text[1:] if text.startswith("-") and float(text) == 0 else text


def ticks(low: float, high: float, count: int = 5) -> Ticks:
    """Round tick values that cover [low, high] in about `count` steps of 1, 2, 2.5 or 5."""

    if high < low:
        low, high = high, low
    if high == low:
        pad = abs(low) * 0.1 or 1.0
        low, high = low - pad, high + pad
    exponent = math.floor(math.log10((high - low) / count))
    step = 0.0
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiple * 10.0**exponent
        if (high - low) / step <= count + 1e-9:
            break
    first = math.floor(low / step + 1e-9)
    last = math.ceil(high / step - 1e-9)
    decimals = 0
    while decimals < 10 and abs(step * 10**decimals - round(step * 10**decimals)) > 1e-9:
        decimals += 1
    return Ticks(tuple(index * step for index in range(first, last + 1)), decimals)


def _y_grid(svg: Svg, scale: Scale, axis: Ticks, left: float, right: float, labels: bool) -> None:
    for value in axis.values:
        y = scale(value)
        svg.line((left, y), (right, y), GRID)
        if labels:
            svg.text((left - 6, y + 4), axis.label(value), 10, "end", SECONDARY)


def _x_grid(svg: Svg, scale: Scale, axis: Ticks, top: float, bottom: float) -> None:
    for value in axis.values:
        x = scale(value)
        svg.line((x, top), (x, bottom), GRID)
        svg.text((x, bottom + 15), axis.label(value), 10, "middle", SECONDARY)


def spread(targets: Sequence[float], gap: float, low: float, high: float) -> list[float]:
    """Label positions near `targets`, in their order, at least `gap` apart within the range."""

    order = sorted(range(len(targets)), key=lambda index: (targets[index], index))
    placed = [min(max(targets[index], low), high) for index in order]
    for index in range(1, len(placed)):
        placed[index] = max(placed[index], placed[index - 1] + gap)
    if placed and placed[-1] > high:
        placed[-1] = high
        for index in range(len(placed) - 2, -1, -1):
            placed[index] = min(placed[index], placed[index + 1] - gap)
    positions = [0.0] * len(targets)
    for position, index in zip(placed, order, strict=True):
        positions[index] = position
    return positions


@dataclass(frozen=True)
class Grid:
    """Panels of one size in rows of `columns`, with room above each for a two-line title."""

    count: int
    columns: int
    width: float
    height: float
    left: float
    top: float
    gap_x: float
    gap_y: float
    right: float = 16.0
    bottom: float = 44.0

    @property
    def rows(self) -> int:
        return math.ceil(self.count / self.columns)

    def origin(self, index: int) -> tuple[float, float]:
        row, column = divmod(index, self.columns)
        return (
            self.left + column * (self.width + self.gap_x),
            self.top + row * (self.height + self.gap_y),
        )

    @property
    def total_width(self) -> float:
        columns = min(self.columns, self.count)
        return self.left + columns * self.width + (columns - 1) * self.gap_x + self.right

    @property
    def total_height(self) -> float:
        return self.top + self.rows * self.height + (self.rows - 1) * self.gap_y + self.bottom


def decision_fold_differences(rows: Rows) -> str:
    """Per-fold candidate minus linear squad points, a panel per candidate, seasons along x."""

    name = "figure_decision_fold_differences.csv"
    _require(name, rows, ("candidate", "fold_id", "season", "difference"))
    candidates = _ordered(row["candidate"] for row in rows)
    seasons = sorted({row["season"] for row in rows})
    values = [_float(name, row, "difference") for row in rows]
    axis = ticks(min(*values, 0.0), max(*values, 0.0), 6)
    grid = Grid(len(candidates), 3, 230.0, 190.0, 74.0, 76.0, 22.0, 70.0)
    svg = Svg(
        grid.total_width,
        grid.total_height,
        "Per-fold paired decision differences by season",
        f"Drawn from {name} by scripts/paper_figures.py.",
    )
    svg.element("circle", {"cx": 80.0, "cy": 18.0, "r": 2.6, "fill": SERIES[0]})
    svg.text((90, 22), "one paired fold: candidate minus linear", 11, fill=SECONDARY)
    svg.line((330, 18), (352, 18), SERIES[1], 2.5)
    svg.text((358, 22), "season mean of the fold differences", 11, fill=SECONDARY)
    for index, candidate in enumerate(candidates):
        left, top = grid.origin(index)
        right, bottom = left + grid.width, top + grid.height
        scale = Scale(axis.low, axis.high, bottom, top)
        mine = [row for row in rows if row["candidate"] == candidate]
        _y_grid(svg, scale, axis, left, right, labels=index % grid.columns == 0)
        svg.line((left, scale(0.0)), (right, scale(0.0)), MUTED)
        svg.text((left, top - 22), candidate, 11, bold=True)
        svg.text((left, top - 8), f"{len(mine)} paired folds", 10, fill=SECONDARY)
        band = grid.width / len(seasons)
        for position, season in enumerate(seasons):
            start = left + position * band
            folds = sorted(
                (row for row in mine if row["season"] == season), key=lambda row: row["fold_id"]
            )
            svg.text((start + band / 2, bottom + 15), season, 10, "middle", SECONDARY)
            for order, row in enumerate(folds):
                x = start + band * (0.1 + 0.8 * (order + 0.5) / len(folds))
                svg.element(
                    "circle",
                    {
                        "cx": x,
                        "cy": scale(_float(name, row, "difference")),
                        "r": 2.2,
                        "fill": SERIES[0],
                        "fill-opacity": "0.7",
                    },
                    f"{candidate}, {row['fold_id']}: {row['difference']}",
                )
            if folds:
                mean = sum(_float(name, row, "difference") for row in folds) / len(folds)
                svg.line(
                    (start + 0.06 * band, scale(mean)),
                    (start + 0.94 * band, scale(mean)),
                    SERIES[1],
                    2.5,
                    title=f"{candidate}, {season} mean of {len(folds)} folds: {mean:.6f}",
                )
        if index % grid.columns == 0:
            centre = (top + bottom) / 2
            svg.text(
                (20, centre), "candidate minus linear, squad points", 11, "middle", rotate=True
            )
    return svg.render()


def _legend(
    svg: Svg, entries: Sequence[tuple[str, str, str]], left: float, top: float, width: float
) -> float:
    """Marker, line and label per series, wrapped to `width`; returns the height it took."""

    x, y = left, top
    for label, colour, shape in entries:
        needed = 34 + _width(label, 11) + 18
        if x > left and x + needed > left + width:
            x, y = left, y + 20
        svg.line((x, y), (x + 24, y), colour, 2.0)
        svg.marker(shape, (x + 12, y), colour)
        svg.text((x + 32, y + 4), label, 11, fill=SECONDARY)
        x += needed
    return y - top + 20


def decision_by_season(rows: Rows) -> str:
    """Each candidate's recorded mean decision difference by season, a line per candidate."""

    name = "figure_decision_by_season.csv"
    _require(name, rows, ("candidate", "season", "candidate_minus_linear_mean"))
    candidates = _ordered(row["candidate"] for row in rows)
    if len(candidates) > len(SERIES):
        raise FigureError(f"{name}: {len(candidates)} candidates, more than {len(SERIES)} series")
    seasons = sorted({row["season"] for row in rows})
    values = [_float(name, row, "candidate_minus_linear_mean") for row in rows]
    axis = ticks(min(*values, 0.0), max(*values, 0.0), 6)
    left, width, height = 74.0, 560.0, 300.0
    svg = Svg(
        left + width + 24,
        0.0,
        "Mean decision differences by season",
        f"Drawn from {name} by scripts/paper_figures.py.",
    )
    entries = [
        (candidate, SERIES[index], MARKERS[index]) for index, candidate in enumerate(candidates)
    ]
    top = 24 + _legend(svg, entries, left, 18, width) + 12
    bottom = top + height
    svg.height = bottom + 44
    scale = Scale(axis.low, axis.high, bottom, top)
    _y_grid(svg, scale, axis, left, left + width, labels=True)
    svg.line((left, scale(0.0)), (left + width, scale(0.0)), MUTED)

    def x_of(season: str) -> float:
        return left + width * (seasons.index(season) + 0.5) / len(seasons)

    for season in seasons:
        svg.text((x_of(season), bottom + 15), season, 10, "middle", SECONDARY)
    for colour, shape, candidate in zip(SERIES, MARKERS, candidates, strict=False):
        mine = sorted(
            (row for row in rows if row["candidate"] == candidate), key=lambda row: row["season"]
        )
        points = [
            (x_of(row["season"]), scale(_float(name, row, "candidate_minus_linear_mean")))
            for row in mine
        ]
        svg.polyline(points, colour, 2.0)
        for row, point in zip(mine, points, strict=True):
            svg.marker(
                shape,
                point,
                colour,
                f"{candidate}, {row['season']}: {row['candidate_minus_linear_mean']}",
            )
    svg.text(
        (20, (top + bottom) / 2),
        "mean candidate minus linear, squad points a gameweek",
        11,
        "middle",
        rotate=True,
    )
    return svg.render()


MAE_COLUMN = re.compile(r"points_mae_(\d{4}-\d{2})")


def matched_mae(name: str, row: dict[str, str], seasons: Sequence[str]) -> float:
    """The observation-weighted mean of an arm's season points MAE over `seasons`."""

    total = 0.0
    observations = 0.0
    for season in seasons:
        for column in (f"points_mae_{season}", f"points_observations_{season}"):
            if column not in row:
                raise FigureError(f"{name}: no column {column}")
        count = _float(name, row, f"points_observations_{season}")
        total += _float(name, row, f"points_mae_{season}") * count
        observations += count
    if observations <= 0:
        raise FigureError(f"{name}: no observations in {', '.join(seasons)}")
    return total / observations


def _labelled_points(
    svg: Svg,
    points: Sequence[tuple[float, float, str, str]],
    left: float,
    width: float,
    top: float,
    bottom: float,
) -> float:
    """Points with a label beside each, spread apart vertically, with a leader when moved.

    A label goes to the left of its point only when it does not fit inside the panel on the
    right and does fit on the left, so it never runs into the tick labels left of the panel.
    Returns the right edge of the rightmost label, so the canvas can be widened to hold it.
    """

    sides: dict[bool, list[int]] = {True: [], False: []}
    reach = left + width
    for index, (x, _, label, _) in enumerate(points):
        room_right = left + width - x
        room_left = x - left
        needed = 9 + _width(label, 11)
        to_the_right = needed <= room_right or needed > room_left
        sides[to_the_right].append(index)
        if to_the_right:
            reach = max(reach, x + needed)
    for to_the_right, members in sides.items():
        targets = [points[index][1] for index in members]
        placed = spread(targets, 14.0, top + 6, bottom - 6)
        for index, y_label in zip(members, placed, strict=True):
            x, y, label, title = points[index]
            offset = 9.0 if to_the_right else -9.0
            if abs(y_label - y) > 2:
                svg.line((x, y), (x + offset * 0.8, y_label), MUTED, 0.75)
            anchor = "start" if to_the_right else "end"
            svg.text((x + offset, y_label + 4), label, 11, anchor, INK, halo=True)
    for x, y, _, title in points:
        svg.marker("circle", (x, y), SERIES[0], title)
    return reach


def points_mae_against_squad_points(rows: Rows, decision_seasons: Sequence[str]) -> str:
    """Squad points on the decision folds against points MAE, pooled and season-matched."""

    name = "figure_points_mae_against_squad_points.csv"
    _require(name, rows, ("arm", "squad_points_decision_folds", "points_mae_pooled_all_seasons"))
    if not decision_seasons:
        raise FigureError("figure_decision_by_season.csv: no decision seasons")
    pooled_seasons = sorted(
        match.group(1) for column in rows[0] if (match := MAE_COLUMN.fullmatch(column))
    )
    if not pooled_seasons:
        raise FigureError(f"{name}: no points_mae_<season> column")
    arms = [row["arm"] for row in rows]
    squad = [_float(name, row, "squad_points_decision_folds") for row in rows]
    pooled = [_float(name, row, "points_mae_pooled_all_seasons") for row in rows]
    matched = [matched_mae(name, row, decision_seasons) for row in rows]
    x_axis = ticks(min(*pooled, *matched), max(*pooled, *matched), 4)
    y_axis = ticks(min(squad), max(squad), 5)
    left, width, height, gap, top = 74.0, 320.0, 300.0, 72.0, 44.0
    bottom = top + height
    svg = Svg(
        left + 2 * width + gap + 24,
        bottom + 62,
        "Points MAE against realized squad points",
        f"Drawn from {name} and the seasons of figure_decision_by_season.csv by "
        "scripts/paper_figures.py.",
    )
    y_scale = Scale(y_axis.low, y_axis.high, bottom, top)
    panels = (
        (f"points MAE pooled over {_span(pooled_seasons)}, as recorded", pooled, "pooled"),
        (
            f"points MAE over {_span(decision_seasons)}, observation-weighted",
            matched,
            "matched",
        ),
    )
    for panel, (label, xs, kind) in enumerate(panels):
        start = left + panel * (width + gap)
        x_scale = Scale(x_axis.low, x_axis.high, start, start + width)
        _y_grid(svg, y_scale, y_axis, start, start + width, labels=True)
        _x_grid(svg, x_scale, x_axis, top, bottom)
        svg.text((start + width / 2, bottom + 36), label, 11, "middle")
        svg.text((start, top - 14), f"{kind} MAE", 11, bold=True)
        points = [
            (
                x_scale(x),
                y_scale(y),
                arm,
                f"{arm}, {kind}: points MAE {x:.6f}, squad points {y:.6f}",
            )
            for arm, x, y in zip(arms, xs, squad, strict=True)
        ]
        reach = _labelled_points(svg, points, start, width, top, bottom)
        svg.width = max(svg.width, reach + 16)
    centre = (top + bottom) / 2
    svg.text((18, centre), "mean realized squad points a gameweek", 11, "middle", rotate=True)
    svg.text((32, centre), f"decision folds {_span(decision_seasons)}", 11, "middle", rotate=True)
    return svg.render()


def _bin(name: str, value: float, bins: int) -> int:
    if not 0.0 <= value <= 1.0:
        raise FigureError(f"{name}: PIT {value} is outside [0, 1]")
    edges = [index / bins for index in range(bins + 1)]
    return min(bisect_right(edges, value) - 1, bins - 1)


def sampler_pit(rows: Rows, bins: int = PIT_BINS) -> str:
    """A PIT histogram per record and arm, each bin's fold count against the uniform count."""

    name = "figure_sampler_pit.csv"
    _require(name, rows, ("sampler", "arm", "record", "pit"))
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["record"], row["arm"]), []).append(row)
    histograms = []
    for (record, arm), members in groups.items():
        samplers = _ordered(row["sampler"] for row in members)
        if len(samplers) != 1:
            raise FigureError(f"{name}: {record} {arm} names samplers {samplers}")
        counts = [0] * bins
        for row in members:
            counts[_bin(name, _float(name, row, "pit"), bins)] += 1
        histograms.append((samplers[0], record, arm, counts, len(members)))
    highest = max(max(max(counts), total / bins) for _, _, _, counts, total in histograms)
    axis = ticks(0.0, highest, 5)
    grid = Grid(len(histograms), 3, 230.0, 150.0, 74.0, 82.0, 22.0, 96.0)
    svg = Svg(
        grid.total_width,
        grid.total_height,
        "Sampler PIT histograms",
        f"Drawn from {name} by scripts/paper_figures.py.",
    )
    svg.rect((74.0, 12.0), (14.0, 12.0), SERIES[0])
    svg.text((94, 22), f"folds per PIT bin of width {1 / bins:g}", 11, fill=SECONDARY)
    svg.line((290, 18), (312, 18), SECONDARY, 1.5, "4 3")
    svg.text((318, 22), "folds per bin under a uniform PIT", 11, fill=SECONDARY)
    x_axis = ticks(0.0, 1.0, 5)
    for index, (sampler, record, arm, counts, total) in enumerate(histograms):
        left, top = grid.origin(index)
        right, bottom = left + grid.width, top + grid.height
        scale = Scale(axis.low, axis.high, bottom, top)
        x_scale = Scale(0.0, 1.0, left, right)
        _y_grid(svg, scale, axis, left, right, labels=index % grid.columns == 0)
        svg.text((left, top - 36), f"{sampler}, n = {total}", 11, bold=True)
        svg.text((left, top - 22), Path(record).stem, 10, fill=SECONDARY)
        svg.text((left, top - 8), arm, 10, fill=SECONDARY)
        for position, count in enumerate(counts):
            x0, x1 = x_scale(position / bins), x_scale((position + 1) / bins)
            svg.rect(
                (x0 + 1, scale(count)),
                (x1 - x0 - 2, scale(0.0) - scale(count)),
                SERIES[0],
                f"{Path(record).stem} {arm}, PIT [{position / bins:g}, "
                f"{(position + 1) / bins:g}{']' if position == bins - 1 else ')'}: {count}",
            )
        svg.line((left, bottom), (right, bottom), MUTED)
        uniform = scale(total / bins)
        svg.line((left, uniform), (right, uniform), SECONDARY, 1.5, "4 3")
        for value in x_axis.values:
            svg.text((x_scale(value), bottom + 15), x_axis.label(value), 10, "middle", SECONDARY)
        svg.text(((left + right) / 2, bottom + 32), "PIT", 10, "middle", SECONDARY)
        if index % grid.columns == 0:
            svg.text((20, (top + bottom) / 2), "folds", 11, "middle", rotate=True)
    return svg.render()


def s2_counts(rows: Rows, calibration: Rows) -> str:
    """Each arm's pooled lower-tail fold count, with its S2 bounds as counts where recorded."""

    name = "figure_s2_counts.csv"
    _require(name, rows, ("sampler", "arm", "scope", "fold_count", "below_q10_count", "record"))
    table = "table_sampler_calibration.csv"
    _require(table, calibration, ("record", "arm", "s2_bounds_low", "s2_bounds_high"))
    pooled = [row for row in rows if row["scope"] == "pooled"]
    if not pooled:
        raise FigureError(f"{name}: no pooled rows")
    bounds: dict[tuple[str, str], tuple[float, float] | None] = {}
    for row in calibration:
        recorded = row["s2_bounds_low"] != "" and row["s2_bounds_high"] != ""
        bounds[(row["record"], row["arm"])] = (
            (_float(table, row, "s2_bounds_low"), _float(table, row, "s2_bounds_high"))
            if recorded
            else None
        )
    bars = []
    for row in pooled:
        key = (row["record"], row["arm"])
        if key not in bounds:
            raise FigureError(f"{table}: no row for {key[0]} {key[1]}")
        folds = _float(name, row, "fold_count")
        band = bounds[key]
        counts = None if band is None else (band[0] * folds, band[1] * folds)
        bars.append((row, _float(name, row, "below_q10_count"), folds, counts))
    reach = [count for _, count, _, _ in bars]
    reach += [edge for *_, counts in bars if counts is not None for edge in counts]
    axis = ticks(0.0, max(reach), 5)
    labels = [(row["sampler"], f"{Path(row['record']).stem} {row['arm']}") for row, *_ in bars]
    left = 24 + max(max(_width(a, 11), _width(b, 10)) for a, b in labels)
    width, row_height, top = 420.0, 46.0, 52.0
    bottom = top + row_height * len(bars)
    scale = Scale(axis.low, axis.high, left, left + width)
    notes = [
        f"{row['below_q10_count']} of {row['fold_count']}"
        + (", no S2 bounds in the record" if counts is None else "")
        for row, _, _, counts in bars
    ]
    reach_right = max(
        scale(count) + 6 + _width(note, 10)
        for (_, count, _, _), note in zip(bars, notes, strict=True)
    )
    svg = Svg(
        max(left + width, reach_right) + 16,
        bottom + 56,
        "S2 lower-tail fold counts",
        f"Drawn from {name} and {table} by scripts/paper_figures.py.",
    )
    svg.rect((left, 12.0), (22.0, 12.0), BAND)
    svg.line((left, 12), (left, 24), MUTED, 1.0, "3 2")
    svg.line((left + 22, 12), (left + 22, 24), MUTED, 1.0, "3 2")
    svg.text((left + 28, 22), "S2 bounds of the record, as fold counts", 11, fill=SECONDARY)
    svg.rect((left + 290, 12.0), (22.0, 12.0), SERIES[0])
    svg.text((left + 318, 22), "folds realized below q10", 11, fill=SECONDARY)
    for value in axis.values:
        svg.line((scale(value), top), (scale(value), bottom), GRID)
        svg.text((scale(value), bottom + 15), axis.label(value), 10, "middle", SECONDARY)
    for index, ((row, count, folds, counts), (first, second), note) in enumerate(
        zip(bars, labels, notes, strict=True)
    ):
        y = top + index * row_height
        centre = y + row_height / 2
        svg.text((left - 10, centre - 3), first, 11, "end", bold=True)
        svg.text((left - 10, centre + 11), second, 10, "end", SECONDARY)
        if counts is not None:
            svg.rect(
                (scale(counts[0]), y + 5),
                (scale(counts[1]) - scale(counts[0]), row_height - 10),
                BAND,
                f"S2 bounds of {second}: {counts[0]:.2f} to {counts[1]:.2f} of {folds:g} folds",
            )
            for edge in counts:
                svg.line((scale(edge), y + 5), (scale(edge), y + row_height - 5), MUTED, 1.0, "3 2")
        svg.rect(
            (left, centre - 8),
            (scale(count) - left, 16.0),
            SERIES[0],
            f"{second}: {row['below_q10_count']} of {row['fold_count']} folds",
        )
        svg.text((scale(count) + 6, centre + 4), note, 10, fill=INK, halo=True)
    svg.line((left, top), (left, bottom), MUTED)
    svg.text(
        (left + width / 2, bottom + 36),
        "folds realized below the scenario tenth percentile, pooled",
        11,
        "middle",
    )
    return svg.render()


@dataclass(frozen=True)
class Figure:
    file: str
    tables: tuple[str, ...]
    draw: Callable[[dict[str, Rows]], str]


FIGURES: tuple[Figure, ...] = (
    Figure(
        "fig1_decision_fold_differences.svg",
        ("figure_decision_fold_differences.csv",),
        lambda t: decision_fold_differences(t["figure_decision_fold_differences.csv"]),
    ),
    Figure(
        "fig2_decision_by_season.svg",
        ("figure_decision_by_season.csv",),
        lambda t: decision_by_season(t["figure_decision_by_season.csv"]),
    ),
    Figure(
        "fig3_points_mae_against_squad_points.svg",
        ("figure_points_mae_against_squad_points.csv", "figure_decision_by_season.csv"),
        lambda t: points_mae_against_squad_points(
            t["figure_points_mae_against_squad_points.csv"],
            sorted({row["season"] for row in t["figure_decision_by_season.csv"]}),
        ),
    ),
    Figure(
        "fig4_sampler_pit.svg",
        ("figure_sampler_pit.csv",),
        lambda t: sampler_pit(t["figure_sampler_pit.csv"]),
    ),
    Figure(
        "fig5_s2_counts.svg",
        ("figure_s2_counts.csv", "table_sampler_calibration.csv"),
        lambda t: s2_counts(t["figure_s2_counts.csv"], t["table_sampler_calibration.csv"]),
    ),
)


def draw(tables: Path, output_dir: Path) -> list[Path]:
    """Every figure from the table files in `tables`, written under `output_dir`.

    All table files are read and every figure drawn before anything is written, so a refused
    table leaves no partial set of figures behind.
    """

    names = sorted({table for figure in FIGURES for table in figure.tables})
    loaded = {table: read_rows(tables / table) for table in names}
    drawn = {figure.file: figure.draw(loaded) for figure in FIGURES}
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for file, text in drawn.items():
        path = output_dir / file
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


@dataclass(frozen=True)
class Manifest:
    """What a Markdown manifest pins: output digests, and the digests of the files read."""

    outputs: dict[str, str | None]
    inputs: dict[str, tuple[str, str]]


SHA256 = re.compile(r"`([0-9a-f]{64})`")
BLOB = re.compile(r"`([0-9a-f]{40})`")
OUTPUT_PATH = re.compile(r"`((?:tables|figures)/[^`]+)`")
INPUT_PATH = re.compile(r"`((?:docs|scripts)/[^`]+\.(?:json|py))`")
INPUT_KEY = re.compile(r"[A-Z]+\d+")


def read_manifest(text: str) -> Manifest:
    """The rows of a Markdown manifest.

    An output row's first cell is a backticked path under `tables/` or `figures/`, and its last
    backticked SHA-256 is the digest pinned (none: the row pins no digest). An input row's first
    cell is a key such as `R1` and its second a backticked path under `docs/` or `scripts/`,
    with one backticked git blob id and one SHA-256.
    """

    outputs: dict[str, str | None] = {}
    inputs: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        output = OUTPUT_PATH.fullmatch(cells[0])
        if output:
            path = output.group(1)
            if path in outputs:
                raise FigureError(f"manifest: two rows for {path}")
            digests = SHA256.findall(line)
            outputs[path] = digests[-1] if digests else None
            continue
        source = INPUT_PATH.fullmatch(cells[1]) if len(cells) > 1 else None
        if source and INPUT_KEY.fullmatch(cells[0]):
            path = source.group(1)
            blobs, digests = BLOB.findall(line), SHA256.findall(line)
            if len(blobs) != 1 or len(digests) != 1 or path in inputs:
                raise FigureError(f"manifest: the row of {path} needs one blob and one SHA-256")
            inputs[path] = (blobs[0], digests[0])
    if not outputs:
        raise FigureError("manifest: no output row")
    return Manifest(outputs, inputs)


def _sha256(path: Path) -> str:
    return paper_record_tables.Digest.of(path.read_bytes()).sha256_lf


def input_digests(tables: Path) -> dict[str, tuple[str, str]]:
    """Blob id and SHA-256 of each record and of the extractor (from `records.csv`), and of
    this file, all read as the extractor reads a record (CRLF as LF)."""

    digests = {
        row["record"]: (row["git_blob_lf"], row["sha256_lf"])
        for row in read_rows(tables / "records.csv")
    }
    own = paper_record_tables.Digest.of(SCRIPT_SOURCE.read_bytes())
    digests[SCRIPT] = (own.blob_lf, own.sha256_lf)
    return digests


def compare(
    manifest: Manifest, directory: Path, inputs: dict[str, tuple[str, str]]
) -> tuple[list[str], bool]:
    """Report lines for every output and input against the manifest, and whether all match."""

    produced = {
        path.relative_to(directory).as_posix(): path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    lines: list[str] = []
    holds = True
    for name in sorted(set(produced) | set(manifest.outputs)):
        expected = manifest.outputs.get(name, "")
        if name not in produced:
            lines.append(f"  MISSING   {name}: in the manifest, not written")
            holds = False
        elif name not in manifest.outputs:
            lines.append(f"  NO ROW    {name}: written, not in the manifest")
            holds = False
        elif expected is None:
            lines.append(f"  unpinned  {name}")
        elif (actual := _sha256(produced[name])) != expected:
            lines.append(f"  DIFFERS   {name}: manifest {expected}, regenerated {actual}")
            holds = False
        else:
            lines.append(f"  ok        {name}")
    for name in sorted(set(inputs) | set(manifest.inputs)):
        if name not in inputs:
            lines.append(f"  NOT READ  {name}: in the manifest, not read")
            holds = False
        elif name not in manifest.inputs:
            lines.append(f"  NO ROW    {name}: read, not in the manifest")
            holds = False
        elif inputs[name] != manifest.inputs[name]:
            lines.append(
                f"  DIFFERS   {name}: manifest {' '.join(manifest.inputs[name])}, "
                f"read {' '.join(inputs[name])}"
            )
            holds = False
        else:
            lines.append(f"  ok        {name}")
    return lines, holds


def regenerate(root: Path, directory: Path) -> list[paper_record_tables.Check]:
    """The tables under `directory/tables` and the figures under `directory/figures`."""

    try:
        checks, _ = paper_record_tables.extract(root, directory / "tables")
    except paper_record_tables.RecordError as error:
        raise FigureError(f"the tables were refused: {error}") from error
    draw(directory / "tables", directory / "figures")
    return checks


def check(root: Path, manifest_path: Path, output_dir: Path | None) -> int:
    path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    if not path.is_file():
        raise FigureError(f"no manifest {path}")
    manifest = read_manifest(path.read_text(encoding="utf-8"))

    def run(directory: Path) -> tuple[list[paper_record_tables.Check], list[str], bool]:
        checks = regenerate(root, directory)
        lines, holds = compare(manifest, directory, input_digests(directory / "tables"))
        return checks, lines, holds

    if output_dir is None:
        with tempfile.TemporaryDirectory(prefix="paper-check-") as temporary:
            checks, lines, holds = run(Path(temporary))
    else:
        checks, lines, holds = run(output_dir)
    failed = [item for item in checks if not item.holds]
    print(f"Regenerated the paper tables and figures from {root}")
    print("\n".join(lines))
    print(f"  {len(checks) - len(failed)} of {len(checks)} record checks hold")
    for item in failed:
        print(f"  FAILS: {item.name}")
    matched = sum(line.startswith("  ok") for line in lines)
    print(f"  {matched} of {len(lines)} manifest rows match")
    return 0 if holds and not failed else 1


def resolve_output(root: Path, output: Path | None, default: Path) -> Path:
    """The output directory; inside the checkout it must sit under the ignored `artifacts/`."""

    root = root.resolve()
    directory = (root / (output or default)).resolve()
    allowed = root / OUTPUT_ROOT
    if directory.is_relative_to(root) and not directory.is_relative_to(allowed):
        raise FigureError(f"inside the checkout only {OUTPUT_ROOT}/ is written: {directory}")
    if directory == allowed:
        raise FigureError(f"name a folder under {OUTPUT_ROOT}/, not {OUTPUT_ROOT}/ itself")
    return directory


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="the checkout that relative paths are read from (default: this one)",
    )
    parser.add_argument(
        "--tables",
        type=Path,
        default=None,
        help=f"the folder the extractor wrote, relative to --root; default {DEFAULT_TABLES}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"relative to --root unless absolute; default {DEFAULT_OUTPUT}, or with --check a "
            "temporary folder"
        ),
    )
    parser.add_argument(
        "--check",
        type=Path,
        default=None,
        metavar="MANIFEST",
        help="regenerate the tables and figures and compare their digests with this manifest",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    root: Path = arguments.root.resolve()
    try:
        if arguments.check is not None:
            output = arguments.output_dir
            directory = None if output is None else resolve_output(root, output, DEFAULT_OUTPUT)
            return check(root, arguments.check, directory)
        tables = (root / (arguments.tables or DEFAULT_TABLES)).resolve()
        output_dir = resolve_output(root, arguments.output_dir, DEFAULT_OUTPUT)
        written = draw(tables, output_dir)
    except FigureError as error:
        print(f"Paper figures refused: {error}")
        return 1
    print(f"Wrote {len(written)} paper figures to {output_dir} from {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
