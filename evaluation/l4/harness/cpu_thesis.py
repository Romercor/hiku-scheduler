# Every number of the thesis's section on scheduler CPU (tables tab:cpu and tab:cpu-bound): Hiku's busy
# share in the main runs (sat3) and the rerun (sat4), and the calibration rounds cal3 (traced time,
# tick-sampled softirq under the idle-priority counter, eBPF run time), cal4 and cal5 (capacity taken
# from the compiled counter). Busy share = 100 - idle - steal over the fully loaded mpstat rows (first
# and last 5-s row dropped). Exclusions: cal3 round 3 for Hiku at 3,000 calls/s (client ports), cal4 at
# 3,000 calls/s (client ports, replaced by cal5), the empty L4 trace of cal5 round 3.
# Why: cpu_cal.py averages all mpstat rows and has no intervals; the thesis uses these.
# args: results_dir (results/l4)
import csv, glob, json, math, os, re, statistics as st, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paired import tq

res = sys.argv[1]
RATE = {"noka_3000": 3000, "ka_2000": 2000, "ka_6000": 6000, "ka_12000": 12000}
CAL = ["noka_3000", "ka_6000", "ka_12000"]
NCPU, SECS = 4, 30


def rows(path):
    out = []
    for l in open(path):
        p = l.split()
        if len(p) >= 12 and p[2] == "all":
            out.append((datetime.strptime(p[0] + p[1], "%I:%M:%S%p"), [float(x) for x in p[3:]]))
    return out


def busy(path, col=None):
    r = rows(path)[1:-1]
    return st.mean(v[col] if col is not None else 100 - v[-1] - v[6] for _, v in r) if r else None


def rnd(path):
    return int(re.search(r"_r(\d+)", path).group(1))


def runs(camp, tag):
    return {rnd(d): d for d in glob.glob(os.path.join(res, camp, tag + "_r*"))}


def thr(d):
    tag, rep = re.match(r"(.+)_r(\d+)$", os.path.basename(d)).groups()
    for r in csv.DictReader(open(os.path.join(os.path.dirname(d), "runs.csv"))):
        if r["tag"] == tag and r["rep"] == rep:
            return float(r["throughput"])


def traced(f, hard=True):
    t = open(f).read()
    soft = sum(int(v) for v in re.findall(r"@soft\[\d+\]: (\d+)", t))
    h = re.search(r"@hard: (\d+)", t)
    if not h:
        return None
    return (soft + (int(h.group(1)) if hard else 0)) / (SECS * NCPU * 1e7)


def stat(f):
    ls = [l.split() for l in open(f) if l.startswith("cpu ")]
    a, b = [int(x) for x in ls[0][1:]], [int(x) for x in ls[-1][1:]]
    d = [y - x for x, y in zip(a, b)]
    return d, sum(d[:8])


def soft_ticks(f, hard=False):
    d, tot = stat(f)
    return 100.0 * (d[6] + (d[5] if hard else 0)) / tot


def count(f):
    return sum(int(l.split()[2]) for l in open(f) if l.startswith("count"))


def ebpf(f):
    t, dec, objs, i = open(f).read(), json.JSONDecoder(), [], 0
    while t[i:].strip():
        s = len(t) - len(t[i:].lstrip())
        o, n = dec.raw_decode(t, s)
        objs.append(o)
        i = n
    run = lambda o: {p["name"]: (p.get("run_time_ns", 0), p.get("run_cnt", 0)) for p in o if p.get("name") in ("availability", "nat")}
    a, b = run(objs[0]), run(objs[-1])
    ns = sum(b[k][0] - a[k][0] for k in b)
    return ns / (SECS * NCPU * 1e7), b["nat"][1] - a["nat"][1]


def rng(v, f="%.1f"):
    return (f + " (" + f + "-" + f + ")") % (st.mean(v), min(v), max(v))


def ci(v):
    m, h = st.mean(v), tq(0.975, len(v) - 1) * st.stdev(v) / math.sqrt(len(v))
    return "%.1f [%.1f, %.1f]" % (m, m - h, m + h), m + h


def usec(pct, rate):
    return pct / 100 * NCPU * 1e6 / rate


print("== Main runs (sat3, 5 repetitions): busy share of the scheduler, fully loaded rows, no steal")
for cond in ["noka_3000", "ka_2000", "ka_6000", "ka_12000"]:
    out = {}
    for tag in ("l7-pull", "l7-pullord", "l4-ord-least"):
        out[tag] = {r: busy(os.path.join(d, "mpstat.log")) for r, d in runs("sat3_" + cond, tag).items()}
    p = out["l7-pull"]
    us = [usec(p[r], thr(d)) for r, d in runs("sat3_" + cond, "l7-pull").items()]
    dd = [out["l7-pullord"][r] - p[r] for r in p if r in out["l7-pullord"]]
    print("  %-9s Hiku pull %s, %.0f-%.0f us/call; pull-ordered %s, ordered - pull %s; L4 sampled %s" % (
        cond, rng(list(p.values())), min(us), max(us), rng(list(out["l7-pullord"].values())), ci(dd)[0],
        rng(list(out["l4-ord-least"].values()), "%.2f")))

print("\n== Client system time with one connection per call (max per run over 5-s samples)")
for camp in ("sat3_noka_3000", "cal3_l7_noka_3000_trace", "cal3_l7_noka_3000_hog", "cal3_l4_noka_3000_trace",
             "cal3_l4_noka_3000_hog", "cal3_l4_noka_3000_stats", "sat4_noka_3000"):
    for tag in ("l7-pull", "l7-pullord", "l4-ord-least"):
        ds = runs(camp, tag)
        if ds:
            mx = [max(v[2] for _, v in rows(os.path.join(d, "client.mpstat"))) for d in ds.values()]
            print("  %-26s %-13s %.0f-%.0f %%" % (camp, tag, min(mx), max(mx)))
# Hiku's runs with one connection per call in which the scheduler's busy share is measured: sat3 (both
# strategies) and the traced cal3 runs without round 3 (the hog runs keep every vCPU busy).
diffs = []
for camp, tag in (("sat3_noka_3000", "l7-pull"), ("sat3_noka_3000", "l7-pullord"), ("cal3_l7_noka_3000_trace", "l7-pull")):
    for r, d in runs(camp, tag).items():
        if camp.startswith("cal3") and r == 3:
            continue
        cl = rows(os.path.join(d, "client.mpstat"))
        hi, lo = [], []
        for t, v in rows(os.path.join(d, "mpstat.log"))[1:-1]:
            c = min(cl, key=lambda x: abs((x[0] - t).total_seconds()))
            if abs((c[0] - t).total_seconds()) > 3:
                continue
            b = 100 - v[-1] - v[6]
            (hi if c[1][2] >= 30 else lo if c[1][2] < 15 else []).append(b)
        if hi and lo:
            diffs.append(st.mean(hi) - st.mean(lo))
print("  scheduler busy, client sys >= 30 %% minus < 15 %%, same run: %s pp over %d runs" % (ci(diffs)[0], len(diffs)))

print("\n== Calibration cal3 (5 rounds; Hiku at 3,000 without round 3)")
for cond in CAL:
    cal = os.path.join(res, "cal3")
    l4t = {rnd(f): traced(f) for f in glob.glob(os.path.join(cal, "l4_%s_r*.trace.txt" % cond))}
    l7t = {rnd(f): traced(f) for f in glob.glob(os.path.join(cal, "l7_%s_r*.trace.txt" % cond))}
    hb = {r: busy(os.path.join(d, "mpstat.log")) for r, d in runs("cal3_l7_%s_trace" % cond, "l7-pull").items()}
    hs = {r: busy(os.path.join(d, "mpstat.log"), 5) for r, d in runs("cal3_l7_%s_trace" % cond, "l7-pull").items()}
    if cond == "noka_3000":
        for x in (hb, hs, l7t):
            x.pop(3, None)
    tick = {rnd(f): soft_ticks(f) for f in glob.glob(os.path.join(cal, "l4_%s_r*.hog.txt" % cond))}
    l4soft = {rnd(f): traced(f, False) for f in glob.glob(os.path.join(cal, "l4_%s_r*.trace.txt" % cond))}
    eb = {rnd(f): ebpf(f) for f in glob.glob(os.path.join(cal, "l4_%s_r*.stats.txt" % cond))}
    samp = {r: busy(os.path.join(d, "mpstat.log")) for r, d in runs("cal3_l4_%s_stats" % cond, "l4-ord-least").items()}
    rate = RATE[cond]
    ratio = [hb[r] / l4t[r] for r in hb if r in l4t]
    print("  %s" % cond)
    print("    Hiku busy (traced runs) %s; L4 traced %s; L4 softirq ticks, busy %s; eBPF %s" % (
        rng(list(hb.values())), rng(list(l4t.values())), rng(list(tick.values())),
        rng([v[0] for v in eb.values()], "%.2f")))
    print("    Hiku busy / L4 traced per round %.2f-%.2f (L4 share %.1f-%.1f %%)" % (
        min(ratio), max(ratio), 100 / max(ratio), 100 / min(ratio)))
    hu = [usec(hb[r], thr(d)) for r, d in runs("cal3_l7_%s_trace" % cond, "l7-pull").items() if r in hb]
    print("    per call: L4 traced %.0f-%.0f us, Hiku busy %.0f-%.0f us (delivered calls), eBPF %.1f-%.1f us" % (
        min(usec(v, rate) for v in l4t.values()), max(usec(v, rate) for v in l4t.values()), min(hu), max(hu),
        min(usec(v[0], rate) for v in eb.values()), max(usec(v[0], rate) for v in eb.values())))
    pk = [eb[r][1] / (SECS * rate) for r in eb]
    pp = [usec(l4t[r], rate) / (eb[r][1] / (SECS * rate)) for r in eb if r in l4t]
    print("    TC runs per call %.1f-%.1f; traced per packet %.1f-%.1f us" % (min(pk), max(pk), min(pp), max(pp)))
    print("    Hiku sampled softirq %s vs traced soft+hard %s" % (rng(list(hs.values())), rng(list(l7t.values()))))
    tt = [tick[r] / l4t[r] for r in tick if r in l4t]
    print("    ticks / traced: means %.3f, per round %.3f-%.3f; ticks / traced softirq only: means %.3f" % (
        st.mean(tick.values()) / st.mean(l4t.values()), min(tt), max(tt),
        st.mean(tick.values()) / st.mean(l4soft.values())))
    sr = [samp[r] / eb[r][0] for r in samp if r in eb]
    print("    L4 sampled busy in the stats runs / eBPF %.2f mean (%.2f-%.2f)" % (st.mean(sr), min(sr), max(sr)))

print("\n== Upper estimate (cal4 at 6,000 and 12,000, cal5 at 3,000; 5 rounds)")
below = total = 0
for cond, name in (("noka_3000", "cal5"), ("ka_6000", "cal4"), ("ka_12000", "cal4")):
    cal = os.path.join(res, name)
    idle = {}
    for f in glob.glob(os.path.join(cal, "idle_*_r*.hog.txt")):
        idle.setdefault(rnd(f), []).append(count(f))
    cap = lambda arm: {rnd(f): 100 * (1 - count(f) / st.mean(idle[rnd(f)]))
                       for f in glob.glob(os.path.join(cal, "%s_%s_r*.hog.txt" % (arm, cond)))}
    c4, c7 = cap("l4"), cap("l7")
    l4t = {r: v for r, v in ((rnd(f), traced(f)) for f in glob.glob(os.path.join(cal, "l4_%s_r*.trace.txt" % cond))) if v}
    hb = {r: busy(os.path.join(d, "mpstat.log")) for r, d in runs("%s_l7_%s_trace" % (name, cond), "l7-pull").items()}
    spread = max(100 * (max(v) - min(v)) / st.mean(v) for v in idle.values())
    ex = [c4[r] - l4t[r] for r in c4 if r in l4t]
    below += sum(1 for v in ex if v < 0)
    total += len(ex)
    s4, up4 = ci(list(c4.values()))
    rate = RATE[cond]
    print("  %-9s L4 capacity %s, traced %s (n=%d); Hiku capacity %s, busy %s; idle spread up to %.1f %%" % (
        cond, s4, rng(list(l4t.values())), len(l4t), ci(list(c7.values()))[0], rng(list(hb.values())), spread))
    print("            Hiku - L4 capacity %s (L4 lower in %d of %d rounds); L4 capacity - traced %s" % (
        ci([c7[r] - c4[r] for r in c4 if r in c7])[0], sum(1 for r in c4 if r in c7 and c4[r] < c7[r]),
        len([r for r in c4 if r in c7]), ci(ex)[0]))
    print("            Hiku capacity / busy share %.2f (means); per call L4 capacity %.0f us (%.0f at upper end), Hiku busy %.0f us" % (
        st.mean(c7.values()) / st.mean(hb.values()), usec(st.mean(c4.values()), rate), usec(up4, rate),
        usec(st.mean(hb.values()), rate)))
    if cond == "noka_3000":
        print("            parity needs the untraced part at %.1f x traced; upper end of the excess %.1f x" % (
            (st.mean(hb.values()) - st.mean(l4t.values())) / st.mean(l4t.values()),
            (st.mean(ex) + tq(0.975, len(ex) - 1) * st.stdev(ex) / math.sqrt(len(ex))) / st.mean(l4t.values())))
print("  L4 capacity below its traced time in %d of %d rounds" % (below, total))

print("\n== Rerun at 3,000 calls/s with widened client ports (sat4, 5 repetitions)")
ds = runs("sat4_noka_3000", "l7-pull")
b = [busy(os.path.join(d, "mpstat.log")) for d in ds.values()]
us = [usec(busy(os.path.join(d, "mpstat.log")), thr(d)) for d in ds.values()]
print("  Hiku busy %.1f-%.1f %%, %.0f-%.0f us/call" % (min(b), max(b), min(us), max(us)))
