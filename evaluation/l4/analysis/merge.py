# Merged campaigns for the analysis: a repetition re-run on a later cluster replaces that repetition
# (all arms of the repetition together, so pairs stay within one cluster). Run dirs are symlinked.
import csv, os
R, M = "results/l4", "results/merged"
SUB = {"final_ibm8": ("final_ibm8_r2", "2"), "multi3_ibm10": ("multi3_ibm10_r4", "4")}
for camp, (fix, rep) in SUB.items():
    out = os.path.join(M, camp); os.makedirs(out, exist_ok=True)
    rows, hdr = [], None
    for src, keep in ((camp, lambda r: r["rep"] != rep), (fix, lambda r: r["rep"] == rep)):
        rd = csv.DictReader(open(os.path.join(R, src, "runs.csv")))
        hdr = hdr or rd.fieldnames
        for r in rd:
            if keep(r):
                rows.append(r)
                ln = os.path.join(out, "%s_r%s" % (r["tag"], r["rep"]))
                if os.path.islink(ln): os.remove(ln)
                os.symlink(os.path.abspath(os.path.join(R, src, "%s_r%s" % (r["tag"], r["rep"]))), ln)
    for f in ("arms.txt",):
        if os.path.exists(os.path.join(R, camp, f)) and not os.path.exists(os.path.join(out, f)):
            os.symlink(os.path.abspath(os.path.join(R, camp, f)), os.path.join(out, f))
    w = csv.DictWriter(open(os.path.join(out, "runs.csv"), "w", newline=""), fieldnames=hdr, extrasaction="ignore")
    w.writeheader(); w.writerows(sorted(rows, key=lambda r: (int(r["rep"]), int(r["pos"]))))
    reps = {}
    for r in rows: reps.setdefault(r["tag"], set()).add(r["rep"])
    print(camp, len(rows), "rows;", {t: len(v) for t, v in reps.items()})
