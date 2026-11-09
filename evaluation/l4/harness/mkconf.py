# Writes one L4 scheduler config per (strategy, fallback) pair, l4_<strategy>+<fallback>.json, and for
# two pairs the variants +nofb (no refusal feedback) and +pad<n> (address table padded with n entries).
# Why: an arm picks its policy by config name. Each function is named by port and by address at
# once, so the client alone picks the mode.
# args: outdir sched_internal_ip n_copies worker_ip...
import json, os, sys

BENCH = ["chameleon", "dd", "float_operation", "gzip_compression",
         "json_dumps_loads", "linpack", "matmul", "pyaes"]
BASE, SERVICE_PORT = 5100, 8080
STRATEGIES = ("weighted-random", "p2c", "jsq", "ordered")
FALLBACKS = ("random", "hashed", "hashed2", "least-loaded", "bounded")

outdir, sched, ncopies, wi = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
os.makedirs(outdir, exist_ok=True)

names = ["%s-%d" % (b, c) for c in range(ncopies) for b in BENCH]
base = {"iface": "eth1", "host": sched, "rst_feedback": True, "penalty_ms": 0, "fin_reclaim": True,
        "workers": ["%s:%d" % (ip, 5000 + i) for i, ip in enumerate(wi)],
        "functions": ["%s:%d" % (n, BASE + i) for i, n in enumerate(names)],
        "function_addrs": ["%s:10.200.%d.%d" % (n, (i + 1) >> 8, (i + 1) & 255) for i, n in enumerate(names)],
        "service_port": SERVICE_PORT}
for s in STRATEGIES:
    for f in FALLBACKS:
        json.dump(dict(base, strategy=s, fallback=f),
                  open(os.path.join(outdir, "l4_%s+%s.json" % (s, f)), "w"), indent=2)
VARIANTS = {"nofb": {"rst_feedback": False}, "pad100000": {"synthetic_fns": 100000},
            "pad1000000": {"synthetic_fns": 1000000}}
for s, f in (("ordered", "least-loaded"), ("weighted-random", "random")):
    for v, extra in VARIANTS.items():
        json.dump(dict(base, strategy=s, fallback=f, **extra),
                  open(os.path.join(outdir, "l4_%s+%s+%s.json" % (s, f, v)), "w"), indent=2)
print("%s: %d functions, %d workers, %d configs" % (outdir, len(names), len(wi),
      len(STRATEGIES) * len(FALLBACKS) + 2 * len(VARIANTS)))
