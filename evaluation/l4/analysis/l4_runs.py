# Every sat7/lim7 run in time order: rate, arm, rep, drop %, failed %, connect p99, client SYN retransmits (delta),
# worker TIME-WAIT max, and the gap since the previous run ended.
import glob, json, os, re, time
R = "results/l4"
runs = [d for s in ("sat7", "lim7") for d in glob.glob(f"{R}/{s}_*/*_r*") if os.path.exists(d + "/summary.json")]
runs.sort(key=lambda d: os.path.getmtime(d + "/summary.json"))
def nst(f):
    o = {}
    for l in open(f, errors="replace"):
        p = l.split()
        if len(p) >= 2 and p[1].isdigit(): o[p[0]] = int(p[1])
    return o
prev = {}; pend = None
for d in runs:
    m = json.load(open(d + "/summary.json"))["metrics"]
    reqs = m["http_reqs"]["count"]; dr = m.get("dropped_iterations", {}).get("count", 0)
    fa = m.get("http_req_failed", {}).get("passes", 0)
    c = nst(d + "/client.nstat") if os.path.exists(d + "/client.nstat") else {}
    syn = c.get("TcpExtTCPSynRetrans", 0) - prev.get("syn", 0); prev["syn"] = c.get("TcpExtTCPSynRetrans", 0)
    t = os.path.getmtime(d + "/summary.json")
    st = open(d + "/sched_start.txt").read().strip() if os.path.exists(d + "/sched_start.txt") else ""
    print("%s %-9s %-14s r%s drop %5.1f fail %4.2f c99 %7.1f syn %6d" % (time.strftime("%d %H:%M", time.localtime(t)), d.split("/")[-2], re.sub(r"_r\d+$", "", d.split("/")[-1]), d[-1], 100 * dr / (reqs + dr), 100 * fa / reqs, m["http_req_connecting"]["p(99)"], syn))
