# Client and scheduler steal (mpstat 'all' rows, loaded rows) vs drop and connect p99, every sat7/lim7 run <= 32k.
import glob, json, os, re, statistics as st
R = "results/l4"
def steal(p):
    if not os.path.exists(p): return float("nan")
    hdr = None; v = []
    for l in open(p, errors="replace"):
        x = l.split()
        if "%steal" in x: hdr = x.index("%steal") - len(x)
        elif hdr is not None and len(x) > 5 and x[2] == "all" if len(x) > 2 else False:
            v.append(float(x[hdr]))
    v = v[1:-1] if len(v) > 2 else v
    return st.mean(v) if v else float("nan")
rows = []
for d in glob.glob(f"{R}/sat7_*/*_r*") + glob.glob(f"{R}/lim7_*/*_r*"):
    if not os.path.exists(d + "/summary.json"): continue
    rate = int(re.search(r"_(\d+)/", d).group(1))
    if rate > 32000: continue
    m = json.load(open(d + "/summary.json"))["metrics"]
    reqs = m["http_reqs"]["count"]; dr = m.get("dropped_iterations", {}).get("count", 0)
    rows.append((os.path.basename(d).rsplit("_r", 1)[0], rate, d[-1], steal(d + "/client.mpstat"), steal(d + "/mpstat.log"), 100 * dr / (reqs + dr), m["http_req_connecting"]["p(99)"]))
for arm in sorted({r[0] for r in rows}):
    rs = [r for r in rows if r[0] == arm]
    lo = [r for r in rs if r[3] < 10]; hi = [r for r in rs if r[3] >= 10]
    bad = lambda r: r[5] > 0.5
    xs, ys = [r[3] for r in rs], [r[5] for r in rs]
    mx, my = st.mean(xs), st.mean(ys)
    cor = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / ((sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** .5)
    print(f"{arm}: n={len(rs)} corr(client steal, drop)={cor:.2f}; steal<10: {sum(bad(r) for r in lo)}/{len(lo)} bad; steal>=10: {sum(bad(r) for r in hi)}/{len(hi)} bad")
for r in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
    if r[0].startswith("l4"): print("%-14s %6d r%s client steal %5.1f sched steal %4.1f drop %5.1f c99 %7.1f" % r)
