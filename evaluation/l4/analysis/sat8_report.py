# n12 saturation retest: every attempt (kept and moved aside) with client and scheduler steal, dropped share,
# latency, connection p99 and k6 VUs; then per arm and rate, and steal-drop correlation below saturation.
import json, glob, os, statistics as st
def steal(p):
    c=None; s=[]
    if not os.path.exists(p): return float("nan")
    for l in open(p, errors="replace"):
        f=l.split()
        if "%steal" in f: c=f.index("%steal")
        elif c and " all " in l and not l.startswith("Average") and len(f) > c: s.append(float(f[c]))
    return sum(s)/len(s) if s else float("nan")
R="results/l4/"
rows=[]
for d in sorted(glob.glob(R+"sat8_[0-9]*/*_r*")+glob.glob(R+"sat8_stolen/*/*")):
    if not os.path.exists(d+"/summary.json"): print("no summary:", d); continue
    m=json.load(open(d+"/summary.json"))["metrics"]
    reqs=m["http_reqs"]["count"]; dr=m.get("dropped_iterations",{}).get("count",0)
    rate=int(d.split("sat8_")[-1].split("/")[0]); name=d.split("/")[-1]
    arm=name.rsplit("_r",1)[0]; kept="stolen" not in d
    rows.append(dict(rate=rate, arm=arm, name=name, kept=kept, cst=steal(d+"/client.mpstat"), sst=steal(d+"/mpstat.log"),
        reqs=reqs, drop=100*dr/(reqs+dr), c99=m["http_req_connecting"]["p(99)"], p99=m["http_req_duration"]["p(99)"],
        vus=m.get("vus_max",{}).get("max", m.get("vus_max",{}).get("value",0)), fail=100*m["http_req_failed"]["value"]))
print("%-6s %-20s %-6s %6s %6s %7s %8s %8s %6s" % ("rate","run","kept","cSteal","sSteal","drop%","p99ms","conn99","VUs"))
for r in sorted(rows, key=lambda r:(r["arm"],r["rate"],r["name"])):
    print("%-6d %-20s %-6s %6.1f %6.1f %7.2f %8.1f %8.1f %6d" % (r["rate"],r["name"],"kept" if r["kept"] else "aside",r["cst"],r["sst"],r["drop"],r["p99"],r["c99"],r["vus"]))
print("\nPer arm and rate, all attempts: n | drop% median [min,max] | p99 median | runs with VUs at max | low-steal (<10) drop% max")
for (a,rt) in sorted({(r["arm"],r["rate"]) for r in rows}):
    rs=[r for r in rows if r["arm"]==a and r["rate"]==rt]; lo=[r for r in rs if r["cst"]<10]
    print("%-13s %6d | n=%2d drop %5.1f [%5.1f,%5.1f] | p99 %7.0f | VUs-max %d | low-steal n=%d drop max %s p99 max %s" % (a,rt,len(rs),
        st.median(r["drop"] for r in rs),min(r["drop"] for r in rs),max(r["drop"] for r in rs),st.median(r["p99"] for r in rs),
        sum(r["vus"]>=9000 for r in rs),len(lo),"%.1f"%max(r["drop"] for r in lo) if lo else "-","%.0f"%max(r["p99"] for r in lo) if lo else "-"))
def corr(xs,ys):
    mx,my=st.mean(xs),st.mean(ys); n=sum((a-mx)*(b-my) for a,b in zip(xs,ys)); d=(sum((a-mx)**2 for a in xs)*sum((b-my)**2 for b in ys))**.5
    return n/d if d else float("nan")
print("\nSteal-drop correlation where the arm is not saturated (L4 8-24k, Hiku one-conn 8k, Hiku kept-open 12k):")
for a,rates in [("l4-ord-least",(8000,16000,24000)),("l7-pull",(8000,)),("l7-pull-ka",(12000,))]:
    rs=[r for r in rows if r["arm"]==a and r["rate"] in rates]
    print("  %-13s n=%2d corr(client steal, drop)=%.2f; steal<10: drop median %.1f; steal>=10: drop median %.1f" % (a,len(rs),corr([r["cst"] for r in rs],[r["drop"] for r in rs]),
        st.median([r["drop"] for r in rs if r["cst"]<10] or [float("nan")]),st.median([r["drop"] for r in rs if r["cst"]>=10] or [float("nan")])))
print("\nL4 32k all attempts by steal:"); [print("  steal %4.1f drop %5.1f p99 %6.0f VUs %5d" % (r["cst"],r["drop"],r["p99"],r["vus"])) for r in sorted([r for r in rows if r["rate"]==32000],key=lambda r:r["cst"])]
print("\nclient steal over all attempts: median %.1f, min %.1f, max %.1f; scheduler steal median %.1f max %.1f" % (st.median(r["cst"] for r in rows),min(r["cst"] for r in rows),max(r["cst"] for r in rows),st.median(r["sst"] for r in rows),max(r["sst"] for r in rows)))
print("\nDelivered (k6 rate) per arm and rate: all attempts min-max | steal<10 attempts min-max | attempts with p99 > 1 s | VUs >= 9000 | kept-only drop median")
for d in sorted(glob.glob(R+"sat8_[0-9]*/*_r*")+glob.glob(R+"sat8_stolen/*/*")):
    if not os.path.exists(d+"/summary.json"): continue
    name=d.split("/")[-1]; rate=int(d.split("sat8_")[-1].split("/")[0])
    for r in rows:
        if r["name"]==name and r["rate"]==rate: r["thr"]=json.load(open(d+"/summary.json"))["metrics"]["http_reqs"]["rate"]
for (a,rt) in sorted({(r["arm"],r["rate"]) for r in rows}):
    rs=[r for r in rows if r["arm"]==a and r["rate"]==rt]; lo=[r for r in rs if r["cst"]<10]; kp=[r for r in rs if r["kept"]]
    f=lambda xs: "%6.0f-%6.0f" % (min(xs),max(xs)) if xs else "      -      "
    print("%-13s %6d | %s | %s | p99>1s %d/%d | VUs-max %d | kept n=%d drop med %.1f steal med %.1f" % (a,rt,f([r["thr"] for r in rs]),f([r["thr"] for r in lo]),sum(r["p99"]>1000 for r in rs),len(rs),sum(r["vus"]>=9000 for r in rs),len(kp),st.median(r["drop"] for r in kp),st.median(r["cst"] for r in kp)))
lo=[r for r in rows if r["arm"]=="l4-ord-least" and r["rate"]<=24000 and r["cst"]<10]
print("\nL4 8-24k steal<10: n=%d drop max %.1f p99 max %.0f conn p99 max %.0f VUs max %d" % (len(lo),max(r["drop"] for r in lo),max(r["p99"] for r in lo),max(r["c99"] for r in lo),max(r["vus"] for r in lo)))
al=[r for r in rows if r["arm"]=="l4-ord-least" and r["rate"]<=24000]
print("L4 8-24k all: n=%d p99>1s %d, VUs max %d" % (len(al),sum(r["p99"]>1000 for r in al),max(r["vus"] for r in al)))
print("\nTABLE rows: arm rate n | steal med [min,max] | drop med steal<10 (n) | drop med steal>=10 (n) | p99 med | at limit")
for a in ["l4-ord-least","l7-pull","l7-pull-ka"]:
    for rt in sorted({r["rate"] for r in rows if r["arm"]==a}):
        rs=[r for r in rows if r["arm"]==a and r["rate"]==rt]; lo=[r["drop"] for r in rs if r["cst"]<10]; hi=[r["drop"] for r in rs if r["cst"]>=10]
        md=lambda xs: "%.1f (%d)" % (st.median(xs),len(xs)) if xs else "- (0)"
        print("%s %d %d | %.0f [%.0f,%.0f] | %s | %s | %.0f | %d" % (a,rt,len(rs),st.median(r["cst"] for r in rs),min(r["cst"] for r in rs),max(r["cst"] for r in rs),md(lo),md(hi),st.median(r["p99"] for r in rs),sum(r["p99"]>1000 for r in rs)))
print("\nSCATTER below limit (arm steal drop):")
for a,rates in [("l4-ord-least",(8000,16000,24000)),("l7-pull",(8000,)),("l7-pull-ka",(12000,))]:
    print(a, " ".join("(%.1f,%.2f)" % (r["cst"],r["drop"]) for r in rows if r["arm"]==a and r["rate"] in rates))
