# Parses one run directory's worker logs into per-run metrics (JSON). Read-only on the run dir.
# usage: parse_run.py <run_dir> <out_json>   |   parse_run.py --all <results_l4_dir> <out_dir>
#   env for --all: CAMPS (comma-separated campaigns, final_azure,final_huawei,final_ibm)
import glob, json, os, re, sys
from collections import deque, defaultdict

TS = re.compile(r"(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{6}) ")
SPLIT = re.compile(r"(?=\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{6} )")
CREATE = re.compile(r"/worker/code/\d+-([A-Za-z_]+)-(\d+), .*\)=(\d+)\.\.\.")
SBID = re.compile(r"SB (\d+)")
NUM = re.compile(r"=(\d+) ms")
INST = re.compile(r"(increase|reduce) instances to (\d+) \[FUNC ([A-Za-z_]+-\d+)\]")
WIN = 0.005


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def parse_worker(path):
    sb_func, sb_ready, sb_create, sb_destroy, sb_start = {}, {}, {}, {}, {}
    pauses = deque()
    busy = set()
    inv = []                     # (t_done, ms, func, cold, check)  check: 1 ok, 0 bad, None n/a
    cnt = defaultdict(int)
    incr = []                    # (t, kind, N, func)
    first = None
    for raw in open(path, errors="replace"):
        for seg in SPLIT.split(raw):
            m = TS.match(seg)
            if not m:
                if "Creating new sandbox" in seg:
                    cnt["creating_nots"] += 1
                if "LambdaFunc.Invoke" in seg:
                    cnt["invoke_nots"] += 1
                continue
            if "MEM POOL" in seg:
                continue
            g = m.groups()
            t = int(g[2]) * 86400 + int(g[3]) * 3600 + int(g[4]) * 60 + int(g[5]) + int(g[6]) / 1e6
            if "Installing `" in seg and first is None:
                first = t
            if "Pause() [SB" in seg and "Unpause" not in seg:
                sb = int(SBID.search(seg).group(1))
                pauses.append([t, sb, False])
                busy.discard(sb)
                cnt["pause"] += 1
            elif "Unpause() [SB" in seg:
                sb = int(SBID.search(seg).group(1))
                sb_start[sb] = (t, False)
                busy.add(sb)
            elif "LambdaFunc.Invoke=" in seg:
                cnt["invoke"] += 1
                y = int(NUM.search(seg).group(1))
                while pauses and pauses[0][0] < t - 1.0:
                    pauses.popleft()
                best = None
                cands = [p for p in pauses if not p[2] and p[0] >= t - WIN]
                types = set()
                for p in cands:
                    st = sb_start.get(p[1])
                    if st is None:
                        sc = 1e6
                    elif st[1]:
                        sc = 0.0 if y + 1.5 >= (t - st[0]) * 1000 else 1e3
                    else:
                        sc = abs((t - st[0]) * 1000 - y)
                    types.add(sb_func.get(p[1], ("?", 0))[0])
                    if best is None or sc <= best[0]:
                        best = (sc, p)
                if best is None:
                    cnt["unmatched"] += 1
                    inv.append((t, y, None, None, None))
                    continue
                if len(types) > 1:
                    cnt["ambiguous"] += 1
                p = best[1]
                p[2] = True
                sb = p[1]
                st = sb_start.get(sb)
                cold = bool(st and st[1])
                if st is None:
                    chk = None
                elif cold:
                    chk = 1 if y + 1.5 >= (t - st[0]) * 1000 else 0
                else:
                    chk = 1 if abs((t - st[0]) * 1000 - y) <= 2.0 else 0
                inv.append((t, y, sb_func.get(sb), cold, chk))
            elif ".Create(" in seg:
                c = CREATE.search(seg)
                if c:
                    sb = int(c.group(3))
                    sb_func[sb] = (c.group(1), int(c.group(2)))
                    sb_create[sb] = t
                    cnt["create_func"] += 1
                else:
                    cnt["create_other"] += 1
            elif "...returns <SB" in seg:
                sb = int(SBID.search(seg).group(1))
                sb_ready[sb] = t
                sb_start[sb] = (sb_create.get(sb, t), True)
                busy.add(sb)
            elif "Destroy() [SB" in seg:
                sb = int(SBID.search(seg).group(1))
                if sb in sb_destroy:
                    cnt["double_destroy"] += 1
                if sb not in sb_create and sb not in sb_ready:
                    cnt["destroy_unknown"] += 1
                if sb in sb_func:
                    cnt["destroy_func"] += 1
                sb_destroy[sb] = t
                cnt["destroy"] += 1
                if sb in busy:          # killed straight after serving: no Pause line, this is the anchor
                    pauses.append([t, sb, False])
                    busy.discard(sb)
                    cnt["destroy_busy"] += 1
            else:
                if "Creating new sandbox" in seg:
                    cnt["creating"] += 1
                if "Destroying sandbox:" in seg:
                    cnt["destroying_line"] += 1
                im = INST.search(seg)
                if im:
                    incr.append((t, im.group(1), int(im.group(2)), im.group(3)))
    return dict(sb_func=sb_func, sb_ready=sb_ready, sb_create=sb_create, sb_destroy=sb_destroy,
                inv=inv, cnt=cnt, incr=incr, first=first)


def parse_run(d):
    ws = [parse_worker(p) for p in sorted(glob.glob(os.path.join(d, "worker-*.log")))]
    t0 = min(w["first"] for w in ws if w["first"] is not None)
    T = 300.0
    cnt = defaultdict(int)
    for w in ws:
        for k, v in w["cnt"].items():
            cnt[k] += v
    # instances: interval [create, destroy) for function sandboxes; undestroyed live to end of window
    edges, isec, isec_ready = [], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    creations = [0, 0, 0]
    lifet = []
    never_destroyed = neg = 0
    for w in ws:
        for sb, f in w["sb_func"].items():
            a = w["sb_create"][sb] - t0
            r = w["sb_ready"].get(sb, w["sb_create"][sb]) - t0
            if sb in w["sb_destroy"]:
                b = w["sb_destroy"][sb] - t0
                lifet.append(b - a)
                if b < a:
                    neg += 1
            else:
                b = T
                never_destroyed += 1
            creations[min(2, max(0, int(a // 100)))] += 1
            a2, b2, r2 = max(0.0, a), min(T, b), max(0.0, min(T, r))
            if b2 > a2:
                edges.append((a2, 1))
                edges.append((b2, -1))
                for s in range(3):
                    lo, hi = s * 100.0, (s + 1) * 100.0
                    isec[s] += max(0.0, min(b2, hi) - max(a2, lo))
                    isec_ready[s] += max(0.0, min(b2, hi) - max(r2, lo))
    edges.sort(key=lambda e: (e[0], e[1]))
    cur, peak, peaks = 0, 0, [0, 0, 0]
    for t, dlt in edges:
        cur += dlt
        s = min(2, int(t // 100))
        peak = max(peak, cur)
        peaks[s] = max(peaks[s], cur)
    # check "increase instances to N" against the reconstruction
    ok = tot = 0
    max_n = 0
    one = more = 0
    for w in ws:
        byf = defaultdict(list)
        for sb, f in w["sb_func"].items():
            byf["%s-%d" % f].append((w["sb_create"][sb], w["sb_destroy"].get(sb, 1e18)))
        for t, kind, n, f in w["incr"]:
            if kind != "increase":
                continue
            max_n = max(max_n, n)
            one += n == 1
            more += n != 1
            # alive just before, not counting those killed within 100 ms after (re-install kill)
            alive = sum(1 for a, b in byf[f] if a < t and b > t + 0.1)
            tot += 1
            ok += (alive == n - 1)
    # invocations
    inv = [(t - t0, y, f, c, k) for w in ws for (t, y, f, c, k) in w["inv"]]
    att = [x for x in inv if x[2] is not None]
    chk = [x[4] for x in att if x[4] is not None]
    res = dict(dir=d, t0=t0, counts=dict(cnt), creations_stage=creations, inst_sec_stage=isec,
               inst_sec_ready_stage=isec_ready, peak=peak, peak_stage=peaks,
               never_destroyed=never_destroyed, neg_life=neg,
               life_med=pct(lifet, 50), life_p95=pct(lifet, 95),
               life_mean=sum(lifet) / len(lifet) if lifet else None,
               incr_check_ok=ok, incr_check_tot=tot, max_instances_to=max_n, to1=one, to2=more,
               n_inv=len(inv), n_attr=len(att), chk_ok=sum(chk), chk_n=len(chk),
               n_cold_inv=sum(1 for x in att if x[3]),
               last_inv=max(x[0] for x in inv))

    def stats(v):
        return dict(n=len(v), mean=sum(v) / len(v) if v else None, med=pct(v, 50), p90=pct(v, 90),
                    p95=pct(v, 95), p99=pct(v, 99), max=max(v) if v else None, sum=sum(v))
    res["inv_all"] = stats([x[1] for x in inv])
    res["inv_warm"] = stats([x[1] for x in att if not x[3]])
    res["inv_cold"] = stats([x[1] for x in att if x[3]])
    res["stage"] = []
    for s in range(3):
        sel = [x for x in inv if min(2, int(x[0] // 100)) == s]
        st = stats([x[1] for x in sel])
        st["warm"] = stats([x[1] for x in sel if x[2] is not None and not x[3]])
        st["coldst"] = stats([x[1] for x in sel if x[3]])
        st["cold_inv"] = sum(1 for x in sel if x[3])
        res["stage"].append(st)
    res["type"] = {}
    for ty in sorted({x[2][0] for x in att}):
        sel = [x for x in att if x[2][0] == ty]
        st = stats([x[1] for x in sel])
        st["warm"] = stats([x[1] for x in sel if not x[3]])
        st["coldst"] = stats([x[1] for x in sel if x[3]])
        st["cold_inv"] = sum(1 for x in sel if x[3])
        res["type"][ty] = st
    return res


def job(a):
    d, o = a
    if not os.path.exists(o):
        json.dump(parse_run(d), open(o, "w"))
    return o


if __name__ == "__main__":
    if sys.argv[1] == "--all":
        from multiprocessing import Pool
        jobs = []
        for camp in os.environ.get("CAMPS", "final_azure,final_huawei,final_ibm").split(","):
            for d in sorted(glob.glob(os.path.join(sys.argv[2], camp, "*_r[0-9]*"))):
                jobs.append((d, os.path.join(sys.argv[3], camp + "__" + os.path.basename(d) + ".json")))
        with Pool(6) as p:
            for o in p.imap_unordered(job, jobs):
                print(o, flush=True)
    else:
        r = parse_run(sys.argv[1])
        json.dump(r, open(sys.argv[2], "w"))
        print(json.dumps({k: v for k, v in r.items() if k not in ("type",)}, indent=1))
