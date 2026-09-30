"""One preregistered certified-hint comparison; no production activation."""

import argparse
from pathlib import Path

from scripts.measure_temporal_refinement import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "artifact-root", "evidence", "states", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    run(**vars(parser.parse_args()), incumbent_comparison=True)
