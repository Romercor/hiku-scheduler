# Workers' CPU in one stage of the load profile: per run the busy share of each worker, averaged over
# the mpstat samples that end between FROM and TO seconds after the first call any worker logged, and
# from it the busiest worker and the spread between the busiest and the least busy one. Paired
# differences between two arms as in paired.py.
# Why: the longer tail of the ordered strategy is consistent with CPU contention on the worker where a
# function's calls are concentrated; the 100-VU stage runs from 200 to 300 s.
# args: <campaign_dir> <armA> <armB> [from_s to_s] (default 205 300)
import glob, math, os, re, statistics as st, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paired import tq

camp, a, b = sys.argv[1:4]
lo, hi = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (205.0, 300.0)


def first_call(d):
    t = None
    for f in glob.glob(os.path.join(d, "worker-*.log")):
        for l in open(f, errors="replace"):
            if "LambdaFunc.Invoke" in l:
                v = datetime.strptime(l[:26], "%Y/%m/%d %H:%M:%S.%f")
                t = v if t is None or v < t else t
                break
    return t


def stage(d):
    t0, out = first_call(d), []
    for f in sorted(glob.glob(os.path.join(d, "worker-*.mpstat"))):
        day = re.search(r"(\d\d)/(\d\d)/(\d{4})", open(f).readline()).groups()
        v, prev = [], None
        for l in open(f):
            p = l.split()
            if len(p) >= 12 and p[2] == "all":
                t = datetime.strptime("%s/%s/%s %s%s" % (day[2], day[0], day[1], p[0], p[1]), "%Y/%m/%d %I:%M:%S%p")
                t += timedelta(days=1) if prev and t < prev - timedelta(hours=1) else timedelta(0)
                prev = t
                if lo <= (t - t0).total_seconds() <= hi:
                    v.append(100 - float(p[-1]) - float(p[9]))
        out.append(st.mean(v))
    return max(out), max(out) - min(out), st.mean(out)


def arm(tag):
    return {int(re.search(r"_r(\d+)$", d).group(1)): stage(d) for d in glob.glob(os.path.join(camp, tag + "_r*"))}


A, B = arm(a), arm(b)
ks = sorted(set(A) & set(B))
print("%s - %s, worker CPU %g-%g s after the first call (%d pairs)" % (a, b, lo, hi, len(ks)))
for i, name in enumerate(("busiest worker", "busiest - least busy", "mean over workers")):
    x = [A[k][i] - B[k][i] for k in ks]
    m, h = st.mean(x), tq(0.975, len(x) - 1) * st.stdev(x) / math.sqrt(len(x))
    same = sum(1 for v in x if (v > 0) == (m > 0))
    print("  %-22s %+6.1f pp [%+.1f, %+.1f]  same sign %d/%d" % (name, m, m - h, m + h, same, len(x)))
