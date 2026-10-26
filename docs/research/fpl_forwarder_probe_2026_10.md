# FPL forwarder probe, October 2026: served

**Record:** [fpl_forwarder_probe_2026_10.json](fpl_forwarder_probe_2026_10.json).
- Under `answer` it holds the whole answer of `https://squadopt.mymandev.com/api/v1/fpl-probe`, unchanged. Written compactly (`separators=(",", ":")`), `answer` gives the served bytes: 118,961 bytes, sha256 `18180d15270800db9490039f543006fa0684d08eb01a0171e1320e5d391825d3`.
- The answer was read at 2026-10-26T05:45:02.758Z (its `generated_at`). It holds 424 records: 422 scheduled and 2 live.
- `repository_commit` is 7a12483c, the develop commit the Worker was deployed from by run 39676751754 on 2026-10-21.

The probe, what it stores and the verdict rule are in [the probe's doc](../fpl_forwarder_probe.md). The rule was fixed before any data (#979).

## Verdict

**Served.** The rule's window runs from the first scheduled standings slot, 2026-10-21T21:30:13.438Z, to 2026-10-24T21:30:13.438Z. In it, 147 of 147 scheduled standings probes answered HTTP 200 with a JSON body.
- Share 1.0, against 95 percent.
- At least 130 probes required.
- `unslotted` 0.

This is the record's own `summary.verdict`, and it was recomputed from the records to the same counts.

## Reading

- **Every slot holds a probe.** The window has 145 slots, one every 30 minutes with both ends included, and all 145 hold a standings probe. Consecutive slots are 30 minutes apart throughout.
- **Two slots ran twice.** 2026-10-23T07:00:13Z and 09:00:13Z each hold two records, which is why the window holds 147. Counted once per slot, the window is 145 of 145, so the repeats change nothing.
- **Response times.** The standings answers in the window took 31 ms at least, 209 ms at the median, 833 ms at the 95th percentile and 1,565 ms at most. Each body was 3,316 to 3,331 bytes.
- **Where they ran from.** The scheduled probes ran from 28 Cloudflare data centres; the most frequent were SJC, AMS, LHR, NRT and LAX.
- **Around the GW8 deadline.** The window spans the GW8 deadline, 2026-10-23T17:30Z. The 24 scheduled probes within three hours of it were all served.
- **Context, not evidence:**
  - The event-status probes in the window were also 147 of 147.
  - Over the whole record, through 2026-10-26T05:30Z, both targets were 211 of 211 with no failure run.
  - The two live probes, at 2026-10-21T21:12Z, both answered 200 JSON.
  - No record carries an error or a non-JSON head.

## What it does not say

- It says the FPL API served Cloudflare's egress for 72 hours in late October 2026, from the data centres the schedule happened to use. It does not say the API will keep doing so, nor how it answers at a busier moment than these.
- The 128 scheduled records after the window are kept as read and never count. Neither do the live probes.
- No league member's name or score is stored: a JSON answer leaves only its size.

## What follows

Under #979 a served verdict keeps the `cloudflare-workers` environment and its token for #980, and #980 is unblocked. The Worker and its KV namespace are deleted with the delete workflow once this record is committed.
