# Integrity of a campaign of matrix.sh or multi.sh, checked from the raw run directories before any
# outcome is looked at: one code version, every run present, the same seed per repetition, each arm
# running the configuration its arms file names, a clean end state and an unloaded client.
# Why: four times an arm silently ran another arm's settings (a knob left over from the run before);
# only counters that must differ between the arms show it.
# args: campaign_dir [reps]   exit code 1 on any failure; warnings do not fail
import csv, glob, json, os, re, sys

STRATEGY = {"weighted-random": 0, "p2c": 1, "jsq": 2, "ordered": 3}
FALLBACK = {"random": 0, "hashed": 1, "hashed2": 2, "least-loaded": 3, "bounded": 4}
DEFAULTS = {"max_conn_requests": 0, "scheduler_peers": "", "signal_refresh_ms": 0, "signal_coalesce_ms": 0,
            "close_when_busy": False, "signal_reports_warm": False}
OV = {"signal_refresh_ms": 1000, "signal_coalesce_ms": 10}

camp = sys.argv[1]
lines = [l.split(None, 4) for l in open(os.path.join(camp, "arms.txt")) if l.strip() and not l.startswith("#")]
multi = lines[0][1].isdigit()
arms = {l[0]: l for l in lines}
rows = {}
for r in csv.DictReader(open(os.path.join(camp, "runs.csv"))):
    rows[(r["tag"], int(r["rep"]))] = r
reps = int(sys.argv[2]) if len(sys.argv) > 2 else max(k for _, k in rows)
fails, warns = [], []


def fail(m):
    fails.append(m)


def nat_last(d):
    out = []
    for p in sorted(glob.glob(os.path.join(d, "sched*.log"))):
        last = None
        for l in open(p, errors="replace"):
            if "NAT:" in l:
                last = l
        if last:
            out.append(last)
    return out


def mpstat(path):
    v = [l.split() for l in open(path, errors="replace") if " all " in l and not l.startswith("Average")]
    return [(100 - float(f[-1]) - float(f[-4]), float(f[-4])) for f in v if len(f) >= 11]


prov, seeds = set(), {}
for tag, a in arms.items():
    for k in range(1, reps + 1):
        d = os.path.join(camp, "%s_r%d" % (tag, k))
        run = "%s_r%d" % (tag, k)
        r = rows.get((tag, k))
        if not r or not os.path.isdir(d):
            fail("%s: missing" % run)
            continue
        if float(r["requests"]) <= 0:
            fail("%s: void (no requests)" % run)
        armtxt = open(os.path.join(d, "arm.txt")).read()
        m = re.search(r"commit=(\S+) src=(\S+) (\S+) worker=(\S+)", armtxt)
        if not m:
            fail("%s: no provenance" % run)
        else:
            prov.add(m.group(0).replace("+dirty", ""))
            if m.group(2) != "clean":
                fail("%s: src not clean" % run)
        s = re.search(r"seed=(\d+)", armtxt)
        if s:
            seeds.setdefault(k, set()).add(s.group(1))

        start = open(os.path.join(d, "sched_start.txt"), errors="replace").read()
        if multi:
            kind, config, ns = "l4", a[2], int(a[1])
            if start.count("L4 %s UP" % config) != ns:
                fail("%s: %d schedulers up, expected %d" % (run, start.count("UP"), ns))
            peers = re.search(r'"scheduler_peers":"([^"]*)"', armtxt).group(1)
            ov = dict(OV, signal_coalesce_ms=int(a[3]), scheduler_peers=peers)
            portmode = True
        else:
            kind, config, ovs, env = a[1], a[2], a[3], (a[4].strip() if len(a) > 4 else "-")
            if ("%s %s UP" % (kind.upper(), config)) not in start:
                fail("%s: scheduler line '%s'" % (run, start.strip()[:60]))
            ov = OV if ovs == "-" else json.loads(ovs)
            portmode = "MODE=l4" in env
        want = dict(DEFAULTS, **ov)
        up = re.findall(r"UP (\{.*\})", open(os.path.join(d, "workers.txt"), errors="replace").read())
        if len(up) != 5:
            fail("%s: %d workers up" % (run, len(up)))
        for u in up:
            got = json.loads(u)
            if got != want:
                fail("%s: worker config %s, expected %s" % (run, got, want))
                break

        nats = nat_last(d)
        if kind == "l7":
            if nats:
                fail("%s: L7 arm has NAT lines" % run)
        else:
            if not nats:
                fail("%s: no NAT line" % run)
                continue
            sf = re.findall(r"strategy=(\d+) fallback=(\d+)", open(glob.glob(os.path.join(d, "sched*.log"))[0], errors="replace").read())
            st, fb = config.split("+")
            if not sf or sf[0] != (str(STRATEGY[st]), str(FALLBACK[fb])):
                fail("%s: strategy/fallback %s, expected %s+%s" % (run, sf[:1], st, fb))
            for n in nats:
                c = dict(re.findall(r"([a-z-]+)=(\d+)", n))
                wf = sum(int(x) for x in re.search(r"wflows=([\d ]+)", n).group(1).split())
                if portmode and int(c["by-addr"]) != 0:
                    fail("%s: port mode but by-addr=%s" % (run, c["by-addr"]))
                if not portmode and c["by-addr"] != c["forward"]:
                    fail("%s: address mode but by-addr %s != forward %s" % (run, c["by-addr"], c["forward"]))
                if int(c.get("left-home", 0)) > 0 and fb != "bounded":
                    warns.append("%s: left-home=%s without bounded fallback" % (run, c["left-home"]))
                if fb == "bounded" and int(c.get("left-home", 0)) == 0 and int(c["flows"]) > 1000:
                    fail("%s: bounded fallback but left-home=0" % run)
                if int(c["live"]) or wf or int(c["d-noport"]) or int(c["sig-full"]):
                    fail("%s: end state live=%s wflows=%d d-noport=%s sig-full=%s" % (run, c["live"], wf, c["d-noport"], c["sig-full"]))
                if int(c["flows"]) == 0:
                    fail("%s: no flows" % run)

        cl = os.path.join(d, "client.mpstat")
        if os.path.exists(cl):
            v = mpstat(cl)
            if not v:
                fail("%s: empty client.mpstat" % run)
            elif sum(x for x, _ in v) / len(v) >= 50 or max(x for x, _ in v) >= 80:
                fail("%s: client cpu mean %.1f max %.1f" % (run, sum(x for x, _ in v) / len(v), max(x for x, _ in v)))
        else:
            fail("%s: no client.mpstat" % run)
        for p in glob.glob(os.path.join(d, "mpstat*.log")):
            v = mpstat(p)
            if v and sum(y for _, y in v) / len(v) >= 3:
                warns.append("%s: scheduler steal %.1f" % (run, sum(y for _, y in v) / len(v)))
        for p in glob.glob(os.path.join(d, "worker-*.mpstat")):
            v = mpstat(p)
            if v and sum(y for _, y in v) / len(v) >= 5:
                warns.append("%s: worker steal %.1f (%s)" % (run, sum(y for _, y in v) / len(v), os.path.basename(p)))

if len(prov) != 1:
    fail("provenance differs between runs: %s" % sorted(prov))
for k, s in seeds.items():
    if len(s) != 1:
        fail("repetition %d: seeds %s" % (k, s))
pos = {}
for (tag, k), r in rows.items():
    pos.setdefault(tag, set()).add(r["pos"])
for w in warns:
    print("warn", w)
for f in fails:
    print("FAIL", f)
print("%s: %d arms x %d repetitions, provenance %s, positions per arm %s -> %s"
      % (os.path.basename(camp.rstrip("/\\")), len(arms), reps, sorted(prov)[:1],
         sorted({len(p) for p in pos.values()}), "FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
