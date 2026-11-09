# front-of-worker time including connection setup, and validation ratios per arm
import json, os, sys
from paired import tq
R, O = sys.argv[1], sys.argv[2]
CAMPS = os.environ.get("CAMPS", "final_azure,final_huawei,final_ibm").split(",")
ARMS = os.environ.get("ARMS", "l7-pull,l7-chbl,l7-leastconn,l7-random,l4-ord-bounded,l4-scan,l4-ord-least").split(",")
REPS = int(os.environ.get("REPS", "5"))
A, B = os.environ.get("PAIR", "l4-ord-least,l7-pull").split(",")
v = {}
for a in ARMS:
    f, at, ck, ic, nd, dn = [], [], [], [], [], []
    for c in CAMPS:
        for r in range(1, REPS + 1):
            w = json.load(open(os.path.join(O, "%s__%s_r%d.json" % (c, a, r))))
            s = json.load(open(os.path.join(R, c, "%s_r%d" % (a, r), "summary.json")))["metrics"]
            f.append(s["http_req_duration"]["avg"] + s["http_req_blocked"]["avg"] - w["inv_all"]["mean"])
            at.append(w["n_attr"] / w["n_inv"]); ck.append(w["chk_ok"] / w["chk_n"])
            ic.append(w["incr_check_ok"] / w["incr_check_tot"]); nd.append(w["never_destroyed"])
            dn.append(s["http_reqs"]["count"] - w["n_inv"])
    v[a] = f
    n = len(f); mu = sum(f) / n; sd = (sum((x - mu) ** 2 for x in f) / (n - 1)) ** .5
    print("%-15s front+blocked %.3f+-%.3f | attr min %.4f mean %.4f | chk min %.4f | incr min %.4f mean %.4f | alive at end %.0f | k6reqs-inv %.1f"
          % (a, mu, sd, min(at), sum(at) / n, min(ck), min(ic), sum(ic) / n, sum(nd) / n, sum(dn) / n))
d = [x - y for x, y in zip(v[A], v[B])]
n = len(d); mu = sum(d) / n; sd = (sum((x - mu) ** 2 for x in d) / (n - 1)) ** .5; h = tq(0.975, n - 1) * sd / n ** .5
print("%s - %s front+blocked %+.3f [%+.3f, %+.3f] %d/%d>0" % (A, B, mu, mu - h, mu + h, sum(x > 0 for x in d), n))
