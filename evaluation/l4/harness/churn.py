# Splits cold starts by cause, per 100 invocations: "to 1" is a function's first instance on a
# worker, "to 2+" an extra instance because the existing one was busy.
# Why: the total hides which one a policy changes; keeping a function on few workers cuts the first
# kind but can add the second.
# args: campaign_dir
import glob, os, re, sys

out = sys.argv[1]
order = [l.split()[0] for l in open(os.path.join(out, "arms.txt")) if l.strip() and not l.startswith("#")]
runs = {}
for d in sorted(glob.glob(os.path.join(out, "*_r[0-9]*"))):
    tag, rep = os.path.basename(d).rsplit("_r", 1)
    one = more = inv = 0
    for path in glob.glob(os.path.join(d, "worker-*.log")):
        for line in open(path, errors="replace"):
            m = re.search(r"increase instances to (\d+)", line)
            if m:
                one, more = one + (m.group(1) == "1"), more + (m.group(1) != "1")
            elif "LambdaFunc.Invoke" in line:
                inv += 1
    if inv:
        runs.setdefault(tag, []).append((int(rep), 100.0 * one / inv, 100.0 * more / inv))


def ms(v):
    mu = sum(v) / len(v)
    sd = (sum((x - mu) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0
    return "%.2f+-%.2f" % (mu, sd)


print("| arm | n | to 1 % | to 2+ % | to 2+ % per repetition |")
print("|---|---:|---:|---:|---|")
for tag in order + sorted(set(runs) - set(order)):
    r = sorted(runs.get(tag, []))
    if r:
        print("| %s | %d | %s | %s | %s |" % (tag, len(r), ms([x[1] for x in r]), ms([x[2] for x in r]),
                                             " / ".join("%.2f" % x[2] for x in r)))
