# The L4 scheduler's counters per arm over one or more pool.sh campaigns: per run the last NAT line of
# sched.log, plus any runs.csv column, the share of decisions without a free slot (no-free / flows),
# and, where stats.txt holds the calls per worker, worker 1's share. With --pair, the paired
# difference of every later campaign against the first by repetition, and the relative change.
# Why: these counters are not columns of the pool campaigns' runs.csv (refused4/5, coal3_*).
# args: <campaign_dir> ... [--keys k1,k2] [--pair]   (default keys: refused,penal-skip)
import csv, glob, math, os, re, statistics as st, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paired import tq

args = [a for a in sys.argv[1:] if not a.startswith("--")]
keys = "refused,penal-skip"
for i, a in enumerate(sys.argv):
    if a == "--keys":
        keys = sys.argv[i + 1]
        args.remove(keys)
keys = keys.split(",")


def run(d, row):
    last = [l for l in open(os.path.join(d, "sched.log")) if " NAT: " in l][-1]
    c = {k: float(v) for k, v in re.findall(r"([a-z-]+)=(\d+)", last.split("|")[0])}
    c.update({k: float(v) for k, v in row.items() if k not in ("tag", "rep") and re.match(r"^-?[\d.]+$", v or "")})
    c["no-free %"] = 100.0 * c["no-free"] / c["flows"] if c.get("flows") else float("nan")
    s = os.path.join(d, "stats.txt")
    if os.path.exists(s):
        calls = [int(l.split()[0]) for l in open(s) if l.strip()]
        c["worker 1 %"] = 100.0 * calls[0] / sum(calls)
    return c


def ci(x):
    m = st.mean(x)
    h = tq(0.975, len(x) - 1) * st.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else float("nan")
    return "%+.2f [%+.2f, %+.2f]" % (m, m - h, m + h)


data = {}
for camp in args:
    rows = {(r["tag"], r["rep"]): r for r in csv.DictReader(open(os.path.join(camp, "runs.csv")))}
    for d in sorted(glob.glob(os.path.join(camp, "*_r*"))):
        tag, rep = re.match(r"(.+)_r(\d+)$", os.path.basename(d)).groups()
        data.setdefault((camp, tag), {})[int(rep)] = run(d, rows[(tag, rep)])
show = keys + ["no-free %", "fail_pct", "worker 1 %"]
for (camp, tag), runs in data.items():
    print("%s %s (%d runs)" % (os.path.basename(camp.rstrip("/\\")), tag, len(runs)))
    for k in show:
        v = [r[k] for r in runs.values() if k in r]
        if v:
            print("  %-12s mean %.4g, range %.4g-%.4g" % (k, st.mean(v), min(v), max(v)))
if "--pair" in sys.argv:
    base = list(data.items())[0]
    for (camp, tag), runs in list(data.items())[1:]:
        ks = sorted(set(runs) & set(base[1]))
        print("%s - %s (%d pairs)" % (os.path.basename(camp.rstrip("/\\")), os.path.basename(base[0][0].rstrip("/\\")), len(ks)))
        for k in keys + ["no-free %"]:
            x = [runs[r][k] - base[1][r][k] for r in ks]
            rel = [100.0 * (runs[r][k] / base[1][r][k] - 1) for r in ks if base[1][r][k]]
            print("  %-12s %s, relative %s %%" % (k, ci(x), ci(rel) if len(rel) == len(ks) else "-"))
