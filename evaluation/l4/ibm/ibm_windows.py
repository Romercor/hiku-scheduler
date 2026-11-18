# 15-minute windows of the 40 busiest apps of one IBM week: mean rate, burstiness per second, skew, active apps.
import pandas as pd, numpy as np, sys
W = int(sys.argv[2]) if len(sys.argv) > 2 else 900
df = pd.read_pickle(sys.argv[1])
df["n"] = df["InvocationTimes"].map(len)
g = df.groupby("AppHash")
tot = g["n"].sum().sort_values(ascending=False)
top = list(tot.index[:40])
t0 = min(min(x) for x in df["InvocationTimes"])
T = int(max(max(x) for x in df["InvocationTimes"]) - t0) + 1
per = np.zeros((40, T), np.int32)
for i, a in enumerate(top):
    ts = np.concatenate([np.asarray(x) for x in df.loc[df["AppHash"] == a, "InvocationTimes"]])
    per[i] = np.bincount((ts - t0).astype(np.int64), minlength=T)[:T]
np.save("per_top40.npy", per)
s = per.sum(0)
rows = []
for st in range(0, T - W, 300):
    w = per[:, st:st + W]
    tot_w = w.sum(1)
    sec = w.sum(0)
    srt = np.sort(tot_w)[::-1]
    rows.append(dict(start_h=st / 3600, mean=sec.mean(), cv=sec.std() / sec.mean(), p99=np.percentile(sec, 99) / sec.mean(),
                     max=sec.max() / sec.mean(), top1=srt[0] / srt.sum(), top5=srt[:5].sum() / srt.sum(), active=(tot_w > 0).sum(),
                     step10=np.percentile(np.abs(np.diff(sec.reshape(-1, 10).sum(1))), 95) / (10 * sec.mean())))
r = pd.DataFrame(rows)
r.to_csv("windows.csv", index=False)
pd.set_option("display.width", 200)
print(r.describe(percentiles=[.1, .5, .9]).round(3).to_string())
med = r.median()
r["dist"] = ((r["cv"] - med["cv"]) / r["cv"].std()) ** 2 + ((r["p99"] - med["p99"]) / r["p99"].std()) ** 2 + ((r["top5"] - med["top5"]) / r["top5"].std()) ** 2
print("\nwindows closest to the median (cv, p99/mean, top5):")
print(r.sort_values("dist").head(8).round(3).to_string())
print("\nburstiest windows (p99/mean):")
print(r.sort_values("p99", ascending=False).head(5).round(3).to_string())
