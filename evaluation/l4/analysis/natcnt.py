# Last NAT counter line of every L4 sat7/lim7 run (time order): flows, dropped (d-noflow), syn-stale, fin-freed,
# no-free, live, plus the run's drop % and connect p99.
import glob, json, os, re
R = "results/l4"
runs = [d for s in ("sat7", "lim7") for d in glob.glob(f"{R}/{s}_*/l4-*_r*") if os.path.exists(d + "/summary.json")]
runs.sort(key=lambda d: os.path.getmtime(d + "/summary.json"))
for d in runs:
    l = [x for x in open(d + "/sched.log") if "NAT:" in x][-1]
    c = dict(re.findall(r"([a-z-]+)=(\d+)", l))
    m = json.load(open(d + "/summary.json"))["metrics"]
    reqs = m["http_reqs"]["count"]; dr = m.get("dropped_iterations", {}).get("count", 0)
    print("%-11s r%s flows %8s noflow %7s syn-stale %7s fin-freed %8s unfreed %6d no-free %6s drop %5.1f c99 %7.1f" % (
        d.split("/")[-2], d[-1], c["flows"], c["d-noflow"], c["syn-stale"], c["fin-freed"], int(c["flows"]) - int(c["fin-freed"]), c["no-free"], 100 * dr / (reqs + dr), m["http_req_connecting"]["p(99)"]))
