# Raw release and check scripts (seed)

These are the scripts every release since 16 September was cut and checked with, copied as they
were from a session scratch directory. They carry absolute paths of that machine and are not
wired to anything. This branch exists so tasks A6 and A7 of the two-week plan have the source to
start from: move what they do into `scripts/check_league_tree.py` and `scripts/release/`, then
delete this directory in the same PRs.

- `verify_variants_tree.py`, `verify_top100_tree.py`, `verify_word_tree.py`: the tree checkers.
- `queue2.sh`: rebase a PR in its worktree, wait for CLEAN, squash merge with a cleaned body.
- `ship_generic.sh`: wait for the site PR, cut the release as a two-parent merge whose tree is
  develop's, merge it, then `deploy.sh` and `verify_live.py`.
- `deploy.sh`: wait for green main CI with one site artifact, tag, dispatch `deploy-pages.yml`.
- `verify_live.py`: ten smoke checks and the content checks against the live site.
- `site_pr_decision.sh`: the hand publish of a weekly run's preview on a new site branch.
