# Paired differences between two arms of one campaign: per metric the mean difference over the
# repetitions both arms completed, its 95 % confidence interval (Student t, n-1 degrees of freedom)
# and how many pairs share the sign of the mean. --positions prints, per arm and position, the mean
# residual of a run from its repetition's mean.
# Why: the arms of a repetition share a seed and the cluster's state of that hour, so the
# differences within a repetition are far less noisy than the arms' means.
# args: <campaign_dir> <armA> <armB> [metric,...] | <campaign_dir> --positions [metric]
#   env: SKIP (comma-separated repetitions to leave out)
import csv, glob, math, os, re, statistics as st, sys

DEFAULT = ["cold_pct", "to1_pct", "to2_pct", "p50", "p95", "p99", "throughput", "cov", "fail_pct"]


def betacf(a, b, x):
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1.0 + num / c
            c = c if abs(c) > 1e-300 else 1e-300
            h *= d * c
    return h


def ibeta(a, b, x):
    if x <= 0 or x >= 1:
        return max(0.0, min(1.0, x))
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb) * betacf(a, b, x) / a
    return 1 - math.exp(lb) * betacf(b, a, 1 - x) / b


def tq(p, df):
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        t = (lo + hi) / 2
        if 1 - 0.5 * ibeta(df / 2, 0.5, df / (df + t * t)) < p:
            lo = t
        else:
            hi = t
    return (lo + hi) / 2


def churn(d):
    one = more = inv = 0
    for path in glob.glob(os.path.join(d, "worker-*.log")):
        for line in open(path, errors="replace"):
            m = re.search(r"increase instances to (\d+)", line)
            if m:
                one, more = one + (m.group(1) == "1"), more + (m.group(1) != "1")
            elif "LambdaFunc.Invoke" in line:
                inv += 1
    return ("%.4f" % (100.0 * one / inv), "%.4f" % (100.0 * more / inv)) if inv else ("", "")


def load(camp):
    runs = {}
    for r in csv.DictReader(open(os.path.join(camp, "runs.csv"))):
        if float(r["requests"] or 0) <= 0 or r["rep"] in os.environ.get("SKIP", "").split(","):
            continue
        if not r.get("to1_pct"):
            r["to1_pct"], r["to2_pct"] = churn(os.path.join(camp, "%s_r%s" % (r["tag"], r["rep"])))
        runs.setdefault(r["tag"], {})[int(r["rep"])] = r
    return runs


def diff(runs, a, b, metrics):
    ks = sorted(set(runs.get(a, {})) & set(runs.get(b, {})))
    print("%s - %s  (%d pairs)" % (a, b, len(ks)))
    for c in metrics:
        try:
            x = [float(runs[a][k][c]) - float(runs[b][k][c]) for k in ks]
        except (KeyError, ValueError):
            continue
        n = len(x)
        if n < 2:
            continue
        m = st.mean(x)
        h = tq(0.975, n - 1) * st.stdev(x) / math.sqrt(n)
        same = sum(1 for v in x if (v > 0) == (m > 0) and v != 0)
        print("  %-12s %+9.3f [%+9.3f, %+9.3f]  same sign %d/%d%s" % (c, m, m - h, m + h, same, n,
              "" if m - h <= 0 <= m + h else "  *"))


def positions(runs, metric):
    reps = {k for t in runs.values() for k in t}
    res = {}
    for k in reps:
        vals = {t: float(runs[t][k][metric]) for t in runs if k in runs[t]}
        mu = st.mean(vals.values())
        for t, v in vals.items():
            res.setdefault((t, int(runs[t][k]["pos"])), []).append(v - mu)
    npos = max(p for _, p in res)
    print("%s residual from the repetition mean, by position" % metric)
    print("%-20s" % "arm" + "".join("%8d" % p for p in range(1, npos + 1)))
    for t in runs:
        print("%-20s" % t + "".join("%8s" % ("%+.2f" % st.mean(res[(t, p)]) if (t, p) in res else "-")
                                    for p in range(1, npos + 1)))
    for p in range(1, npos + 1):
        v = [x for (t, q), xs in res.items() if q == p for x in xs]
        print("  position %d: mean %+.3f over %d runs" % (p, st.mean(v), len(v)))


if __name__ == "__main__":
    camp = sys.argv[1]
    runs = load(camp)
    if sys.argv[2] == "--positions":
        positions(runs, sys.argv[3] if len(sys.argv) > 3 else "cold_pct")
    else:
        diff(runs, sys.argv[2], sys.argv[3], sys.argv[4].split(",") if len(sys.argv) > 4 else DEFAULT)
