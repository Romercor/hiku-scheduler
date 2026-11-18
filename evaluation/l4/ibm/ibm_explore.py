# Overview of one week of the IBM Code Engine trace: apps, calls, time span, and the total rate per minute
# and per second, to find windows whose mean rate fits the OpenLambda test bed.
import pandas as pd, numpy as np, sys, time
t0 = time.time()
df = pd.read_pickle(sys.argv[1])
print("loaded", round(time.time() - t0), "s;", df.shape, list(df.columns))
print(df.head(3).to_string()[:1500])
df["n"] = df["InvocationTimes"].map(len)
print("rows", len(df), "apps", df["AppHash"].nunique(), "namespaces", df["NamespaceHash"].nunique(), "calls", df["n"].sum())
ts = np.concatenate(df["InvocationTimes"].map(np.asarray).values)
print("time span", ts.min(), ts.max(), (ts.max() - ts.min()) / 3600, "h")
per_app = df.groupby("AppHash")["n"].sum().sort_values(ascending=False)
tot = per_app.sum()
print("top apps share:", {k: round(per_app.iloc[:k].sum() / tot, 3) for k in (1, 5, 10, 40, 100)})
sec = np.bincount((ts - ts.min()).astype(np.int64))
mins = sec[: len(sec) // 60 * 60].reshape(-1, 60).sum(1) / 60
print("all apps: mean %.1f calls/s, per-minute mean p5/p50/p95/max %s" % (sec.mean(), np.percentile(mins, [5, 50, 95, 100]).round(1)))
np.save("sec_all.npy", sec)
df[["AppHash", "n"]].to_pickle("apps_n.pkl")
