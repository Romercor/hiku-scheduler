# Builds the trace.js function table from a popularity file: the n most popular functions, renormalised.
# Why: they get the names and ports of the paper's function set, so the configs of mkconf.py apply.
# args: probabilities_json n_copies out_json
import json, sys

BENCH = ["chameleon", "dd", "float_operation", "gzip_compression",
         "json_dumps_loads", "linpack", "matmul", "pyaes"]
names = ["%s-%d" % (b, c) for c in range(int(sys.argv[2])) for b in BENCH]
p = sorted((v["probability"] for v in json.load(open(sys.argv[1])).values()), reverse=True)[:len(names)]
json.dump([{"name": n, "port": 5100 + i, "weight": w / sum(p)} for i, (n, w) in enumerate(zip(names, p))],
          open(sys.argv[3], "w"))
