# Working in a local checkout

Branch and edit in a git worktree. Leave the main checkout on `develop`, clean.

```console
git worktree add .codex-tmp/worktrees/<name> -b <branch> origin/develop
```

Two reasons, and both have already cost time.

**The weekly run executes from this checkout and refuses three ways.** A modified tree raises
`Weekly evidence requires a clean source checkout`. A `HEAD` that is not the declared revision
raises on the mismatch. And `check_publication_base` refuses when the checkout is not at
`origin/develop`. The third is the one a "is it clean, is it behind" glance misses, and all three
land at preflight on a deadline afternoon, after the solve has been spent. Check with:

```console
git fetch origin && git merge --ff-only origin/develop
```

**Branching from this checkout carries whatever it is standing on.** `git switch -c` from a
`develop` that is not at `origin/develop` puts someone else's commit on your branch, and a squash
merge then bundles two unrelated changes under one message. That happened on 2026-09-14: a
documentation pull request absorbed a web feature, and the feature's own pull request closed
itself as empty because its content had already landed. Nothing was lost and both changes were
gate-tested together, but the history now describes half of what it contains. Branching from
`origin/develop` explicitly, as above, cannot do this.

A worktree is cheap and disposable. `git worktree remove <path>` when the branch has merged, and
never delete a directory another worktree is using: on Windows a recursive delete follows
directory junctions and takes the target's contents with it, which is how the live captures were
lost on 2026-09-10.

