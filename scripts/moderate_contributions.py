"""Host operator moderation. Requires filesystem access; never exposes a web admin token."""

import argparse
import json
import os
from pathlib import Path

from squadopt.platform.contributions import ContributionStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pending", "approve", "reject"))
    parser.add_argument("comment_id", type=int, nargs="?")
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()
    root = os.environ.get("SQUADOPT_BACKEND_STORE_ROOT")
    path = args.db or (Path(root) / "contributions.sqlite3" if root else None)
    if path is None or not path.is_file():
        parser.error("An existing contribution database is required")
    store = ContributionStore(path)
    if args.action == "pending":
        # JSON escapes control characters in untrusted text, including terminal escapes.
        print(json.dumps(store.pending(), ensure_ascii=True, indent=2))
    else:
        if args.comment_id is None:
            parser.error("comment_id is required")
        store.moderate(args.comment_id, "approved" if args.action == "approve" else "rejected")
        print("Moderation saved")


if __name__ == "__main__":
    main()
