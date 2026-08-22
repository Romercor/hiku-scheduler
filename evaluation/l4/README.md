# eval - P7.1 / RQ2: L4 steering vs L7 Hiku proxy

Does the in-kernel L4 path reduce overhead vs the L7 userspace proxy? Same backends under
both arms, only the forwarding layer differs (isolating arm; realistic OpenLambda arm pending).

## Setup

4x e2-standard-2 (europe-west3). scheduler (10.156.0.22) runs one arm at a time:
- L7: `hiku start` pull-based on :9020 (workers w1:5000, w2:5001)
- L4: `hiku steer -c steer.json` on ens4 (bpf built with `-DN_WORKERS=2`); k6 hits :5100

Backends w1/w2 run `responder.py` (echo, HTTP/1.1 keep-alive, TCP_NODELAY, emits a FREE
signal on completion to model a worker announcing itself idle). worker-3 is the k6 client.

## Run

```
# per backend (w1 id1:5000, w2 id2:5001):
python3 responder.py <port> worker-<id> 10.156.0.22 <id>
# scheduler: mpstat 1 32 > cpu.out   (during each k6 run)
# client:
TARGET=http://10.156.0.22:5100/run/echo VUS=50 DUR=30s k6 run load.js   # L4, closed-loop
TARGET=http://10.156.0.22:9020/run/echo RATE=3000  k6 run load.js       # L7, fixed-rate
```

## Results (2026-08-22)

Closed-loop (50 VUs, max throughput):

| metric        | L7 Hiku | L4 steer |
|---------------|---------|----------|
| throughput    | 3883/s  | 8007/s   |
| p50           | 4.15ms  | 5.39ms   |
| p95           | 37.6ms  | 12.8ms   |
| p99           | 212ms   | 17.8ms   |
| max           | 13.2s   | 0.24s    |
| scheduler CPU | ~82%    | ~0.9%    |

Equal load (3000 rps, below both ceilings):

| metric        | L7 Hiku | L4 steer |
|---------------|---------|----------|
| p50           | 1.54ms  | 0.69ms   |
| p95           | 4.12ms  | 1.16ms   |
| p99           | 8.77ms  | 5.77ms   |
| scheduler CPU | ~64%    | ~0.6%    |

L4 removes the scheduler from the data path: ~100x less scheduler CPU, ~2x median latency
and ~2x throughput ceiling, and far tighter tail. Both arms 0% errors.

Caveats: Python echo backends cap throughput (~8k rps) - the real forwarding delta is likely
larger with faster backends. The one-time `no-free` burst at start is mark-busy hitting a cold
idle_map. Worker choice on L4 was mostly the random fallback under this synthetic heartbeat
(the pull-vs-fallback dynamics are RQ3 / P7.2). CPU is scheduler-wide (mpstat all), since L4's
work is in kernel softirq, not the loader process.

## Trace-driven eval (P7.3) + SOTA comparison (P7.4) - harness

- `cold_backend.py` - backend that models execution + cold starts: `/run/<fn>` is warm if
  used within `keep_s`, else pays `cold_ms`; emits a per-function FREE on completion (drives
  the L4 pull map, so no separate heartbeat is needed). args: `port name sched wid [warm_ms cold_ms keep_s]`
- `trace_gen.py` - synthetic Zipf function table; a real Azure/IBM/Huawei adapter emits the
  same two files. args: `n_funcs [zipf_s base_port out_prefix]` -> `<pref>.funcs` (name:port
  per line, for the loader's `functions` config list) + `<pref>.json` (name,port,weight, for the driver).
- `trace.js` - k6 driver: weighted function pick, L4 (`:<port>/run/<fn>`) or L7
  (`:9020/run/<fn>`), cold/warm counters. env: `FUNCS MODE(l4|l7) SCHED RATE DUR`.

Run: `trace_gen.py N` -> loader `functions` list from `trace.funcs` (L4) or Hiku config (L7) ->
`cold_backend.py` on each worker -> `k6 trace.js MODE=l4` vs `MODE=l7` with each Hiku balancer.
Compare latency, throughput, and cold-start rate across schedulers. CH-RLU's advantage is
locality -> warm hits, so cold-start modeling (this backend) is what makes that comparison meaningful.

## Scheduler comparison results (2026-08-22)

40 functions (Zipf s=1.1), 80 rps, 25s; backends warm=5ms cold=150ms keep=4s; 2 workers + 1 client.
Backends restarted (fully cold) before each arm. CH-RLU positioned in related work; CH-BL
(`hashing-bounded`) is its base and the locality baseline.

| scheduler                   | cold rate | p50    | p95    | p99   | throughput | sched CPU |
|-----------------------------|-----------|--------|--------|-------|------------|-----------|
| L4-pull (ours)              | 6.0%      | 6.96ms | 152ms  | 161ms | 69/s       | ~0.7%     |
| L7 pull-based (Hiku)        | 5.3%      | 7.85ms | 152ms  | 154ms | 80/s       | ~5.4%     |
| L7 least-connections        | 8.7%      | 7.84ms | 152ms  | 154ms | 80/s       | ~5.6%     |
| L7 CH-BL (hashing-bounded)  | 4.75%     | 7.91ms | 9.2ms  | 153ms | 80/s       | ~6.0%     |
| L7 random                   | 8.95%     | 8.02ms | 153ms  | 154ms | 80/s       | ~6.6%     |

Reading: (1) locality ranking CH-BL < pull < least-conn < random on cold rate - consistent
hashing keeps a function on one worker (p95 9.2ms, mostly warm), validating why CH-RLU builds
on CH-BL. (2) L4-pull uses ~8-10x less scheduler CPU than every L7 balancer (the data-path
offload holds on a real multi-function trace). (3) L4-pull's slightly higher cold rate + lower
throughput come from mark-busy modelling concurrency=1 per {function,worker}: a popular warm
function cannot absorb concurrent load on one worker, forcing spread -> the instance-concurrency
gap (P5). Caveats: 2 workers / single run / no warmup-discard - directional, not paper-grade;
CPU gap widens at higher rps (see P7.1 saturation).

## Instance concurrency (P5)

The availability signal now carries a per-function slot count (available concurrency) instead
of binary free/busy; `pick_worker` picks the worker with the most free slots and consumes one on
dispatch; `cold_backend.py` takes a `conc` arg and enforces C concurrent execs per function
(excess queues) while advertising `slots = C - active`. Isolation run (4 hot functions Zipf,
warm=30ms cold=150ms, 200 rps, 20s, 2 workers):

| L4 hot-4fn, 200 rps | CONC=1 | CONC=4 |
|---------------------|--------|--------|
| p50                 | 85ms   | 32ms   |
| p95                 | 6.02s  | 33ms   |
| p99                 | 6.82s  | 47ms   |
| completed           | 3224 (413 dropped) | 3980 (0 dropped) |
| failed              | 1.36%  | 0.02%  |

At concurrency=1 a popular warm function saturates its single slot per worker and requests queue
to multi-second latency; concurrency=4 serves the same load at p99 47ms with full throughput.
Note the effect only appears once the backend ENFORCES the limit (a per-function semaphore) - a
threaded server that runs everything concurrently hides it. At low/unsaturated rates concurrency
is a no-op (the per-function demand is below the 1-slot capacity).

## Distributed / multiple load balancers (P6 / RQ4)

BPF maps are per-kernel - no shared map across schedulers. Coherence instead comes from each
worker BROADCASTING its per-function slot count to ALL schedulers (`cold_backend` sched arg is a
comma-separated list); each scheduler keeps its own idle_map, optimistically decrements on
dispatch, and the worker (which enforces concurrency C) re-syncs everyone on its next report.
`SCHED_IP` is now configurable (loader `host` config field, stored in the `cfg` map) so N schedulers each own
their IP. Two schedulers (S1=.22, S2=worker-3 .21), shared backends w1/w2, 40-fn trace, warm=10ms
cold=100ms C=4; 1 scheduler @100 rps vs 2 schedulers @50+50:

| metric              | 1 scheduler @100 | 2 schedulers @50+50 (S1 / S2) |
|---------------------|------------------|-------------------------------|
| p99 latency         | 103ms            | 103ms / 103ms                 |
| throughput          | ~1960            | ~998 + ~979 (~1977 total)     |
| cold rate           | ~3.6%            | ~3.8%                         |
| backend split (S1)  | 40/60            | 685/286                       |
| backend split (S2)  | -                | 691/285                       |

Findings: (1) COHERENCE holds - the two schedulers make near-identical routing decisions
(685/286 vs 691/285) from the shared broadcast, with NO shared map; adding a 2nd scheduler keeps
p99/throughput/cold-rate flat (no over-dispatch collapse) and scales request ingestion. (2) Load
imbalance across backends persisted with JSQ (pick max-slots) - the classic
load-balancing-with-stale-information herding. Caveats: k6 client co-located on a backend (4-VM
limit); single run; functional demo, not paper-scale.

### Fixing the imbalance: weighted-random (roulette) selection

JSQ (pick the max-slots worker) makes independent schedulers deterministically choose the same
target from stale state -> herd. P2C does not help at N=2 (2-of-2 = JSQ). Fix: `pick_worker`
selects a worker with probability proportional to its free slots (roulette over `wslots`), so it
stays load-aware but decorrelates schedulers. Result (same setup):

| case                          | JSQ (max-slots) | weighted-random |
|-------------------------------|-----------------|-----------------|
| 1 scheduler @100, w1/w2 split | 23/77 -> 40/60  | 46/54           |
| 2 schedulers, client on w1    | 71/29           | 69/31           |
| 2 schedulers, client on w2    | -               | 54/46           |

Weighted-random fixes the single-scheduler imbalance (46/54, near even). The residual 2-scheduler
skew tracked the CLIENT's host (69/31 with client on w1 vs 54/46 with client on w2) = a
co-location measurement artifact of the 4-VM testbed (client shares a backend), not an algorithm
flaw; both schedulers stayed coherent throughout. A clean read needs a 5th (dedicated client) VM.
P2C remains the general-N answer for larger clusters (RQ3/P7.2).

## Intermittent request failures - diagnosed as a load-generator artifact (not an L4 bug)

Multi-function L4 runs showed 0.2-4.5% `dial: i/o timeout` / `request timeout` failures near
saturation. Isolation (250 rps): L4 single-function = 0.00%; L7 single-port = 0.00%; L4
40-function = fails -> failures scale with the number of function PORTS, not the kernel path.
Cause: function-in-port makes one k6 client open ~40x more concurrent sockets (a connection pool
per host:port); at high VU counts the CLIENT exhausts local connection resources. Ruled out:
source-port collision (no-keepalive was clean), backend backlog (raised 5->512, didn't fix),
cold-start warmup, flow-map accumulation. So the L4 steering path is clean at load; the failures
are an artifact of one client fanning out to 40 ports (unrealistic) and are ~0.1-0.6% at the
<=100 rps used for scheduler comparisons. Harness now sets backend `request_queue_size=512`;
`trace.js` has `DEBUG` (log failures) and `NOKA` (no keep-alive) knobs.

## Staleness sensitivity (P7.2 / RQ3)

Knobs: `cold_backend` `report_ms` (report slots every T ms instead of on each event -> scheduler
view lags by up to T = controllable staleness); loader `strategy` config field (weighted-random, p2c,
jsq, runtime via `cfg[1]`). 1 scheduler, 3 backends (w1=client, co-located), 4 hot fns (Zipf),
warm=40ms, near capacity (270 rps):

| strategy | staleness | p99    | throughput |
|----------|-----------|--------|------------|
| JSQ      | 20ms      | 55.8ms | 234/s      |
| JSQ      | 200ms     | 58.6ms | 234/s      |
| JSQ      | 1000ms    | 59.7ms | 234/s      |
| P2C      | 20ms      | 59.4ms | 234/s      |
| P2C      | 200ms     | 59.7ms | 234/s      |

FINDING (nuances the JSQ-herds-under-staleness expectation): the single-scheduler design is
essentially INSENSITIVE to staleness - p99 moves 56->60ms across a 50x staleness range
(20ms->1000ms) and throughput is flat, with JSQ ~= P2C. Reason: the OPTIMISTIC slot-decrement -
the scheduler decrements its own dispatches locally - already prevents over-dispatch, so a stale
"worker is free" just makes it spread to other workers rather than herd. The textbook
staleness-herding assumes the scheduler relies SOLELY on periodic reports; our self-tracking
breaks that assumption. So P2C is NOT needed to "recover staleness" here. Where staleness DOES
bite is MULTIPLE schedulers (each can't see the others' dispatches -> cross-scheduler
over-dispatch -> herding, see the distributed section), and there the decorrelating strategies
(weighted-random; P2C for N>=3) help. Secondary observation: at lower load (180 rps, headroom)
P2C gave the most balanced backend split (w1 least inflated by co-location). Caveats: co-located
client, single runs, N=3.

## Real workload trace: Azure Functions 2021 (P7.3)

`azure_adapter.py` turns the Azure 2021 invocation trace into the harness format. Obtain the trace
(one-time): download `AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar` from Azure/AzurePublicDataset,
extract with RARLAB `unrar` (bsdtar/p7zip choke on its RAR5 dictionary), then
`python azure_adapter.py <trace.txt> 30 5100 300 azure` -> `azure.funcs`/`.json`/`.dur`. It counts
per-function invocations (real popularity) and median execution duration, takes the top N (top 30 =
88.8% of ~1.98M invocations across 424 functions, heavy-tailed: w[0]=0.30), and emits per-function
warm durations (real, capped at 300ms; the most popular function is the shortest at 1ms).
`cold_backend` reads the `.dur` file (arg 10) for per-function warm times; cold = warm + cold penalty.

Scheduler comparison on the Azure workload (1 scheduler, 2 backends w1/w2, w3 = dedicated client,
150 rps, C=4):

| scheduler          | cold rate | med    | p99   | balance w1/w2 |
|--------------------|-----------|--------|-------|---------------|
| L4-pull (ours)     | 1.92%     | 12.5ms | 304ms | 51/49         |
| L7 pull-based      | 2.07%     | 14.0ms | 305ms | 76/24         |
| L7 CH-BL           | 2.27%     | 13.7ms | 305ms | 72/28         |
| L7 least-conn      | 3.27%     | 13.8ms | 306ms | 84/16         |
| L7 random          | 3.50%     | 14.2ms | 393ms | 50/50         |

On the real trace L4-pull has the lowest cold-start rate and the best load balance among the
load-aware schedulers (weighted-random; dedicated client here so no co-location bias), at the ~10x
lower scheduler CPU shown in P7.1. Note L4-pull's p95 catches the 300ms-capped function more (higher
than the L7 arms) and it under-delivered slightly (2915 vs 3000 reqs, 0.48% fail = the function-in-port
client-socket effect, log 56). IBM/Huawei traces plug into the same adapter pattern (future work).
The 305MB trace and .rar are not committed (regenerable via the adapter).
