"""Regenerate the committed synthetic club-news fixture.

Run from the repository root:

    python -m scripts.generate_club_news_fixture

The fixture is reproducible from code rather than an opaque blob, and a test asserts the
file on disk still matches this generator, so the two cannot drift apart. Every document
in it was written for it: no club's captured bytes are redistributed here, and real
captures stay under `data/snapshots/`, which is gitignored.
"""

import json
from pathlib import Path

from tests.fixtures.synthetic_club_news import make_club_news_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPOSITORY_ROOT / "data" / "sample"
FIXTURE_FILE = SAMPLE_DIR / "club_news_v1.fixture.json"


def main() -> None:
    """Write the synthetic club-news fixture to the sample directory."""

    document = make_club_news_fixture()
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a fixed trailing newline keep the file byte-identical across
    # platforms and across two runs of this script.
    FIXTURE_FILE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(document['documents'])} document(s), "
        f"{len(document['roster'])} roster entries and "
        f"{len(document['unparseable_responses'])} unparseable response(s) to {FIXTURE_FILE}"
    )


if __name__ == "__main__":
    main()
