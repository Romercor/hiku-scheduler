# Worker and client nstat deltas (vs the previous run on that host) for L4 runs at each sat7 rate, summed
# over workers, mean over repetitions: counters that differ most between rates.
import glob, os, re, statistics as st, collections
R = "results/l4"
runs = [d for s in ("sat7", "lim7") for d in glob.glob(f"{R}/{s}_*/*_r*") if os.path.exists(d + "/summary.json")]
runs.sort(key=lambda d: os.path.getmtime(d + "/summary.json"))
def nst(f):
    o = {}
    for l in open(f, errors="replace"):
        p = l.split()
        if len(p) >= 2 and p[1].isdigit(): o[p[0]] = int(p[1])
    return o
prev = {}; agg = collections.defaultdict(lambda: collections.defaultdict(list))
for d in runs:
    tot = collections.Counter()
    for h in ["client"] + ["worker-%d" % i for i in range(1, 6)]:
        f = f"{d}/{h}.nstat"
        if not os.path.exists(f): continue
        v = nst(f); p = prev.get(h, {}); prev[h] = v
        for k in v:
            tot[(h == "client", k)] += v[k] - p.get(k, 0)
    if "/sat7_" in d and "l4-" in d:
        rate = int(re.search(r"sat7_(\d+)", d).group(1))
        for k, x in tot.items(): agg[k][rate].append(x)
rates = [4000, 8000, 12000, 16000, 20000, 24000]
keys = [k for k in agg if max(abs(st.mean(agg[k][r])) for r in rates if agg[k][r]) > 500 and any(s in k[1] for s in ("TW", "PAWS", "Syn", "SYN", "Reset", "Rst", "RST", "Timeout", "Drop", "Overflow", "Retrans", "Challenge", "Ack", "ACK", "Fail"))]
print("%-40s " % "counter (C=client, W=workers)" + " ".join("%9d" % r for r in rates))
for k in sorted(keys, key=lambda k: k[1]):
    print("%-40s " % (("C " if k[0] else "W ") + k[1][:37]) + " ".join("%9.0f" % st.mean(agg[k][r]) if agg[k][r] else "        -" for r in rates))
