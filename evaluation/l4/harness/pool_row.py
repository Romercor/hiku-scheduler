# Turns one run of pool.sh into a row of runs.csv: cold starts and instance-seconds from the
# workers' /stats, latency from k6.
# Why: poolbackend.go writes no OpenLambda log, so row.py cannot read these runs.
# args: campaign_dir tag rep position conc n_workers
import json, os, sys

out, tag, rep, pos, conc = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
nw = int(sys.argv[6])
d = os.path.join(out, "%s_r%d" % (tag, rep))
st = [l.split() for l in open(os.path.join(d, "stats.txt")) if len(l.split()) == 3]
reqs, cold, isec = sum(int(s[0]) for s in st), sum(int(s[1]) for s in st), sum(float(s[2]) for s in st)
m = json.load(open(os.path.join(d, "summary.json")))["metrics"]
dur = m["http_req_duration"]
thr, fail = m["http_reqs"]["rate"], 100.0 * m["http_req_failed"]["value"]
idle = [float(l.split()[-1]) for l in open(os.path.join(d, "mpstat.log"), errors="replace")
        if " all " in l and not l.startswith("Average")]
cpu = 100.0 - sum(idle) / len(idle) if idle else 0.0
coldpct = 100.0 * cold / reqs if reqs else 0.0
print("%-22s pos%d workers %d/%d %7d %7.1f/s p50 %6.1f p95 %7.1f p99 %7.1f cold %5.2f%% inst-s %8.0f fail %5.2f%% cpu %4.1f%%"
      % ("%s r%d" % (tag, rep), pos, len(st), nw, reqs, thr, dur["med"], dur["p(95)"], dur["p(99)"], coldpct, isec, fail, cpu))
csv = os.path.join(out, "runs.csv")
new = not os.path.exists(csv)
with open(csv, "a", newline="") as f:
    if new:
        f.write("tag,rep,pos,conc,requests,throughput,p50,p95,p99,fail_pct,cold_starts,cold_pct,inst_seconds,sched_cpu\n")
    f.write("%s,%d,%d,%d,%d,%.2f,%.3f,%.3f,%.3f,%.4f,%d,%.3f,%.1f,%.2f\n"
            % (tag, rep, pos, conc, reqs, thr, dur["med"], dur["p(95)"], dur["p(99)"], fail, cold, coldpct, isec, cpu))
