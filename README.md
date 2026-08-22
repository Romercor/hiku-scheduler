# From L7 to L4: an eBPF pull-based scheduler for serverless

> **Research fork of [Hiku](https://github.com/saman-akbari/hiku-scheduler)** (Akbari & Hauswirth, *Hiku: Pull-Based Scheduling for Serverless Computing*, IEEE CCGrid 2025 -- [paper](https://arxiv.org/abs/2502.15534)), the original L7 pull-based OpenLambda scheduler.
> This fork keeps Hiku's L7 scheduler intact as the baseline (`hiku start`) and adds an in-kernel **L4 eBPF** steering mode (`hiku steer`). For the original project's API, usage, and evaluation docs, see the [upstream repository](https://github.com/saman-akbari/hiku-scheduler).

## 1. The problem

**New terms**
- **Serverless / FaaS** (Function-as-a-Service) -- you upload single *functions*; the platform runs them on demand and manages the machines for you.
- **Worker** -- a machine in the pool that actually runs function code.
- **Scheduler** -- the component that decides *which* worker handles each incoming request.
- **Sandbox / instance** -- an isolated lightweight container holding one running copy of a function.
- **Cold start vs warm** -- cold = the sandbox must be created first (slow, ~100x); warm = one already exists (fast).

In serverless, each user request runs a small function inside a short-lived sandbox on one of many workers. A scheduler must decide, for every invocation, which worker runs it. A good decision means low latency, even load, and re-using a **warm** instance instead of paying a **cold start**. Naive routing (random / round-robin) ignores who is busy and who is already warm, so it wastes both.

## 2. The original system: Hiku, at L7

**New terms**
- **L7 (Layer 7, "application layer")** -- the top of the network stack, where whole HTTP requests live: code here sees URLs, headers, bodies.
- **Reverse proxy** -- a server that receives a client request, forwards it to a backend, then relays the reply back.
- **Balancer** -- the swappable piece that chooses which worker gets the request.
- **Pull-based / Join-Idle-Queue (JIQ)** -- idle workers announce themselves into a queue; the scheduler gives the next job to one that is waiting. Work is "pulled" by the free.
- **CH-BL** -- consistent-hashing with bounded loads: a locality-aware policy that keeps sending the same function to the same worker unless it is overloaded.

**Hiku** (the reference system, built by our supervisor's own research group) is a scheduler **for** OpenLambda: it solves this general FaaS problem on that platform. It is an **L7** scheduler -- a Go **reverse proxy**. For every request it (1) **picks** a worker with a pluggable **balancer**, (2) **proxies** the HTTP request to that worker, (3) **releases** the worker when the reply comes back. Its headline balancer is **pull-based**; it also ships least-connections, random, and **CH-BL** (a state-of-the-art locality baseline).

## 3. Why move to L4 -- the limitation

**New terms**
- **L4 (Layer 4, "transport layer")** -- the lower TCP/packet level; code here sees connections and packets, not URLs.
- **eBPF** -- a way to load small, safety-checked programs into the Linux kernel that run at chosen hook points, without modifying the kernel itself.
- **Data path** -- the route every request physically travels; being "in the data path" means you touch *every* request.
- **Syscall** -- a call from a program into the kernel (e.g. read/write a socket); each one costs time.
- **Latency tail** -- the slowest few percent of requests; what users feel as "sometimes it is really slow."

**The scheduler sits inside the data path.** Because it proxies every request in userspace, each invocation pays a full user-space hop: accept the TCP connection, parse HTTP, open a second connection to the worker, copy bytes back -- many **syscalls** per request. At high rates the scheduler becomes the **CPU bottleneck** and inflates the **latency tail**.

**Goal:** migrate the same pull-based logic from L7 (userspace) down to **L4**, running **in the kernel** via **eBPF**. Then the kernel steers packets straight to workers and the scheduler **leaves the per-request data path** -- it becomes a thin control plane instead of a proxy.

| L7 (Hiku, baseline) | L4 (ours, eBPF) |
|---|---|
| client -> **scheduler proxies in userspace** (pick + copy every request) -> worker. Release is **implicit**: the scheduler sees the reply return, so it knows the worker is free for free. | client -> **kernel rewrites the packet** (pick + NAT, no userspace) -> worker. Scheduler is off the path, so "I'm free" must be sent **explicitly** as a packet. |

## 4. The first consequence, and the first prototype

**New terms**
- **NIC (Network Interface Card)** -- the hardware port where packets enter and leave a machine.
- **XDP (eXpress Data Path)** -- an eBPF hook that runs on packets the instant they hit the NIC, before the normal networking stack. Extremely cheap.
- **BPF map** -- a table shared between the in-kernel program and userspace; the kernel's key-value store for state.
- **UDP** -- a fire-and-forget packet type (no connection setup); ideal for tiny one-off signals.

Mapping Hiku revealed the catch: today the scheduler learns idleness **implicitly** (it is on the path). Once forwarding moves in-kernel, it no longer sees the traffic, so **availability must become an explicit signal**. First prototype (Bar 1): each worker emits a tiny **UDP** `FREE/BUSY` packet; an **XDP** program on the scheduler's **NIC** parses it and updates a **BPF map** -- with **zero userspace in the hot path**. Validated cross-node on two *separate-kernel* cloud VMs. This is the **zero-syscall availability sync**.

## 5. The two hard problems to route a real request at L4

**New terms**
- **NAT (Network Address Translation)** -- rewriting a packet's destination (or source) address so it goes to a different machine than originally addressed. Here: redirecting a request aimed at the scheduler so it lands on the chosen worker.
- **TC / TCX (Traffic Control)** -- an eBPF hook just after XDP where you can modify and redirect packets; where we perform the NAT.
- **sockmap / sk_msg** -- an eBPF mechanism that splices two TCP sockets together at the socket layer (the alternative forwarding method we tested).
- **Function-in-port** -- encoding "which function" into the destination port number, so the kernel can tell functions apart without reading the URL.

**R1 -- function identity.** At L7 the function is in the URL (`/run/<fn>`); at L4 the kernel only sees packets. Solution: **function-in-port** -- each function is a distinct destination port, and a BPF map (`fnports`) maps port -> function-hash.

**R2 -- forwarding.** How to actually move the connection in-kernel. Two options were built and compared:

- **A -- sockmap/sk_msg splice** (socket layer): proven to work, but needs the scheduler to first accept the connection (a bootstrap race).
- **B -- XDP/TC packet steering** (chosen): an in-kernel **stateful NAT** rewrites the destination to the picked worker and the kernel forwards it. Proven in stages: **B.1** route to a fixed worker, then **B.2** the NAT **picks a FREE worker from the idle map at connect time** -- pull-based scheduling, end-to-end, entirely in the kernel.

## 6. The methodologies, and why each one helps

**New terms**
- **Verifier** -- the kernel's safety checker that rejects any eBPF program that could crash or loop forever (this is what makes in-kernel code safe).
- **P2C (power-of-two-choices)** -- pick two workers at random, use the less loaded one; cheap yet near-optimal balance.
- **JSQ (join-shortest-queue)** -- always pick the least-loaded worker.
- **Optimistic decrement** -- the moment you assign a worker, immediately mark one of its free slots as used, before the worker confirms.

| Technique | What it is | Why it helps here |
|---|---|---|
| **eBPF** | Sandboxed, verifier-checked programs the kernel runs at hook points; no kernel patch. | Lets scheduling logic live safely in the kernel -- the whole premise. |
| **XDP** | Earliest ingress hook, per-packet, before the socket layer. | Ingests availability signals for near-zero cost; never wakes userspace. |
| **TC / TCX** | Traffic-control hook where we rewrite and redirect packets. | Where the NAT steering happens -- the in-kernel "forward to worker". |
| **BPF maps** | Kernel/user shared tables: idle map (HASH), flow table (LRU), config/ports (ARRAY/HASH). | Replace the Go scheduler's in-memory state; shared between fast path and control plane. |
| **Pull-based / JIQ** | Route to an idle worker from an idle set. | Balances load and reuses warm instances -- the policy we are migrating. |
| **Optimistic decrement** | On assigning a worker, immediately drop its free-slot count in the map. | Stops many near-simultaneous picks from all piling onto one "free" worker before it reports back -- makes a single scheduler robust to **stale** data. |
| **Slot-based concurrency** | Generalize binary FREE/BUSY to a per-function count of C concurrent executions. | Models real instance concurrency; availability = free slots, removing head-of-line blocking. |
| **Fallback picks** | P2C, JSQ, weighted-random -- runtime-selectable via config. | Pure "pick the most free" (JSQ) **herds** under stale data; P2C / weighted-random spread load. Weighted-random fixed a real imbalance we saw. |
| **Per-kernel maps + broadcast** | Each scheduler has its own maps (no shared map); workers broadcast slot counts to all schedulers. | Decentralized coherence for **multiple** schedulers with no shared state or lock. |
| **Flow LRU + liveness aging** | Evict flows on RST/timeout; expire stale idle entries. | Keeps NAT state bounded and avoids black-holing requests to a dead worker. |

## 7. How we actually got here (the chain of thought)

**New terms**
- **FunctionBench** -- a standard suite of serverless benchmark functions used to generate realistic load.
- **autocrlf** -- a Windows Git setting that rewrites line endings; it silently corrupted a prebuilt binary for us.

1. Read the topic and the Hiku fork; **mapped its L7 architecture** and found the only existing cross-node worker->scheduler signal -- confirming availability must go explicit at L4.
2. Paper research on L7->L4 options (sockmap vs XDP, Katran, JIQ); an examiner-style review flagged the real risk (routing a real request is the hard 90%).
3. Built the **XDP availability prototype** and validated it on two separate-kernel VMs (Bar 1).
4. Stood up cloud infra (GCP) to reproduce Hiku's own evaluation -- survived many yaks: WSL RAM exhaustion, GCP auth/quota walls, and an **OpenLambda segfault root-caused to Windows `autocrlf` silently truncating the prebuilt binary**. Fell back to a known-good 1 scheduler + 3 worker cluster.
5. Got the **full L7 Hiku pipeline** running real FunctionBench load on GCP -- the baseline.
6. Proved a real request could be routed **at L4**: first sockmap splice, then committed to **Option B (TC NAT)**; B.1 fixed-worker, then **B.2 pull-based** -- the NAT picks a free worker from the in-kernel map.
7. Hardened it: worker liveness aging + LRU/RST flow eviction; added **mark-busy-on-assignment** (optimistic decrement).
8. Added **multi-function** routing (function-in-port), **instance concurrency** (slots), **fallback strategies** (P2C/JSQ/weighted-random), and **multiple schedulers** (broadcast coherence).
9. Evaluated: isolated L4-vs-L7, staleness sensitivity, and drove the **real Azure Functions 2021 trace** against every Hiku balancer.
10. Finally **integrated L4 into the fork** as a second mode next to L7.

## 8. Does it work? (evaluation)

**New terms**
- **Throughput** -- requests handled per second (higher is better).
- **p99 (99th-percentile latency)** -- 99% of requests finish faster than this number; a measure of the slow tail (lower is better).
- **Scheduler CPU %** -- how much of a CPU core the scheduler itself burns to do its job (lower is better).

| Question | Result |
|---|---|
| **RQ2 -- L4 vs L7 Hiku** | ~**100x less scheduler CPU** (0.6% vs 64% at equal load; 0.9% vs 82% at max), ~**2x throughput**, far better tail (**p99 17.8ms vs 212ms**; max 0.24s vs 13.2s) -- because the scheduler left the data path. |
| **RQ3 -- staleness** | Single-scheduler design is **staleness-insensitive** (optimistic decrement pre-compensates); staleness only bites with multiple schedulers. |
| **Instance concurrency** | Slot model removes head-of-line blocking: p99 **6.82s -> 47ms** going from C=1 to C=4. |
| **RQ4 -- distributed** | Two decentralized schedulers stay coherent over one worker pool with **no shared map**. |
| **Real trace (Azure 2021)** | L4-pull has the **lowest cold-start rate (1.92%)** and best load balance (51/49) vs Hiku's random / least-conn / CH-BL / pull. |

**Remaining to fully validate:** IBM + Huawei traces, paper-scale 1+5, CH-RLU, realistic OpenLambda arm.

## 9. Where it lives now

The L4 subsystem is integrated **directly into the Hiku fork** as a second mode -- one config-driven binary:

```
hiku start   -> L7 reverse proxy   (the original Hiku baseline, kept for comparison)
hiku steer   -> L4 eBPF steering   (our contribution)

main.go        program entry - picks the mode
  |__ steer.go       control plane: loads + attaches the program, fills the maps
       |__ steer.bpf.c   THE algorithm - runs in the kernel, per packet
```

So the scheduling brain that used to be Go running in userspace is now a verified eBPF program in the kernel; the Go code shrinks to a loader that configures it. Same policy (pull-based), a fraction of the cost.

## 10. Code map: where everything lives

```
hiku-scheduler/                the fork: L7 baseline + L4 mode in one repo
|
|__ src/
|   |__ main.go                CLI entry: `hiku start` (L7)  /  `hiku steer` (L4)
|   |
|   |__ steer/                 >>> our L4 subsystem <<<
|   |   |__ steer.go           control plane: parse steer.json, load+attach, fill maps, stats
|   |   |__ bpf/steer.bpf.c    THE algorithm, in-kernel: programs `availability` (XDP) + `nat` (TC)
|   |
|   |__ scheduler/ balancer/   the L7 baseline (Hiku, untouched): pull-based / CH-BL / ...
|   |__ proxy/ server/ config/  reverse proxy, HTTP server, config
|   |__ go.mod  deps.sh         deps (adds github.com/cilium/ebpf)
|
|__ steer.json                 L4 config: iface, host, strategy, workers[], functions[]
|__ scripts/
|   |__ setup_l4.sh            build the bpf object + hiku binary, ship them, enable ip_forward
|   |__ 1_deploy.sh 2_setup.sh  existing L7 deploy / setup
|__ evaluation/l4/             eval harness: cold_backend.py, trace.js, azure_adapter.py, ...
```

Inside `steer.bpf.c` (the algorithm) the state is a handful of BPF maps -- `workers`, `idle_map`, `flow` (LRU), `fnports`, `cfg`, `nat_stats` -- plus two attached programs (`availability` on XDP, `nat` on TC) and the `pick_worker()` helper they share.

| To change / find... | Look at |
|---|---|
| Which worker a request goes to (the scheduling decision) | `pick_worker()` in `steer.bpf.c` (+ `strategyFromConfig()` in `steer.go`) |
| How "I'm free" signals are ingested | the `availability` program (XDP) in `steer.bpf.c` |
| How a request is rewritten and forwarded (and the reply back) | the `nat` program (TC) in `steer.bpf.c` |
| Workers, functions, strategy, interface, scheduler IP | `steer.json` (parsed by `ToConfig()` in `steer.go`) |
| Which mode runs (L7 vs L4) | `main.go` (`start` vs `steer` command) |
| Build / deploy the L4 mode on a node | `scripts/setup_l4.sh` |
| Measure it (load, traces, cold/warm backend) | `evaluation/l4/` |

## 11. Further steps (code-level extension points)

The code is deliberately structured so each item below is a **small, localized change -- an extension point, not a rewrite**. Listed here purely in terms of the code:

- **New pick strategy** -- add one `case` to `strategyFromConfig()` (steer.go) and one branch to `pick_worker()` keyed on `cfg[1]` (steer.bpf.c). Nothing else changes; the existing weighted-random / P2C / JSQ are already just cases here.
- **More functions / workers** -- extend the `functions` and `workers` lists in `steer.json`. `N_WORKERS` is currently a build-time `#define` that can be lifted to a runtime map size.
- **Flow lifecycle** -- handle TCP `FIN` as well as the current `RST`/timeout for faster flow-table eviction; the LRU size and idle timeout are single constants to tune.
- **Unique NAT source-port allocation** -- deferred; add a per-connection source-port pool so one client can open very many concurrent connections without source-port collisions.
- **Richer metrics** -- extend the `nat_stats` counters and `printStats()` (e.g. per-worker dispatch counts, cold/warm split) for deeper observability.
- **IPv6** -- the packet parser and `endpoint` encoding are IPv4-only; add a parallel IPv6 path.
- **Config split** -- optionally split `steer.go` into `steer.go` + `config.go` to mirror Hiku's `config` package layout.
- **go.sum** -- run `go mod tidy` once to finalize the committed dependency checksums.

Each of these plugs into an existing seam (a config field, a map, a `switch` case, a single hook), so the codebase can be extended without touching the core steering path.

## License

Apache License 2.0 (see [LICENSE](LICENSE)) -- inherited from the original Hiku project.
