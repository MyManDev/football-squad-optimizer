"""Regenerate the committed synthetic sample data.

Run from the repository root:

    python -m scripts.generate_sample_data

The committed CSV is reproducible from code rather than being an opaque blob, and
a test asserts that the file on disk still matches this generator, so the two
cannot drift apart. The data is entirely synthetic: no third-party dataset is
redistributed here.
"""

from pathlib import Path

from tests.fixtures.synthetic_gameweeks import make_raw_gameweeks

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPOSITORY_ROOT / "data" / "sample"
SAMPLE_FILE = SAMPLE_DIR / "raw_player_gameweeks.csv"


def main() -> None:
    """Write the synthetic raw player-gameweek panel to the sample directory."""

    frame = make_raw_gameweeks()
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # A fixed line terminator keeps the file byte-identical across platforms.
    frame.to_csv(SAMPLE_FILE, index=False, lineterminator="\n")
    print(f"Wrote {len(frame)} rows and {len(frame.columns)} columns to {SAMPLE_FILE}")


if __name__ == "__main__":
    main()
