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
        r"co-?authored-by|generated with|claude|codex|chatgpt|openai|anthropic|\bAI\b", line, re.I
    ):
        continue
    lines.append(line)
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
