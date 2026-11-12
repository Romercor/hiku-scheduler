# The client's CPU over campaigns: per run its busy share (100 - idle - steal) averaged over all
# samples and the highest single 5-s sample, and for the synthetic workers (pool campaigns, which have
# params.txt) the average over the fully loaded samples (first and last dropped). Grouped by worker
# type, connection policy (noka=1 in params.txt or NOKA=1 in arm.txt) and scheduler layer.
# Why: the thesis rules out the client as a bottleneck except for Hiku with one connection per call.
# args: <campaign_dir> ...
import glob, os, re, statistics as st, sys


def busy(path):
    v = [100 - float(p[-1]) - float(p[9]) for p in (l.split() for l in open(path)) if len(p) >= 12 and p[2] == "all"]
    return v


groups = {}
for camp in sys.argv[1:]:
    params = os.path.join(camp, "params.txt")
    pool = os.path.exists(params)
    noka_camp = pool and "noka=1" in open(params).read()
    for d in glob.glob(os.path.join(camp, "*_r*")):
        f = os.path.join(d, "client.mpstat")
        if not os.path.exists(f) or not busy(f):
            continue
        v, arm = busy(f), open(os.path.join(d, "arm.txt")).read()
        layer = arm.split()[1]
        noka = noka_camp or (not pool and "NOKA=1" in arm)
        key = ("synthetic" if pool else "OpenLambda", "one per call" if noka else "kept open", layer)
        full = st.mean(v[1:-1]) if pool and len(v) > 2 else st.mean(v)
        groups.setdefault(key, []).append((full, max(v), os.path.basename(camp)))
for key in sorted(groups):
    g = groups[key]
    print("%-10s %-12s %-3s runs %3d  mean per run %.0f-%.0f %%, highest sample %.0f %% (%s)" % (
        key + (len(g), min(x[0] for x in g), max(x[0] for x in g), max(x[1] for x in g),
        max(g, key=lambda x: x[1])[2])))
