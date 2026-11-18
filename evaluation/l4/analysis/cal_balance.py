# Per-call CPU of every arm and condition of a calibration campaign (cal.sh), in microseconds per
# delivered call: the scheduler's traced irq+softirq time (lower bound for L4), its busy share while traced
# (Hiku), the capacity taken from the idle-priority counter against the idle runs of the same round
# (upper estimate, 95 % t-interval over rounds), and from the load runs of the same campaign the client
# (gateway) and the workers' CPU. Conditions and arms are read from the file names.
# args: results_dir campaign (e.g. results/l4 cal7)
import glob, json, math, os, re, statistics as st, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from paired import tq

res, name = sys.argv[1], sys.argv[2]
cal = os.path.join(res, name)
NCPU, NCLI = 4, int(os.environ.get("NCLI", 16))


def count(f):
    return sum(int(l.split()[2]) for l in open(f) if l.startswith("count"))


def traced(f):
    t = open(f).read()
    soft = sum(int(v) for v in re.findall(r"@soft\[\d+\]: (\d+)", t))
    h = re.search(r"@hard: (\d+)", t)
    return (soft + int(h.group(1) if h else 0)) / 1.2e9 if soft else None


def busy(path, skip=True):
    r = [l.split() for l in open(path, errors="replace") if len(l.split()) >= 12 and l.split()[2] == "all"]
    r = r[1:-1] if skip and len(r) > 2 else r
    return st.mean(100 - float(x[-1]) - float(x[9]) for x in r) if r else None


def rnd(f):
    return int(re.search(r"_r(\d+)", f).group(1))


def run_dir(arm, cond, mode, r):
    d = glob.glob(os.path.join(res, "%s_%s_%s_%s" % (name, arm, cond, mode), "*_r%d" % r))
    return d[0] if d else None


def rate(d):
    try:
        return json.load(open(os.path.join(d, "summary.json")))["metrics"]["http_reqs"]["rate"]
    except Exception:
        return None


def ci(v):
    if len(v) < 2:
        return "%.0f (n=%d)" % (st.mean(v), len(v)) if v else "-"
    m, s = st.mean(v), st.stdev(v)
    h = tq(0.975, len(v) - 1) * s / math.sqrt(len(v))
    return "%.0f [%.0f, %.0f] (n=%d)" % (m, m - h, m + h, len(v))


idle = {}
for f in glob.glob(os.path.join(cal, "idle_*_r*.hog.txt")):
    idle.setdefault(rnd(f), []).append(count(f))

keys = sorted({re.match(r"(.+)_r\d+\.(hog|trace)\.txt", os.path.basename(f)).group(1)
               for f in glob.glob(os.path.join(cal, "*_r*.*.txt")) if not os.path.basename(f).startswith("idle_")})
print("us per delivered call; capacity = upper estimate with 95 % CI over rounds")
for k in keys:
    arm, cond = k.split("_", 1)
    cap, trc, hbusy, cli, wrk, rates = [], [], [], [], [], []
    for f in glob.glob(os.path.join(cal, "%s_r*.hog.txt" % k)):
        r, d = rnd(f), run_dir(arm, cond, "hog", rnd(f))
        q = rate(d) if d else None
        if q and r in idle:
            cap.append(100 * (1 - count(f) / st.mean(idle[r])) / 100 * NCPU * 1e6 / q)
            rates.append(q)
    for f in glob.glob(os.path.join(cal, "%s_r*.trace.txt" % k)):
        r, d = rnd(f), run_dir(arm, cond, "trace", rnd(f))
        q = rate(d) if d else None
        t = traced(f)
        if q and t is not None:
            trc.append(t / 100 * NCPU * 1e6 / q)
        if q and d and os.path.exists(os.path.join(d, "mpstat.log")) and arm.endswith("7"):
            b = busy(os.path.join(d, "mpstat.log"))
            if b is not None:
                hbusy.append(b / 100 * NCPU * 1e6 / q)
    for mode in ("hog", "trace"):
        for d in glob.glob(os.path.join(res, "%s_%s_%s_%s" % (name, arm, cond, mode), "*_r*")):
            q = rate(d)
            if not q:
                continue
            c = os.path.join(d, "client.mpstat")
            if os.path.exists(c) and busy(c) is not None:
                cli.append(busy(c) / 100 * NCLI * 1e6 / q)
            w = [busy(os.path.join(d, "worker-%d.nstat" % i)) if os.path.exists(os.path.join(d, "worker-%d.nstat" % i)) else None for i in range(1, 6)]
            if all(x is not None for x in w):
                wrk.append(sum(w) / 100 * 2 * 1e6 / q)
    print("%-6s %-10s rate %6.0f | sched capacity %s | traced %s | busy %s | client %s | workers %s" % (
        arm, cond, st.mean(rates) if rates else 0, ci(cap), ci(trc), ci(hbusy), ci(cli), ci(wrk)))
