# Mean and sample deviation per arm over a campaign's runs.csv, in the order of the arms file.
# Why: one table per campaign; a run with no requests (skipped or failed) is listed, not averaged,
# so it cannot pull the mean down.
# args: campaign_dir
import csv, os, sys

out = sys.argv[1]
rows = [r for r in csv.DictReader(open(os.path.join(out, "runs.csv")))]
order = [l.split()[0] for l in open(os.path.join(out, "arms.txt")) if l.strip() and not l.startswith("#")]
cols = [("throughput", "thrupt/s", 1), ("p50", "p50 ms", 1), ("p95", "p95 ms", 0), ("p99", "p99 ms", 0),
        ("cold_pct", "cold %", 1), ("cov", "CoV", 3), ("fail_pct", "fail %", 2), ("sched_cpu", "cpu %", 2),
        ("conn_max", "conn max ms", 0)]


def ms(v, nd):
    mu = sum(v) / len(v)
    sd = (sum((x - mu) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0
    return "%.*f+-%.*f" % (nd, mu, nd, sd)


print("| arm | n | " + " | ".join(c[1] for c in cols) + " | pick found no slot |")
print("|---|---:|" + "---:|" * (len(cols) + 1))
for tag in order + sorted({r["tag"] for r in rows} - set(order)):
    rs = [r for r in rows if r["tag"] == tag and float(r["requests"]) > 0]
    bad = sum(1 for r in rows if r["tag"] == tag) - len(rs)
    if not rs:
        continue
    miss = [100.0 * float(r["no_free"]) / float(r["flows"]) for r in rs if r["flows"] and float(r["flows"]) > 0]
    print("| %s | %d%s | %s | %s |" % (tag, len(rs), " (+%d void)" % bad if bad else "",
          " | ".join(ms([float(r[c[0]]) for r in rs], c[2]) for c in cols), ms(miss, 1) + " %" if miss else "-"))
