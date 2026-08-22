# Synthetic function table with Zipf popularity (the skew real Azure/IBM/Huawei traces
# have, which stresses locality/load balancing). A real-trace adapter can emit the same
# two files: <pref>.funcs ('name:port' per line, for the L4 loader) and <pref>.json
# ([{name,port,weight}], for the k6 driver).
# args: n_funcs [zipf_s base_port out_prefix]
import sys, json
n = int(sys.argv[1])
s = float(sys.argv[2]) if len(sys.argv) > 2 else 1.1
base = int(sys.argv[3]) if len(sys.argv) > 3 else 5100
pref = sys.argv[4] if len(sys.argv) > 4 else 'trace'

funcs = [{'name': 'fn%03d' % i, 'port': base + i, 'weight': 1.0 / ((i + 1) ** s)} for i in range(n)]
tot = sum(f['weight'] for f in funcs)
for f in funcs:
    f['weight'] /= tot

open(pref + '.funcs', 'w').write('\n'.join('%s:%d' % (f['name'], f['port']) for f in funcs) + '\n')
json.dump(funcs, open(pref + '.json', 'w'))
print('wrote %d functions, ports %d..%d, top weight %.3f' % (n, base, base + n - 1, funcs[0]['weight']))
