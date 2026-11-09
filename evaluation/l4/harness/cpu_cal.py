# Scheduler CPU from the calibration rounds of cal.sh: Hiku's busy share while traced,
# the kernel scheduler's softirq + hard irq time (bpftrace, 30 s on 4 CPUs), and the capacity each
# takes from an idle-priority counter on every vCPU, against the idle runs of the same round.
# Why: mpstat does not see the kernel scheduler's work, so its cost needs these two measures.
# args: results_dir (results/l4) [calibration name, cal]
import glob, os, re, statistics as st, sys

res = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "cal"
cal = os.path.join(res, name)
conds = ["noka_3000", "ka_6000", "ka_12000"]


def busy(cond, col=None):
    out = {}
    for d in glob.glob(os.path.join(res, "%s_l7_%s_trace" % (name, cond), "*_r[0-9]")):
        rows = [l.split() for l in open(os.path.join(d, "mpstat.log")) if len(l.split()) >= 12 and l.split()[2] == "all"]
        out[int(d[-1])] = st.mean(float(p[col]) if col else 100 - float(p[-1]) - float(p[9]) for p in rows)
    return out


def traced(f):
    t = open(f).read()
    soft = sum(int(v) for v in re.findall(r"@soft\[\d+\]: (\d+)", t))
    return (soft + int(re.search(r"@hard: (\d+)", t).group(1))) / 1.2e9


def count(f):
    return sum(int(l.split()[2]) for l in open(f) if l.startswith("count"))


idle = {}
for f in glob.glob(os.path.join(cal, "idle_*_r*.hog.txt")):
    idle.setdefault(int(re.search(r"_r(\d)", f).group(1)), []).append(count(f))


def cap(arm, cond):
    return {int(re.search(r"_r(\d)", f).group(1)): 100 * (1 - count(f) / st.mean(idle[int(re.search(r"_r(\d)", f).group(1))]))
            for f in glob.glob(os.path.join(cal, "%s_%s_r*.hog.txt" % (arm, cond)))}


def rng(v):
    return "%.1f (%.1f-%.1f)" % (st.mean(v), min(v), max(v))


for cond in conds:
    l4t = {int(re.search(r"_r(\d)", f).group(1)): traced(f) for f in glob.glob(os.path.join(cal, "l4_%s_r*.trace.txt" % cond))}
    b = {r: v for r, v in busy(cond).items() if r in l4t}
    c4, c7 = cap("l4", cond), cap("l7", cond)
    both = [r for r in c4 if r in c7]
    print(cond)
    print("  L7 busy while traced  %s" % rng(list(b.values())))
    l7t = {int(re.search(r"_r(\d)", f).group(1)): traced(f) for f in glob.glob(os.path.join(cal, "l7_%s_r*.trace.txt" % cond))}
    soft = busy(cond, 8)
    print("  L7 sampled %%soft / traced soft+hard  %s" % ", ".join(
        "r%d %.2f/%.2f" % (r, soft[r], l7t[r]) for r in sorted(l7t) if r in soft))
    print("  L4 traced time        %s" % rng(list(l4t.values())))
    print("  time ratio L7/L4      %.2f-%.2f per round" % (min(b[r] / l4t[r] for r in b), max(b[r] / l4t[r] for r in b)))
    print("  capacity L7 / L4      %s / %s" % (rng(list(c7.values())), rng(list(c4.values()))))
    print("  capacity ratio        %.2f matched (rounds %s), %.2f all rounds" % (
        st.mean(c7[r] for r in both) / st.mean(c4[r] for r in both), ",".join(map(str, both)),
        st.mean(c7.values()) / st.mean(c4.values())))
