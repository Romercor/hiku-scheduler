# Go/no-go for a session: the pilot (Hiku pull-based and the kernel scheduler's default, one
# repetition) must land in the bands of the final comparison of 2026-10-12, and a later reference
# run of Hiku pull-based must match the pilot's.
# Why: a slow host or a broken setup shows in these runs first; a session that fails here would
# spend hours measuring the cluster instead of the schedulers.
# args: pilot <campaign_dir> | ref <pilot_campaign_dir> <ref_campaign_dir>
import csv, glob, os, sys


def rows(d):
    return {r["tag"]: r for r in csv.DictReader(open(os.path.join(d, "runs.csv")))}


def client(d, tag):
    v = [100 - float(l.split()[-1]) - float(l.split()[-4]) for p in glob.glob(os.path.join(d, tag + "_r*", "client.mpstat"))
         for l in open(p) if " all " in l and not l.startswith("Average")]
    return (sum(v) / len(v), max(v)) if v else (None, None)


bad = []
if sys.argv[1] == "pilot":
    d = sys.argv[2]
    r = rows(d)
    p, l4 = r.get("l7-pull"), r.get("l4-ord-least")
    if not p or not l4:
        sys.exit("GATE FAILED: pilot runs missing")
    checks = [("l7-pull throughput >= 85", float(p["throughput"]) >= 85),
              ("l7-pull p95 <= 300 ms", float(p["p95"]) <= 300),
              ("l7-pull cold 16.0-19.0 %", 16.0 <= float(p["cold_pct"]) <= 19.0),
              ("l4 cold 12.0-15.0 %", 12.0 <= float(l4["cold_pct"]) <= 15.0),
              ("l4 no-free < 2 % of flows", float(l4["no_free"]) < 0.02 * float(l4["flows"])),
              ("failed calls < 0.1 %", max(float(p["fail_pct"]), float(l4["fail_pct"])) < 0.1)]
    for tag in ("l7-pull", "l4-ord-least"):
        m, x = client(d, tag)
        checks.append(("client cpu %s mean < 50 %% (%s)" % (tag, m), m is not None and m < 50))
else:
    p, q = rows(sys.argv[2])["l7-pull"], rows(sys.argv[3])["ref-pull"]
    checks = [("throughput within 3 %% (%s vs %s)" % (q["throughput"], p["throughput"]),
               abs(float(q["throughput"]) / float(p["throughput"]) - 1) <= 0.03),
              ("p95 within 15 %% (%s vs %s)" % (q["p95"], p["p95"]), abs(float(q["p95"]) / float(p["p95"]) - 1) <= 0.15),
              ("failed calls < 0.1 %", float(q["fail_pct"]) < 0.1)]
for name, ok in checks:
    print("%-4s %s" % ("ok" if ok else "FAIL", name))
sys.exit(0 if all(ok for _, ok in checks) else "GATE FAILED")
