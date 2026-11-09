# Turns one rate of sigcost.sh into a row of runs.csv: ingested rate, ns per signal from bpftool,
# CPU from mpstat.
# Why: these runs have no k6 or worker logs, so row.py cannot read them.
# args: campaign_dir pass rate_pps sent_pps seconds pairs
import os, re, sys

d, p, rate, sent, secs, pairs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6]
s = open("%s/sched_%s_%s.txt" % (d, p, rate)).read()
num = lambda k: int(re.findall(k + r"[= ](\d+)", s)[-1])
idle = {l.split()[1]: float(l.split()[-1]) for l in open("%s/mpstat_%s_%s.txt" % (d, p, rate)) if "%" not in l}
csv = os.path.join(d, "runs.csv")
new = not os.path.exists(csv)
with open(csv, "a", newline="") as f:
    if new:
        f.write("pass,pairs,target_pps,sent_pps,ingested_pps,not_stored,ns_per_signal,cpu_pct,busiest_core_pct\n")
    row = "%s,%s,%s,%s,%d,%d,%.0f,%.2f,%.2f" % (
        p, pairs, rate, sent, num("signals") / secs, num("sig-full"),
        num("run_time_ns") / max(num("run_cnt"), 1), 100 - idle["all"],
        100 - min(v for k, v in idle.items() if k != "all"))
    f.write(row + "\n")
    print(row)
