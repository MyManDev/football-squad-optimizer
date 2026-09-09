# Preserved development before main alignment

This branch preserves the complete develop tree before alignment to published main.
BRANCHES.json maps former local/remote names to their exact commit. Every listed commit,
including detached worktree heads and the primary public-data snapshot, is reachable
through this archive commit's parents. Their changes are not silently combined into
the archive's source tree.

Inspect an old tree with `git show COMMIT:path`; restore a topic with
`git switch -c restored/topic COMMIT`. Review and port only the desired changes to develop.
Do not merge this aggregate archive commit into develop: it represents preservation,
not acceptance of every historical implementation.

The primary local publication snapshot preserves the pre-cleanup web/public/data state.
Other uncommitted work and ignored local data remain in their original worktrees.
The archive is not a backup of private data/ records or ignored scratch evidence.
