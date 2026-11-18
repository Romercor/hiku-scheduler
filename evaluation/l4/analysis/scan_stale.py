# rows whose workers saw no invocations, or whose k6 log has no progress lines (stale summary)
import csv, glob, os
for f in sorted(glob.glob('results/l4/*/runs.csv')):
    c = f.split('/')[-2]
    if not any(c.startswith(p) for p in ('sat7', 'lim7', 'cal7', 'pilot_ibm8', 'pilot_s8', 'final_ibm8', 'final_paper8', 'rq3_ibm8', 'ref_s8')):
        continue
    for x in csv.DictReader(open(f)):
        d = os.path.join(os.path.dirname(f), x['tag'] + '_r' + x['rep'])
        k6 = open(d + '/k6.log', errors='ignore').read() if os.path.exists(d + '/k6.log') else ''
        if x.get('invocations') in ('0', '') and 'l7' not in x['tag'] and 'ref' not in x['tag'] or 'running (' not in k6:
            print(c, x['tag'], x['rep'], 'inv', x.get('invocations'), 'k6log', len(k6))
