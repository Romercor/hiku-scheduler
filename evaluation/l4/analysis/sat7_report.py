# Saturation report: per rate and arm, mean (range) over repetitions of throughput, failed and dropped calls,
# latency incl. connection setup, CPU of scheduler/client/workers, and TCP counters as per-run deltas
# (nstat -az prints absolute counters, so a run's delta is its value minus the previous run on that host).
import csv, glob, json, os, re, statistics as st, sys

R = sys.argv[1] if len(sys.argv) > 1 else "results/l4"
PFX = sys.argv[2] if len(sys.argv) > 2 else "sat5"
N7 = ["sat7", "lim7", "cal7", "gw7"]
SESSION = {"sat5": ["sat5"], "sat6": ["sat6", "gw"], "gw": ["sat6", "gw"], "sat7": N7, "lim7": N7}[PFX]
runs = []
for d in [x for s in SESSION for x in glob.glob(os.path.join(R, s + "_*", "*_r*"))]:
    if not os.path.exists(os.path.join(d, "summary.json")):
        continue
    runs.append(d)


def nstat(f):
    out = {}
    for l in open(f, errors="replace"):
        p = l.split()
        if len(p) >= 2 and p[1].isdigit():
            out[p[0]] = int(p[1])
        if l.startswith("TIMEWAIT"):
            out["TIMEWAIT"] = int(p[1])
    return out


def mtime(d):
    return os.path.getmtime(os.path.join(d, "summary.json"))


runs.sort(key=mtime)
prev = {}
delta = {}
for d in runs:
    for host in ["client"] + ["worker-%d" % i for i in range(1, 6)]:
        f = os.path.join(d, host + ".nstat")
        if not os.path.exists(f):
            continue
        v = nstat(f)
        p = prev.get(host, {})
        delta[(d, host)] = {k: v[k] - p.get(k, 0) if k != "TIMEWAIT" else v[k] for k in v}
        prev[host] = v


def cpumax(p):
    # the busiest single vCPU over the loaded rows: its mean busy share and its %soft
    rows = {}
    for l in open(p, errors="replace"):
        x = l.split()
        if len(x) >= 12 and x[2].isdigit():
            rows.setdefault(x[2], []).append((100 - float(x[-1]) - float(x[9]), float(x[8])))
    if not rows:
        return float("nan"), float("nan")
    m = {c: (st.mean(b for b, _ in (v[1:-1] or v)), st.mean(q for _, q in (v[1:-1] or v))) for c, v in rows.items()}
    return m[max(m, key=lambda k: m[k][0])]


def busy(p, skip=True):
    r = [l.split() for l in open(p) if len(l.split()) >= 12 and l.split()[2] == "all"]
    r = r[1:-1] if skip and len(r) > 2 else r
    return st.mean(100 - float(x[-1]) - float(x[9]) for x in r) if r else float("nan")


rows = {}
for d in runs:
    if not re.search(r"/" + PFX + r"_\d+/", d):
        continue
    rate = int(re.search(PFX + r"_(\d+)", d).group(1))
    tag = re.sub(r"_r\d+$", "", os.path.basename(d))
    m = json.load(open(os.path.join(d, "summary.json")))["metrics"]
    g = lambda k, s: (m.get(k, {}).get(s) if isinstance(m.get(k), dict) else None)
    dur, con = m["http_req_duration"], m["http_req_connecting"]
    reqs = g("http_reqs", "count") or 0
    failed = (m.get("http_req_failed", {}).get("passes") or 0)
    dropped = g("dropped_iterations", "count") or 0
    wbusy = [busy(os.path.join(d, "worker-%d.nstat" % i), False) for i in range(1, 6) if os.path.exists(os.path.join(d, "worker-%d.nstat" % i))]
    stats = [int(l.split()[0]) for l in open(os.path.join(d, "stats.txt")) if l.strip()] if os.path.exists(os.path.join(d, "stats.txt")) else []
    cd = delta.get((d, "client"), {})
    pc = os.path.join(d, "mpstat_cpu.log")
    wtw = [delta.get((d, "worker-%d" % i), {}).get("TIMEWAIT", 0) for i in range(1, 6)]
    rows.setdefault((rate, tag), []).append(dict(
        thr=g("http_reqs", "rate") or 0, fail=100.0 * failed / reqs if reqs else 0, drop=100.0 * dropped / (reqs + dropped) if reqs + dropped else 0,
        p50=dur["med"], p95=dur["p(95)"], p99=dur["p(99)"], cmax=con["max"], c99=con["p(99)"],
        sched=busy(os.path.join(d, "mpstat.log")), client=busy(os.path.join(d, "client.mpstat")),
        wmax=max(wbusy) if wbusy else float("nan"), w1=(100.0 * max(stats) / sum(stats)) if stats else float("nan"),
        synre=cd.get("TcpExtTCPSynRetrans", 0), opens=cd.get("TcpActiveOpens", 0), tw=max(wtw),
        cpu1=cpumax(pc)[0] if os.path.exists(pc) else float("nan"), soft1=cpumax(pc)[1] if os.path.exists(pc) else float("nan")))
f = lambda v, fmt="%.1f": (fmt % st.mean(v)) + (" (" + fmt % min(v) + "-" + fmt % max(v) + ")" if len(v) > 1 else "")
cols = ["thr", "fail", "drop", "p50", "p95", "p99", "c99", "cmax", "sched", "cpu1", "soft1", "client", "wmax", "w1", "synre", "opens", "tw"]
print("rate,arm,n," + ",".join(cols))
for (rate, tag) in sorted(rows):
    v = rows[(rate, tag)]
    print("%d,%s,%d," % (rate, tag, len(v)) + ",".join(f([x[c] for x in v], "%.0f" if c in ("synre", "opens", "tw", "thr") else "%.2f") for c in cols))
