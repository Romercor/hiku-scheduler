# Azure Functions 2021 invocation trace -> harness workload. Counts invocations per function
# (real popularity) and median execution duration, takes the top N functions, and emits the same
# files trace_gen.py does (<pref>.funcs name:port, <pref>.json name/port/weight) plus <pref>.dur
# (name warm_ms) for per-function durations. Durations capped at cap_ms for a small cluster.
# Trace: AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt (cols: app,func,end_timestamp,duration).
# args: trace_txt n_funcs [base_port cap_ms out_prefix]
import sys, json, collections, statistics
trace, n = sys.argv[1], int(sys.argv[2])
base = int(sys.argv[3]) if len(sys.argv) > 3 else 5100
cap = float(sys.argv[4]) if len(sys.argv) > 4 else 300.0
pref = sys.argv[5] if len(sys.argv) > 5 else 'azure'

cnt = collections.Counter()
durs = collections.defaultdict(list)
with open(trace) as f:
    next(f)
    for line in f:
        p = line.split(',')
        if len(p) != 4:
            continue
        fn = p[1]
        cnt[fn] += 1
        d = durs[fn]
        if len(d) < 3000:                 # bounded sample is enough for a stable median
            try:
                d.append(float(p[3]))
            except ValueError:
                pass

top = cnt.most_common(n)
tot = sum(c for _, c in top)
funcs = []
for i, (fn, c) in enumerate(top):
    med_ms = statistics.median(durs[fn]) * 1000 if durs[fn] else 10.0
    funcs.append({'name': 'fn%03d' % i, 'port': base + i, 'weight': c / tot,
                  'warm_ms': round(min(med_ms, cap), 1)})

open(pref + '.funcs', 'w').write('\n'.join('%s:%d' % (f['name'], f['port']) for f in funcs) + '\n')
json.dump(funcs, open(pref + '.json', 'w'))
open(pref + '.dur', 'w').write('\n'.join('%s %.1f' % (f['name'], f['warm_ms']) for f in funcs) + '\n')
print('top %d of %d functions; captured %d invocations (%.1f%% of all); w[0]=%.3f w[-1]=%.4f; warm_ms %.1f..%.1f'
      % (n, len(cnt), tot, 100 * tot / sum(cnt.values()), funcs[0]['weight'], funcs[-1]['weight'],
         min(f['warm_ms'] for f in funcs), max(f['warm_ms'] for f in funcs)))
