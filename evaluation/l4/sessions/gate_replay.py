# Replay pilot: prints the replay scale for the campaigns, 1 if no pilot run failed more than 1 % of its
# calls or dropped more than 1 % of its arrivals, else 0.75. A run without requests fails the gate.
import csv, json, glob, os, sys
d = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(d, "runs.csv"))))
worst = 0.0
for r in rows:
    if float(r["requests"] or 0) <= 0:
        sys.exit("REPLAY PILOT FAILED: %s_r%s has no requests" % (r["tag"], r["rep"]))
    m = json.load(open(os.path.join(d, "%s_r%s" % (r["tag"], r["rep"]), "summary.json")))["metrics"]
    drop = (m.get("dropped_iterations") or {}).get("count", 0)
    req = m["http_reqs"]["count"]
    worst = max(worst, float(r["fail_pct"]), 100.0 * drop / (req + drop))
    print("%s_r%s fail %s %% drop %.2f %% cold %s %% p99 %s" % (r["tag"], r["rep"], r["fail_pct"], 100.0 * drop / (req + drop), r["cold_pct"], r["p99"]), file=sys.stderr)
print(1 if worst <= 1.0 else 0.75)
