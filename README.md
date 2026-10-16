# From L7 to L4: an eBPF pull-based scheduler for serverless (WIP Version)

> **Research fork of [Hiku](https://github.com/saman-akbari/hiku-scheduler)** (Akbari & Hauswirth, *Hiku: Pull-Based Scheduling for Serverless Computing*, IEEE CCGrid 2025 -- [paper](https://arxiv.org/abs/2502.15534)), the original L7 pull-based OpenLambda scheduler.
> This fork keeps Hiku's L7 scheduler as the baseline (`hiku start`) and adds an in-kernel **L4 eBPF** scheduler (`hiku l4`). For the original project's API, usage, and evaluation docs, see the [upstream repository](https://github.com/saman-akbari/hiku-scheduler).

## How it works

Hiku is a reverse proxy: every request passes through it in user space, and it learns that a worker is free when the reply comes back. The L4 scheduler moves the same pull-based decision into the Linux kernel, so no user-space process handles a request.

1. **Availability signal.** Each OpenLambda worker announces how many idle instances it holds per function, in a 15-byte UDP datagram to port 9020. An XDP program on the scheduler stores it in a BPF map (`idle_map`), with no system call on the scheduler.
2. **Pick.** A client, or a gateway in front of the platform, opens one TCP connection per invocation to the function's IPv4 address. The address names the function, because the kernel never sees the HTTP request. At the SYN, a TC ingress program picks a worker that announced a free instance of that function and takes one slot from its count.
3. **Forwarding.** The same program rewrites the connection to the worker (NAT) and the replies back to the function's address, so the client sees an ordinary connection.

```
client --SYN to function address--> scheduler: TC pick + NAT ------> worker (OpenLambda)
                                    scheduler: XDP -> idle_map <---- UDP availability signal
```

If no worker has a free instance, a fallback still picks one (least-loaded by default), since the kernel cannot hold a connection back. A user-space loader only installs the programs and fills their maps.

## Code map

```
src/l4/bpf/scheduler.bpf.c      the scheduler: programs `availability` (XDP) and `nat` (TC)
src/l4/loader.go                reads the config, loads and attaches the programs, prints counters
src/l4/config.json              example config
src/main.go                     `hiku start` (L7, Hiku) / `hiku l4` (L4)
scripts/setup_l4.sh             builds the kernel program and hiku on a scheduler node
open-lambda-mod/src/worker/lambda/signal.go
                                the worker's availability signal; hooks and settings next to it,
                                and the `openlambda` binary in the repo root is built from them
src/balancer/pull_ordered.go    Hiku with the ordered pick, a comparison arm for the evaluation
```

The L7 baseline has three changes so that it is not limited by its own implementation: per-request logging is off unless `HIKU_VERBOSE` is set, only error bodies are kept in memory, and the proxy keeps up to 1024 idle connections per worker.

## Build and run

The scheduler node needs Linux 6.6 or newer (for TCX) and root; `setup_l4.sh` installs clang and Go on Ubuntu. From the repo root:

```bash
bash scripts/setup_l4.sh            # builds the kernel program for the workers in src/l4/config.json, and hiku
sudo /app/hiku l4 -c /app/l4.json
```

Config fields (`src/l4/config.json`):

| field | meaning |
|---|---|
| `iface` | network interface to attach to |
| `host` | the scheduler's own IPv4 address |
| `workers` | `ip:port` per worker; ids follow the list order from 1, at most 15 workers |
| `function_addrs` | `name:IPv4` per function |
| `service_port` | the port clients dial on every function address |
| `strategy` | pick among free workers: `ordered` (default), `p2c`, `jsq`, `weighted-random` |
| `fallback` | pick when none is free: `least-loaded` (default), `random`, `hashed`, `hashed2`, `bounded` |
| `fin_reclaim` | free a connection's state on an orderly close (recommended) |
| `rst_feedback`, `penalty_ms` | skip a worker for a while after it refused a connection |
| `functions`, `synthetic_fns` | port mode (`name:port` on the scheduler's own address), and padding for scale tests |

Clients must route the function addresses to the scheduler (for example `ip route add 10.200.0.0/16 via <scheduler>`), and the network must not drop replies that the scheduler sends from addresses it does not own (UpCloud: `source_ip_filtering = false`).

Workers run OpenLambda with the changes in `open-lambda-mod`. The worker id is derived from its port, so the worker on port 5000+i must be entry i+1 of `workers`. In the worker config, `scheduler_url` and `scheduler_port` (9020), or `scheduler_peers` for several schedulers, name where the signal goes; the evaluation used `signal_refresh_ms` 1000 and `signal_coalesce_ms` 10. A worker answers a full accept queue with a RST, which `rst_feedback` needs, only with `net.ipv4.tcp_abort_on_overflow=1`.

## Limitations

- IPv4 only, without IP options; one TCP connection per invocation, so a gateway in front is assumed.
- The worker count is compiled in (`N_WORKERS`, at most 15), and the worker and function tables are fixed for a run.
- The scheduler is a NAT, so replies pass through it.
- With `max_conn_requests` on, a worker keeps the count of a connection that closed early and passes it to the next connection on the same address and port.

## License

Apache License 2.0 (see [LICENSE](LICENSE)) -- inherited from the original Hiku project.
