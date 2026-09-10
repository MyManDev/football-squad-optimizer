# Queue recovery and attempt ownership

`queue_contracts` defines the adapter interface; `file_advice_queue` implements storage;
`advice_queue` orchestrates an injected computation and preserves the old public imports.
The domain calculation and the public `backend_jobs_v1` record are unchanged.

## Transaction boundaries

Short metadata transactions use a permanent OS-locked `.queue.lock` file. A process exit
releases the lock; the file is never deleted or replaced. Solving happens outside the lock.
Recovery, claiming, heartbeat, terminal writes and cache publication all check the persisted
attempt under that same lock. An old attempt cannot refresh or remove a replacement claim,
write its result, or publish cache bytes before the ownership check.

| Interrupted prefix | Recovery |
| --- | --- |
| Open-key intent, no job document | Publish the exact queued job carried by the intent |
| Claim marker, still queued | Remove the incomplete claim; no worker received a running job |
| Requeued document, old claim marker | Remove the marker without incrementing the attempt twice |
| Cache bytes, still running | Recover after lease expiry; identical recomputation remains idempotent |
| Terminal document, index/claim left over | Complete cleanup without rewriting the terminal outcome |

Legacy job documents and id-only indexes are readable. A legacy index with no job was never
acknowledged by the old submission path; its exact bytes are retained before releasing that
incomplete reservation. A malformed record is never treated as a valid absence: scans retain
its bytes in `integrity/`, emit an `advice_queue_integrity_issue` event and continue unrelated
jobs. Its existing reservation remains blocked, preventing duplicate work under that key.
Evidence metadata records the original filename and SHA-256. Evidence is not automatically deleted.

## Upgrade and acceptance

Drain/stop old API and worker processes before changing this adapter; older processes do not
honor the transaction lock or attempt-qualified heartbeat. Then start the updated worker and
run recovery before accepting new work. Do not mix old and new writers against one store.

Process crash safety is distinct from storage failure or a host power outage. Payload files
are flushed before atomic publication; an independent backup is still required. The deployed
shared filesystem must pass the actual multi-process locking and publication acceptance,
including across hosts before adding replicas. A passing local NTFS test does not establish
NFS behavior. Python documents the platform lock primitives in
[fcntl](https://docs.python.org/3/library/fcntl.html) and
[msvcrt](https://docs.python.org/3/library/msvcrt.html).

Synthetic regression coverage lives in `tests/unit/test_queue_recovery.py`: five child-process
termination points, two recoverers, process claim contention, stale heartbeat/store/cache
publication, lost worker ownership, malformed identity and corruption isolation. Existing
worker/cache/API tests preserve deterministic conflict detection and public behavior.
