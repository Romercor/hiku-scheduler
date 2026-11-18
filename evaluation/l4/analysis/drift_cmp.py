# Per arm and repetition, p95, p99 and cold starts of final_ibm8 against rq3_ibm8 (same windows, later cluster).
import csv
B = 'results/l4/'
def load(c):
    return {(list(x.values())[0], list(x.values())[1]): x for x in csv.DictReader(open(B + c + '/runs.csv'))}
a, b = load('final_ibm8'), load('rq3_ibm8')
print('arm rep | final_ibm8 p95 p99 cold | rq3_ibm8 p95 p99 cold')
for k in sorted(set(a) & set(b)):
    x, y = a[k], b[k]
    print(k[0], k[1], '|', x['p95'], x['p99'], x['cold_pct'], '|', y['p95'], y['p99'], y['cold_pct'])
