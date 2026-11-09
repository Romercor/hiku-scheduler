# Turns one run of matrix.sh or multi.sh into a row of runs.csv, from k6, the worker logs and the
# scheduler log. cov is plot.py's (only the workers seen in a second), cov_all counts every worker.
# Why: the worker logs are the only source both arms have, as the L4 datapath logs nothing per
# request. Scheduler CPU is all time not idle or stolen, since the L4 work runs in softirq. With
# several k6 instances the percentiles are averaged, as k6 exports no samples to merge.
# The columns after left_home were added for the re-test: client CPU, the split of cold starts, mean
# connection setup, worker CPU, forced evictions and the scheduler's end state and configuration.
# args: campaign_dir tag rep position n_workers   (env RUNS_CSV: write the row there instead)
import datetime, glob, json, os, re, sys

out, tag, rep, pos, nw = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
d = os.path.join(out, "%s_r%d" % (tag, rep))

cold = inv = one = more = maxi = evict = 0
per_sec, stamps = {}, []
for path in sorted(glob.glob(os.path.join(d, "worker-*.log"))):
    w = os.path.basename(path).replace(".log", "")
    for line in open(path, errors="replace"):
        if "Creating new sandbox" in line:
            cold += 1
        elif "increase instances to " in line:
            m = re.search(r"increase instances to (\d+)", line)
            if m:
                one, more, maxi = one + (m.group(1) == "1"), more + (m.group(1) != "1"), max(maxi, int(m.group(1)))
        elif "LambdaFunc.Invoke" in line:
            inv += 1
            m = re.match(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d+)", line)
            if m:
                stamps.append((datetime.datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S.%f"), w))
        if "reason=forced eviction" in line:
            evict += 1
if stamps:
    t0 = min(t for t, _ in stamps)
    for ts, w in stamps:
        c = per_sec.setdefault(int((ts - t0).total_seconds()), {})
        c[w] = c.get(w, 0) + 1


def stdev(v):
    mu = sum(v) / len(v)
    return (sum((x - mu) ** 2 for x in v) / len(v)) ** 0.5


covs, covs_all = [], []
for sec in range(max(per_sec) + 1 if per_sec else 0):
    wc = per_sec.get(sec, {})
    mean = sum(wc.values()) / nw
    covs.append(stdev(list(wc.values())) / mean if wc else 0.0)
    covs_all.append(stdev([wc.get("worker-%d" % i, 0) for i in range(1, nw + 1)]) / mean if wc else 0.0)
cov = sum(covs) / len(covs) if covs else 0.0
cov_all = sum(covs_all) / len(covs_all) if covs_all else 0.0

reqs = thr = p50 = p95 = p99 = fail = 0.0
sums = [json.load(open(sp))["metrics"] for sp in glob.glob(os.path.join(d, "summary*.json"))]
for m in sums:
    dur, n = m.get("http_req_duration", {}), m.get("http_reqs", {}).get("count", 0)
    reqs, thr = reqs + n, thr + m.get("http_reqs", {}).get("rate", 0.0)
    p50, p95, p99 = (p50 + dur.get("med", 0.0) / len(sums), p95 + dur.get("p(95)", 0.0) / len(sums),
                     p99 + dur.get("p(99)", 0.0) / len(sums))
    fail += 100.0 * n * m.get("http_req_failed", {}).get("value", 0.0)
fail = fail / reqs if reqs else 0.0

mp = [l.split() for path in glob.glob(os.path.join(d, "mpstat*.log"))
      for l in open(path, errors="replace") if " all " in l and not l.startswith("Average")]
steal = sum(float(f[-4]) for f in mp) / len(mp) if mp else 0.0
cpu = 100.0 - sum(float(f[-1]) for f in mp) / len(mp) - steal if mp else 0.0
conn = max([m.get("http_req_connecting", {}).get("max", 0.0) for m in sums] or [0.0])
conn_avg = sum(m.get("http_req_connecting", {}).get("avg", 0.0) for m in sums) / len(sums) if sums else 0.0


def busy(path):
    v = [l.split() for l in open(path, errors="replace") if " all " in l and not l.startswith("Average")]
    return [(100.0 - float(f[-1]) - float(f[-4]), float(f[-4])) for f in v if len(f) >= 11]


cl = busy(os.path.join(d, "client.mpstat")) if os.path.exists(os.path.join(d, "client.mpstat")) else []
wb = [busy(p) for p in sorted(glob.glob(os.path.join(d, "worker-*.mpstat")))]
wb = [w for w in wb if w]

keys = ["flows", "no-free", "signals", "refused", "dropped", "left-home"]
more_keys = ["by-addr", "forward", "live", "sig-full", "d-noport", "fin-freed"]
nat, cfg, wflows = {}, "", 0
for path in sorted(glob.glob(os.path.join(d, "sched*.log"))):
    last = {}
    for l in open(path, errors="replace"):
        if "NAT:" in l:
            last = dict(re.findall(r"([a-z-]+)=(\d+)", l))
            wf = re.search(r"wflows=([\d ]+)", l)
            lastw = sum(int(x) for x in wf.group(1).split()) if wf else 0
        elif "strategy=" in l and not cfg:
            m = re.search(r"strategy=(\d+) fallback=(\d+)", l)
            cfg = "%s,%s" % m.groups() if m else ""
    if last:
        wflows += lastw
    for k in keys + more_keys:
        if k in last:
            nat[k] = str(int(nat.get(k, 0)) + int(last[k]))

coldpct = 100.0 * cold / inv if inv else 0.0
print("%-24s pos%d %6d %5.1f/s p50 %5.1f p95 %6.1f p99 %6.1f cold %4.1f%% cov %.3f fail %4.2f%% "
      "cpu %4.2f%% steal %4.2f conn %5.0f nofree %s/%s drop %s"
      % ("%s r%d" % (tag, rep), pos, reqs, thr, p50, p95, p99, coldpct, cov, fail, cpu, steal, conn,
         nat.get("no-free", "-"), nat.get("flows", "-"), nat.get("dropped", "-")))

extra = [("client_cpu", "%.2f" % (sum(x for x, _ in cl) / len(cl)) if cl else ""),
         ("client_cpu_max", "%.2f" % max(x for x, _ in cl) if cl else ""),
         ("to1_pct", "%.4f" % (100.0 * one / inv) if inv else ""),
         ("to2_pct", "%.4f" % (100.0 * more / inv) if inv else ""),
         ("conn_avg", "%.4f" % conn_avg), ("max_inst", str(maxi)), ("forced_evict", str(evict)),
         ("wcpu_mean", "%.2f" % (sum(sum(x for x, _ in w) / len(w) for w in wb) / len(wb)) if wb else ""),
         ("wcpu_max", "%.2f" % max(sum(x for x, _ in w) / len(w) for w in wb) if wb else ""),
         ("wsteal_max", "%.2f" % max(sum(y for _, y in w) / len(w) for w in wb) if wb else ""),
         ("wflows_end", str(wflows) if nat else ""), ("strategy_fallback", cfg.replace(",", "+"))]
extra += [(k.replace("-", "_"), nat.get(k, "")) for k in more_keys]

csv = os.environ.get("RUNS_CSV") or os.path.join(out, "runs.csv")
new = not os.path.exists(csv)
with open(csv, "a", newline="") as f:
    if new:
        f.write("tag,rep,pos,requests,throughput,p50,p95,p99,fail_pct,cold_starts,invocations,"
                "cold_pct,cov,cov_all,sched_cpu,steal,conn_max,"
                + ",".join(k.replace("-", "_") for k in keys) + "," + ",".join(k for k, _ in extra) + "\n")
    f.write("%s,%d,%d,%d,%.2f,%.3f,%.3f,%.3f,%.4f,%d,%d,%.3f,%.4f,%.4f,%.2f,%.2f,%.1f,%s,%s\n"
            % (tag, rep, pos, reqs, thr, p50, p95, p99, fail, cold, inv, coldpct, cov, cov_all, cpu,
               steal, conn, ",".join(nat.get(k, "") for k in keys), ",".join(v for _, v in extra)))
