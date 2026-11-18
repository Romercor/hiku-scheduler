# Replay files for k6: per second, the calls of each of the 40 busiest apps of the week in a 10-minute window,
# at the original rate. Apps are ranked by their calls in the window and mapped to the deployed functions
# in that order (index 0 = most called), as TOP=1 does with the Azure file.
import json, numpy as np, os, sys
per = np.load("per_top40.npy")
W = int(os.environ.get("W", 600))
starts_h = [float(x) for x in sys.argv[1:]]
for k, h in enumerate(starts_h, 1):
    st = int(round(h * 3600))
    w = per[:, st:st + W]
    order = np.argsort(-w.sum(1), kind="stable")
    w = w[order]
    sec = w.sum(0)
    tot = w.sum(1)
    meta = dict(source="IBM Cloud Code Engine trace, week_10, top-40 apps of the week", start_s=st, seconds=W,
                calls=int(sec.sum()), mean=round(float(sec.mean()), 1), cv=round(float(sec.std() / sec.mean()), 3),
                p99_over_mean=round(float(np.percentile(sec, 99) / sec.mean()), 2), max_over_mean=round(float(sec.max() / sec.mean()), 2),
                top1=round(float(tot[0] / tot.sum()), 3), top5=round(float(tot[:5].sum() / tot.sum()), 3),
                active=int((tot > 0).sum()))
    json.dump(dict(meta=meta, total=[int(x) for x in sec], secs=[[int(x) for x in w[:, s]] for s in range(W)]),
              open("replay_ibm_%d.json" % k, "w"))
    print(k, meta)
