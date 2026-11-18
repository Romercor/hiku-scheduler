# Means (with sample standard deviation) of every arm and the paired differences of the reruns: comparison with
# Hiku (paper load and replay), reload campaign, top-40, bursts, skewed workloads, open loop, strategies,
# connection reuse, several schedulers, dead worker, lost announcements. Run merge.py first.
# usage: bash evaluation/l4/analysis/numbers.sh (from the repository root)
N=results/l4; G=results/merged; P="python3 evaluation/l4/harness/paired.py"
M=throughput,p50,p95,p99,cold_pct,to1_pct,to2_pct,cov,fail_pct
means() { python3 - "$1" <<'PY'
import csv, sys, statistics as st
rows = [r for r in csv.DictReader(open(sys.argv[1] + "/runs.csv")) if float(r["requests"] or 0) > 0]
arms = []
for r in rows:
    if r["tag"] not in arms: arms.append(r["tag"])
cols = ["throughput", "p50", "p95", "p99", "cold_pct", "to1_pct", "to2_pct", "cov", "fail_pct"]
print("arm n " + " ".join(cols))
for a in arms:
    v = [r for r in rows if r["tag"] == a]
    out = []
    for c in cols:
        x = [float(r[c]) for r in v if r.get(c) not in (None, "")]
        out.append("%.2f+-%.2f" % (st.mean(x), st.stdev(x) if len(x) > 1 else 0) if x else "-")
    print(a, len(v), " ".join(out))
PY
}
for c in $N/final_paper8 $G/final_ibm8; do echo "######## $c"; means $c
  for pr in "l4-ord-least l7-pull" "l4-ord-least l7-pullord" "l7-pullord l7-pull" "l4-scan l7-pull" "l7-leastconn l7-pull" "l7-random l7-pull" "l7-chbl l7-pull" "l4-ord-bounded l4-ord-least"; do $P $c $pr $M; done; done
echo "######## rl1"; means $N/rl1
for pr in "l4-ord-least-r5s l7-pull-r5s" "l4-ord-least l7-pull" "l7-pullord l7-pull" "l4-ord-least l7-pullord" "l7-pull l7-pull-r5s" "l4-ord-least l4-ord-least-r5s"; do $P $N/rl1 $pr $M; done
for c in top1 bur3 top_9b skew3_9b; do echo "######## $c"; means $N/$c; for pr in "l4-ord-least l7-pull" "l7-pullord l7-pull" "l4-ord-least l7-pullord"; do $P $N/$c $pr $M; done; done
echo "######## open3_9b"; means $N/open3_9b
for pr in "l4-ord-least-o210 l7-pull-o210" "l7-pullord-o210 l7-pull-o210" "l4-ord-least-o210 l7-pullord-o210"; do $P $N/open3_9b $pr $M; done
SKIP=6 $P $N/open3_9b l7-pullord-o210 l7-pull-o210 $M
echo "######## rq3_ibm8"; means $N/rq3_ibm8
echo "######## conn3_ibm9"; means $N/conn3_ibm9; $P $N/conn3_ibm9 l4-x1 l7-pullord-ka $M; $P $N/conn3_ibm9 l4-ka l7-pullord-ka $M
echo "######## multi3_ibm10"; means $G/multi3_ibm10; SKIP=5 $P $G/multi3_ibm10 wr-s4 wr-s1 $M; $P $G/multi3_ibm10 c10-s1 c0-s1 $M
echo "######## agelimit_ibm9b"; means $N/agelimit_ibm9b
echo "######## loss4_ibm9"; means $N/loss4_ibm9
echo "######## final3 orig"; means results/l4/final3
