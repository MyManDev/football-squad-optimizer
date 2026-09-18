"""Remove attribution lines and normalize punctuation before a squash merge."""

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(r"\s+\u2014\s+", ", ", text)
text = text.replace("\u2014", ": ").replace("\u2013", "-")
lines = []
for line in text.splitlines():
    if re.search(
        r"co-?authored-by|generated with|(?<![\w./-])(?:claude|codex)(?![\w/-])"
        r"|chatgpt|openai|anthropic|\bAI\b",
        line,
        re.I,
    ):
        continue
    lines.append(line)
cleaned = "\n".join(lines).strip()
if not cleaned:
    sys.exit("body file empty after cleaning, NOT merging")
path.write_text(cleaned + "\n", encoding="utf-8")
