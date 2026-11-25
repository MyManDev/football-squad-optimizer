# Frozen named-chip cache parity

The two cold workers agreed on solver status, weekly transfers, solver objective and published net points at the same address and immutable specification in 16 of 16 paired controls. Each pair submitted the same chip, preferences, member and horizon to isolated local instances of the API, queue, cache and worker. The run-bound request included a run reference. Both used the same frozen API context.

Producer commit `b9eb642470b503f00a06ddc750ace454f49b757e`. OR-Tools `9.15.6755`.

- Completed solver statuses matched in 16/16.
- Weekly transfer decisions matched in 16/16.
- Solver objectives matched in 16/16.
- Published net points matched in 16/16.
- Cache addresses matched in 16/16.
- Immutable request specifications matched in 16/16.
- Cached bytes (audit) matched in 16/16.

| Member-week | Chip | Weeks | Bound status | Legacy status | Bound objective | Legacy objective | Bound minus legacy | Bound net points | Legacy net points | Transfers equal | Bound work / allocation | Legacy CP units / native calls |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| gw8-2199732 | wildcard | 1 | OPTIMAL | OPTIMAL | 58.527 | 58.527 | 0 | 58.527 | 58.527 | yes | 0.90463626 / 21.0 | 1.63856678 / 0 |
| gw8-2199732 | wildcard | 3 | OPTIMAL | OPTIMAL | 175.581 | 175.581 | 0 | 175.581 | 175.581 | yes | 80.98560922 / 122.0 | 38.68618914 / 4 |
| gw8-2281624 | freehit | 1 | OPTIMAL | OPTIMAL | 58.214 | 58.214 | 0 | 58.214 | 58.214 | yes | 0.92902301 / 21.0 | 1.70877261 / 0 |
| gw8-2281624 | freehit | 3 | OPTIMAL | OPTIMAL | 167.869 | 167.869 | 0 | 167.869 | 167.869 | yes | 72.25062312 / 122.0 | 37.2195998 / 5 |
| gw8-5349883 | wildcard | 1 | OPTIMAL | OPTIMAL | 57.443 | 57.443 | 0 | 57.443 | 57.443 | yes | 0.93775491 / 21.0 | 1.74432144 / 0 |
| gw8-5349883 | wildcard | 3 | OPTIMAL | OPTIMAL | 172.329 | 172.329 | 0 | 172.329 | 172.329 | yes | 90.02793518 / 122.0 | 52.56320761 / 4 |
| gw8-5662073 | freehit | 1 | OPTIMAL | OPTIMAL | 57.892 | 57.892 | 0 | 57.892 | 57.892 | yes | 0.95115553 / 21.0 | 1.73066875 / 0 |
| gw8-5662073 | freehit | 3 | OPTIMAL | OPTIMAL | 166.562 | 166.562 | 0 | 166.562 | 166.562 | yes | 63.51781756 / 122.0 | 34.9984673 / 5 |
| gw9-2199732 | wildcard | 1 | OPTIMAL | OPTIMAL | 58.778 | 58.778 | 0 | 58.778 | 58.778 | yes | 0.91852389 / 21.0 | 1.68979404 / 0 |
| gw9-2199732 | wildcard | 3 | OPTIMAL | OPTIMAL | 176.334 | 176.334 | 0 | 176.334 | 176.334 | yes | 120.00555451 / 122.0 | 102.30160523 / 4 |
| gw9-2281624 | freehit | 1 | OPTIMAL | OPTIMAL | 58.643 | 58.643 | 0 | 58.643 | 58.643 | yes | 0.89483987 / 21.0 | 1.78983325 / 0 |
| gw9-2281624 | freehit | 3 | OPTIMAL | OPTIMAL | 167.736 | 167.736 | 0 | 167.736 | 167.736 | yes | 63.29144456 / 122.0 | 28.06322594 / 5 |
| gw9-5349883 | wildcard | 1 | OPTIMAL | OPTIMAL | 57.808 | 57.808 | 0 | 57.808 | 57.808 | yes | 0.92246182 / 21.0 | 1.7179459 / 0 |
| gw9-5349883 | wildcard | 3 | OPTIMAL | OPTIMAL | 173.424 | 173.424 | 0 | 173.424 | 173.424 | yes | 81.90305303 / 122.0 | 103.3861221 / 4 |
| gw9-5662073 | freehit | 1 | OPTIMAL | OPTIMAL | 58.285 | 58.285 | 0 | 58.285 | 58.285 | yes | 0.91108 / 21.0 | 2.01792635 / 0 |
| gw9-5662073 | freehit | 3 | OPTIMAL | OPTIMAL | 159.686 | 159.686 | 0 | 159.686 | 159.686 | yes | 75.72150956 / 122.0 | 35.48863687 / 5 |

The JSON retains both cache addresses, specification and document hashes, the solver status, objective, published net points, transfer IDs for every week, individual solver calls and the durable run receipt. The frozen Phase 1 direct-planner control is recorded separately. The equality columns compare the two actual worker outcomes.

The adapter uses frozen Phase 1 players, expected points, fixture counts, transfer balances, held players and sale proceeds. It reconstructs an equivalent purchase basis at the frozen prices. Both workers receive the capture timestamp and a synthetic deadline one day later. The replay grants the named chip for the requested week using synthetic chip rights. These controls compare worker behavior on fixed inputs.
