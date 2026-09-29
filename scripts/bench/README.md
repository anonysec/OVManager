# bench/ — reproducing the numbers in CHANGELOG.md

Several releases here rest on measurements rather than argument: the fan-out
cost table (1.0.17), the starvation table (1.0.18), and the jobs worker's
memory and isolation figures (1.0.19). Those numbers were originally produced
by throwaway scripts in `/tmp` that were then deleted, which left the
changelog asserting things nobody could re-check. These are the scripts, kept
in the repository so the claims stay checkable.

```bash
make bench                    # both, about 3 minutes
.venv/bin/python scripts/bench/node_fanout.py
.venv/bin/python scripts/bench/node_fanout.py --full          # adds the 30s column, ~7min
.venv/bin/python scripts/bench/node_fanout.py --only-starvation --nodes 20,40,80
.venv/bin/python scripts/bench/jobs_worker.py
.venv/bin/python scripts/bench/request_fanout.py          # ~4 minutes, dead and healthy
.venv/bin/python scripts/bench/request_fanout.py --dead-only
```

## What each one backs

| script | claim | published |
| --- | --- | --- |
| `node_fanout.py` | a fan-out cycle costs `ceil(nodes / workers) × timeout` | 1.0.17 |
| `node_fanout.py` | an unbounded fan-out takes anyio's shared limiter and starves everything else | 1.0.18 |
| `jobs_worker.py` | the second interpreter costs resident memory | 69.5 MB, 1.0.19 |
| `jobs_worker.py` | a wedged job no longer stops the panel answering | 31.8s job, 9 ms worst `/health`, 1.0.19 |
| `request_fanout.py` | a request is bounded in time, and a healthy fleet is not slowed | 30.1s → 10.0s at 1 dead node, 1.0.33 |

The scripts print the published figure next to what they measured, so a drift
is visible rather than buried.

## Read this before trusting a number from these scripts

Every measurement here was wrong at least once while it was being written, and
the failure mode is always the same: **the harness did not do the thing it
claimed to measure, and produced a confident number anyway.** The scripts
therefore check their premises and abort rather than report.

The three traps, all of which bit during development:

1. **A bare `BaseHTTPRequestHandler` is not a blackhole.** With no `do_GET` it
   replies `501` immediately, so a probe against it never waits and a fan-out
   of them costs nothing. `check_premise()` sends a real probe and refuses to
   continue unless it blocked for the full timeout.

2. **A raw TCP connect does not block either.** It completes the moment the
   server accepts. Probing with `socket.create_connection` measures a
   handshake, not a timeout — the first draft of `node_fanout.py` did exactly
   this, and its premise check caught it on the first run.

3. **`DATA_DIR` is read at import time.** Set it only in the environment handed
   to a seeding *subprocess* and the measuring process reads a different
   database. `request_fanout.py` did exactly this and reported a flat 18.1s for
   every node count while probing 118 leftover rows from `OVManager/data`
   instead of the node it had just seeded. It now asserts it is pointed at the
   database it created, and asserts per iteration that the nodes it probes are
   the ones it seeded.

4. **Measuring after the fact measures nothing.** The first version of the
   starvation measurement drained the fan-out before timing the unrelated
   operation, and put the fan-out on a private executor, so the two could never
   contend. It reported 0.01s where 1.0.18 published 2.95s. The fan-out must
   still be in flight, on the same pool, when the unrelated work runs.

And one that is easy to miss because it is not about the harness at all:

5. **Calling the job wrong measures a crash.** `check_user_used_traffic()`
   takes no arguments and opens its own session. Passing it one made it raise
   on the first line, and the measurement timed the crash. The script asserts
   the job ran long enough to have wedged before it reports isolation.

## These are not tests

Nothing here runs in CI. The numbers depend on the machine's core count — the
whole `ceil(nodes / workers)` shape is a function of it — so a fixed assertion
would be a test of the runner, not of the code. What *is* in CI are the tests
that pin the properties these numbers were measured to justify:
`tests/test_node_fanout_budget.py` and `tests/test_worker_process.py`.
