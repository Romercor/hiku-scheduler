# Whole path behind the nginx gateway (gw7): per rate, paired differences over the rounds of L4 minus Hiku in us per
# delivered call: totals with the scheduler's traced time and with its capacity estimate, then scheduler, client
# (k6 and nginx) and workers alone; mean with 95 % t-interval (last column of Table tab:path).
import glob,json,os,re,statistics as st,math
R='results/l4'
T={4:2.776}
def count(f): return sum(int(l.split()[2]) for l in open(f) if l.startswith('count'))
def traced(f):
    t=open(f).read(); s=sum(int(v) for v in re.findall(r'@soft\[\d+\]: (\d+)',t)); h=re.search(r'@hard: (\d+)',t)
    return (s+int(h.group(1) if h else 0))/1.2e9 if s else None
def busy(p):
    r=[l.split() for l in open(p,errors='replace') if len(l.split())>=12 and l.split()[2]=='all']; r=r[1:-1] if len(r)>2 else r
    return st.mean(100-float(x[-1])-float(x[9]) for x in r) if r else None
def rate(d): return json.load(open(d+'/summary.json'))['metrics']['http_reqs']['rate']
def comp(camp,arm,cond,r):
    out={}
    idle=[count(f) for f in glob.glob('%s/%s/idle_*_r%d.hog.txt'%(R,camp,r))]
    dh=glob.glob('%s/%s_%s_%s_hog/*_r%d'%(R,camp,arm,cond,r)); dt=glob.glob('%s/%s_%s_%s_trace/*_r%d'%(R,camp,arm,cond,r))
    if not dh or not dt: return None
    qh,qt=rate(dh[0]),rate(dt[0])
    out['cap']=(1-count('%s/%s/%s_%s_r%d.hog.txt'%(R,camp,arm,cond,r))/st.mean(idle))*4e6/qh
    t=traced('%s/%s/%s_%s_r%d.trace.txt'%(R,camp,arm,cond,r)); out['tr']=t/100*4e6/qt if t else None
    out['busy']=busy(dt[0]+'/mpstat.log')/100*4e6/qt
    cl=[busy(d+'/client.mpstat')/100*16e6/rate(d) for d in dh+dt]; out['cli']=st.mean(cl)
    wk=[sum(busy(d+'/worker-%d.nstat'%i) for i in range(1,6))/100*2e6/rate(d) for d in dh+dt]; out['wrk']=st.mean(wk)
    return out
def ci(x):
    m=st.mean(x); h=T.get(len(x)-1,2.0)*st.stdev(x)/math.sqrt(len(x)); return '%+.0f [%+.0f, %+.0f]'%(m,m-h,m+h)
for rt in [4000,8000,12000,16000]:
    dl_lo=[];dl_hi=[];dsch=[];dcli=[];dwrk=[]
    for r in range(1,6):
        a=comp('gw7','gwl4','gw_%d'%rt,r); b=comp('gw7','gwl7','gw_%d'%rt,r)
        if not a or not b or a['tr'] is None: continue
        L_lo=a['tr']+a['cli']+a['wrk']; L_hi=a['cap']+a['cli']+a['wrk']; H=b['busy']+b['cli']+b['wrk']
        dl_lo.append(L_lo-H); dl_hi.append(L_hi-H); dsch.append(a['tr']-b['busy']); dcli.append(a['cli']-b['cli']); dwrk.append(a['wrk']-b['wrk'])
    print(rt,'n=%d total(L4 traced)-Hiku %s | total(L4 cap)-Hiku %s | sched %s | gateway %s | workers %s'%(len(dl_lo),ci(dl_lo),ci(dl_hi),ci(dsch),ci(dcli),ci(dwrk)))
