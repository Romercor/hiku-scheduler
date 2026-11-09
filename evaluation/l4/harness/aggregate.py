# Aggregates the per-run JSON of parse_run.py plus each run's summary.json into per-arm tables.
# usage: aggregate.py <results_l4_dir> <out_dir_with_json>
#   env: CAMPS, ARMS (comma-separated), REPS (per campaign, 5), PAIR (armA,armB for the differences)
import csv, json, os, statistics, sys
from paired import tq

R, O = sys.argv[1], sys.argv[2]
CAMPS = os.environ.get("CAMPS", "final_azure,final_huawei,final_ibm").split(",")
ARMS = os.environ.get("ARMS", "l7-pull,l7-chbl,l7-leastconn,l7-random,l4-ord-bounded,l4-scan,l4-ord-least").split(",")
REPS = int(os.environ.get("REPS", "5"))
A, B = os.environ.get("PAIR", "l4-ord-least,l7-pull").split(",")
TYPES = ["chameleon", "dd", "float_operation", "gzip_compression", "json_dumps_loads", "linpack", "matmul", "pyaes"]

runs = {}   # (camp, arm, rep) -> metrics dict
val = dict(n=0, cold_ok=0, inv_ok=0, req_ok=0)
worst = dict(attr=1.0, chk=1.0, incr=1.0)
tot = dict(unmatched=0, ambiguous=0, inv=0, never=0, nots=0, dd=0, du=0, neg=0, create=0, destroy=0,
           destroying=0, coldinv=0)
for camp in CAMPS:
    rc = {(r["tag"], int(r["rep"])): r for r in csv.DictReader(open(os.path.join(R, camp, "runs.csv")))}
    for arm in ARMS:
        for rep in range(1, REPS + 1):
            p = os.path.join(O, "%s__%s_r%d.json" % (camp, arm, rep))
            if not os.path.exists(p):
                print("MISSING", p)
                continue
            w = json.load(open(p))
            s = json.load(open(os.path.join(R, camp, "%s_r%d" % (arm, rep), "summary.json")))["metrics"]
            c = w["counts"]
            row = rc[(arm, rep)]
            val["n"] += 1
            val["cold_ok"] += c.get("creating", 0) == int(row["cold_starts"]) == c.get("create_func", 0)
            val["inv_ok"] += c["invoke"] == int(row["invocations"])
            val["req_ok"] += s["http_reqs"]["count"] == int(row["requests"])
            worst["attr"] = min(worst["attr"], w["n_attr"] / w["n_inv"])
            worst["chk"] = min(worst["chk"], w["chk_ok"] / w["chk_n"])
            worst["incr"] = min(worst["incr"], w["incr_check_ok"] / w["incr_check_tot"])
            tot["unmatched"] += c.get("unmatched", 0); tot["ambiguous"] += c.get("ambiguous", 0)
            tot["inv"] += w["n_inv"]; tot["never"] += w["never_destroyed"]
            tot["nots"] += c.get("creating_nots", 0) + c.get("invoke_nots", 0)
            tot["dd"] += c.get("double_destroy", 0); tot["du"] += c.get("destroy_unknown", 0)
            tot["neg"] += w["neg_life"]; tot["create"] += c["create_func"]
            tot["destroy"] += c.get("destroy_func", 0); tot["destroying"] += c.get("destroying_line", 0)
            tot["coldinv"] += w["n_cold_inv"]
            m = {}
            for k in ("http_req_connecting", "http_req_blocked", "http_req_duration"):
                for q in ("avg", "med", "p(95)", "p(99)", "max", "min"):
                    m["%s.%s" % (k.replace("http_req_", ""), q)] = s[k][q]
            m["e2e.avg"] = s["http_req_duration"]["avg"] + s["http_req_blocked"]["avg"]
            m["e2e.avg_conn"] = s["http_req_duration"]["avg"] + s["http_req_connecting"]["avg"]
            m["e2e.p99_lo"] = s["http_req_duration"]["p(99)"] + s["http_req_blocked"]["min"]
            m["e2e.p98_hi"] = s["http_req_duration"]["p(99)"] + s["http_req_blocked"]["p(99)"]
            m["e2e.max_hi"] = s["http_req_duration"]["max"] + s["http_req_blocked"]["max"]
            m["reqs"] = s["http_reqs"]["count"]
            m["inst.sec"] = sum(w["inst_sec_stage"])
            m["inst.mean"] = sum(w["inst_sec_stage"]) / 300.0
            m["inst.peak"] = w["peak"]
            m["inst.life_med"] = w["life_med"]
            m["inst.life_mean"] = w["life_mean"]
            m["inst.maxN"] = w["max_instances_to"]
            m["inst.never"] = w["never_destroyed"]
            m["inst.sec_per_inv"] = sum(w["inst_sec_stage"]) / w["n_inv"]
            for i in range(3):
                st = w["stage"][i]
                m["s%d.inst_mean" % i] = w["inst_sec_stage"][i] / 100.0
                m["s%d.peak" % i] = w["peak_stage"][i]
                m["s%d.creations" % i] = w["creations_stage"][i]
                m["s%d.inv" % i] = st["n"]
                m["s%d.cold_pct" % i] = 100.0 * w["creations_stage"][i] / st["n"]
                for q in ("mean", "med", "p95", "p99"):
                    m["s%d.inv_%s" % (i, q)] = st[q]
                m["s%d.warm_mean" % i] = st["warm"]["mean"]
                m["s%d.warm_med" % i] = st["warm"]["med"]
                m["s%d.warm_p95" % i] = st["warm"]["p95"]
                m["s%d.cold_mean" % i] = st["coldst"]["mean"]
            for q in ("mean", "med", "p95", "p99", "max"):
                m["inv.%s" % q] = w["inv_all"][q]
                m["warm.%s" % q] = w["inv_warm"][q]
                m["cold.%s" % q] = w["inv_cold"][q]
            m["front.avg"] = s["http_req_duration"]["avg"] - w["inv_all"]["mean"]
            m["front.med"] = s["http_req_duration"]["med"] - w["inv_all"]["med"]
            m["front.p99"] = s["http_req_duration"]["p(99)"] - w["inv_all"]["p99"]
            for ty in TYPES:
                t = w["type"][ty]
                m["%s.n_share" % ty] = 100.0 * t["n"] / w["n_attr"]
                m["%s.mean" % ty] = t["mean"]; m["%s.med" % ty] = t["med"]; m["%s.p95" % ty] = t["p95"]
                m["%s.warm_med" % ty] = t["warm"]["med"]; m["%s.warm_mean" % ty] = t["warm"]["mean"]
                m["%s.warm_p95" % ty] = t["warm"]["p95"]
                m["%s.cold_mean" % ty] = t["coldst"]["mean"]
                m["%s.cold_pct" % ty] = 100.0 * t["cold_inv"] / t["n"]
                m["%s.contrib" % ty] = t["sum"] / w["n_attr"]     # ms of the overall mean owed to this type
            runs[(camp, arm, rep)] = m


def msd(v):
    mu = sum(v) / len(v)
    sd = (sum((x - mu) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0
    return mu, sd


def fmt(v, nd=1):
    mu, sd = msd(v)
    return "%.*f±%.*f" % (nd, mu, nd, sd)


def vals(arm, key, camp=None):
    return [runs[(c, arm, r)][key] for c in CAMPS if camp in (None, c) for r in range(1, REPS + 1)]


def paired(key, a=A, b=B, camp=None, nd=1):
    d = [x - y for x, y in zip(vals(a, key, camp), vals(b, key, camp))]
    mu, sd = msd(d)
    h = tq(0.975, len(d) - 1) * sd / len(d) ** 0.5
    pos = sum(1 for x in d if x > 0)
    return "%+.*f [%+.*f, %+.*f] (%d/%d>0)" % (nd, mu, nd, mu - h, nd, mu + h, pos, len(d))


def table(title, cols, nd=1, diff=True, percamp=False):
    print("\n### " + title)
    print("| arm | " + " | ".join(c[1] for c in cols) + " |")
    print("|---|" + "---:|" * len(cols))
    for arm in ARMS:
        print("| %s | " % arm + " | ".join(fmt(vals(arm, c[0]), c[2] if len(c) > 2 else nd) for c in cols) + " |")
    if diff:
        print("| **%s - %s, %d pairs** | " % (A, B, len(CAMPS) * REPS) + " | ".join(paired(c[0], nd=c[2] if len(c) > 2 else nd) for c in cols) + " |")
        if percamp:
            for camp in CAMPS:
                print("| %s %d pairs | " % (camp, REPS) + " | ".join(paired(c[0], camp=camp, nd=c[2] if len(c) > 2 else nd) for c in cols) + " |")


print("VALIDATION", val, worst, tot)

table("1a connect/blocked (ms)", [("connecting.avg", "conn avg", 3), ("connecting.p(95)", "conn p95", 3),
      ("connecting.p(99)", "conn p99", 3), ("connecting.max", "conn max", 1), ("blocked.avg", "blk avg", 3),
      ("blocked.p(95)", "blk p95", 3), ("blocked.p(99)", "blk p99", 3), ("blocked.max", "blk max", 1)], percamp=True)
table("1b end-to-end (ms)", [("duration.avg", "dur avg", 2), ("e2e.avg", "dur+blocked avg", 2),
      ("e2e.avg_conn", "dur+conn avg", 2), ("duration.med", "dur med", 2), ("e2e.p99_lo", "e2e p99 lower", 1),
      ("e2e.p98_hi", "e2e p98 upper", 1), ("e2e.max_hi", "e2e max upper", 0)], percamp=True)
table("2 tail (ms)", [("duration.p(95)", "p95", 1), ("duration.p(99)", "p99", 1), ("duration.max", "max", 0)], percamp=True)
print("max of max per arm:", {a: round(max(vals(a, "duration.max"))) for a in ARMS})
print("max conn per arm:", {a: round(max(vals(a, "connecting.max")), 1) for a in ARMS})
print("median of max per arm:", {a: round(statistics.median(vals(a, "duration.max"))) for a in ARMS})
table("3 instances", [("inst.sec", "inst-s", 0), ("inst.mean", "mean alive", 1), ("inst.peak", "peak", 1),
      ("s0.inst_mean", "alive 20VU", 1), ("s1.inst_mean", "alive 50VU", 1), ("s2.inst_mean", "alive 100VU", 1),
      ("s0.peak", "peak 20", 1), ("s1.peak", "peak 50", 1), ("s2.peak", "peak 100", 1),
      ("inst.life_med", "life med s", 2), ("inst.life_mean", "life mean s", 2), ("inst.maxN", "max to-N", 1),
      ("inst.sec_per_inv", "inst-s/inv", 3)], percamp=True)
table("3b creations per stage", [("s0.creations", "20VU", 0), ("s1.creations", "50VU", 0), ("s2.creations", "100VU", 0),
      ("s0.inv", "inv 20", 0), ("s1.inv", "inv 50", 0), ("s2.inv", "inv 100", 0)])
table("4a worker invoke overall (ms)", [("inv.mean", "mean", 2), ("inv.med", "med", 1), ("inv.p95", "p95", 1),
      ("inv.p99", "p99", 1), ("inv.max", "max", 0), ("warm.mean", "warm mean", 2), ("warm.med", "warm med", 1),
      ("warm.p95", "warm p95", 1), ("warm.p99", "warm p99", 1), ("cold.mean", "cold mean", 1), ("cold.med", "cold med", 1),
      ("cold.p95", "cold p95", 1)], percamp=True)
table("4b front of worker (k6 minus worker, ms)", [("front.avg", "avg dur - mean invoke", 3), ("front.med", "med - med", 2),
      ("front.p99", "p99 - p99", 2)], percamp=True)
for stat, nd in (("med", 1), ("p95", 1), ("mean", 2), ("warm_med", 1), ("warm_mean", 2), ("warm_p95", 1),
                 ("cold_mean", 1), ("cold_pct", 2), ("n_share", 2), ("contrib", 2)):
    table("4c per type: %s" % stat, [("%s.%s" % (ty, stat), ty[:8], nd) for ty in TYPES])
table("5a cold % per stage", [("s0.cold_pct", "20VU", 2), ("s1.cold_pct", "50VU", 2), ("s2.cold_pct", "100VU", 2)], percamp=True)
for q in ("mean", "med", "p95", "p99"):
    table("5b invoke %s per stage" % q, [("s%d.inv_%s" % (i, q), "%s" % v, 1) for i, v in enumerate(("20VU", "50VU", "100VU"))])
table("5c warm invoke per stage", [("s0.warm_mean", "mean 20", 1), ("s1.warm_mean", "mean 50", 1), ("s2.warm_mean", "mean 100", 1),
      ("s0.warm_med", "med 20", 1), ("s1.warm_med", "med 50", 1), ("s2.warm_med", "med 100", 1),
      ("s0.warm_p95", "p95 20", 1), ("s1.warm_p95", "p95 50", 1), ("s2.warm_p95", "p95 100", 1),
      ("s0.cold_mean", "cold mean 20", 1), ("s1.cold_mean", "cold mean 50", 1), ("s2.cold_mean", "cold mean 100", 1)])
