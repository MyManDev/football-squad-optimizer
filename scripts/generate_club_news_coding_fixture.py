"""Regenerate the committed synthetic coding fixture.

Run from the repository root:

    python -m scripts.generate_club_news_coding_fixture

Like its sibling, the fixture is reproducible from code rather than an opaque blob, and a
test asserts the file on disk still matches this generator. This one is derived from the
located fixture as well, so the two files agree by construction: every quote it carries is
cut out of the other fixture's document bytes at the offsets that file declares. Nothing
here is any club's captured text.
"""

import json
from pathlib import Path

from tests.fixtures.synthetic_club_news_coding import make_club_news_coding_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPOSITORY_ROOT / "data" / "sample"
FIXTURE_FILE = SAMPLE_DIR / "club_news_coding_v1.fixture.json"


def main() -> None:
    """Write the synthetic coding fixture to the sample directory."""

    document = make_club_news_coding_fixture()
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a fixed trailing newline keep the file byte-identical across platforms
    # and across two runs of this script.
    FIXTURE_FILE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    coded = json.loads(document["response"]["text"])["claims"]
    print(
        f"Wrote {len(coded)} coded claim(s) and "
        f"{len(document['unlocatable_responses'])} refusal(s) to {FIXTURE_FILE}"
    )


if __name__ == "__main__":
    main()
