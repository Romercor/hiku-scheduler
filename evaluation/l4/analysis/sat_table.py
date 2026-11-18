# Saturation table: per rate and arm, over all runs and over runs with client steal < 10 %: delivered calls/s,
# dropped %, p99 and connect p99 (medians for the tails), client steal; sat7 (4-24k) and lim7 (28-64k, L4 only).
import glob, json, os, re, statistics as st
R = "results/l4"
def steal(p):
    hdr = None; v = []
    for l in open(p, errors="replace"):
        x = l.split()
        if "%steal" in x: hdr = x.index("%steal") - len(x)
        elif hdr is not None and len(x) > 5 and x[2] == "all": v.append(float(x[hdr]))
    v = v[1:-1] if len(v) > 2 else v
    return st.mean(v) if v else float("nan")
tab = {}
for d in glob.glob(f"{R}/sat7_*/*_r*") + glob.glob(f"{R}/lim7_*/*_r*"):
    if not os.path.exists(d + "/summary.json"): continue
    rate = int(re.search(r"_(\d+)/", d).group(1)); arm = os.path.basename(d).rsplit("_r", 1)[0]
    m = json.load(open(d + "/summary.json"))["metrics"]
    reqs = m["http_reqs"]["count"]; dr = m.get("dropped_iterations", {}).get("count", 0)
    tab.setdefault((arm, rate), []).append(dict(thr=m["http_reqs"]["rate"], drop=100 * dr / (reqs + dr), p99=m["http_req_duration"]["p(99)"],
        c99=m["http_req_connecting"]["p(99)"], steal=steal(d + "/client.mpstat"), fail=100 * m.get("http_req_failed", {}).get("passes", 0) / reqs))
print("arm rate | all: n thr drop(med,max) p99med c99med steal | low-steal: n thr drop(max) p99med c99med")
for (arm, rate) in sorted(tab, key=lambda k: (k[0], k[1])):
    v = tab[(arm, rate)]; lo = [x for x in v if x["steal"] < 10]
    f = lambda xs, k, fn: fn([x[k] for x in xs]) if xs else float("nan")
    print("%-12s %6d | %d %6.0f %5.1f %5.1f %7.0f %7.0f %4.1f | %d %6.0f %5.1f %7.0f %7.0f" % (arm, rate, len(v), f(v, "thr", st.mean), f(v, "drop", st.median), f(v, "drop", max),
        f(v, "p99", st.median), f(v, "c99", st.median), f(v, "steal", st.mean), len(lo), f(lo, "thr", st.mean), f(lo, "drop", max), f(lo, "p99", st.median), f(lo, "c99", st.median)))
