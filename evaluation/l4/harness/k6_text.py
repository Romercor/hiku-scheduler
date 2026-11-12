# Rebuilds the k6 fields of one row of runs.csv from the end-of-test summaries in k6-N.log, for a run
# whose k6 JSON summaries were not all copied (multi3 c50-s1_r4: 2 of 4). Requests and throughput are
# summed over the instances, the percentiles averaged as row.py does; client CPU is left blank.
# Writes runs_fixed.csv next to runs.csv.
# args: <campaign_dir> <tag> <rep>
import csv, glob, os, re, statistics as st, sys

camp, tag, rep = sys.argv[1:4]
d = os.path.join(camp, "%s_r%s" % (tag, rep))
req = fail = 0
thr, p50, p95, p99 = [], [], [], []


def ms(s):
    return float(s[:-2]) if s.endswith("ms") else float(s[:-1]) * 1000


for f in sorted(glob.glob(os.path.join(d, "k6-*.log"))):
    t = open(f, errors="replace").read()
    m = re.search(r"http_reqs\.+: (\d+)\s+([\d.]+)/s", t)
    req, thr = req + int(m.group(1)), thr + [float(m.group(2))]
    fail += int(re.search(r"http_req_failed\.+: [\d.]+%\s+(\d+) out of", t).group(1))
    dur = re.search(r"http_req_duration\.+: .*med=(\S+).*p\(95\)=(\S+) p\(99\)=(\S+)", t)
    p50, p95, p99 = p50 + [ms(dur.group(1))], p95 + [ms(dur.group(2))], p99 + [ms(dur.group(3))]
new = {"requests": str(req), "throughput": "%.2f" % sum(thr), "p50": "%.3f" % st.mean(p50),
       "p95": "%.3f" % st.mean(p95), "p99": "%.3f" % st.mean(p99), "fail_pct": "%.4f" % (100.0 * fail / req),
       "client_cpu": "", "client_cpu_max": ""}
rows = list(csv.DictReader(open(os.path.join(camp, "runs.csv"))))
for r in rows:
    if r["tag"] == tag and r["rep"] == rep:
        print("before", {k: r[k] for k in new})
        r.update(new)
        print("after ", new)
with open(os.path.join(camp, "runs_fixed.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
