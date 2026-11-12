# The layer remainder over campaigns: L4 default minus Hiku with the ordered strategy, cold starts,
# per pair, in every campaign that compares the two layers with the same strategy. open3 leaves out
# repetition 5 of the ramped arms, whose Hiku pull-ordered run collapsed.
# Why: the thesis counts the pairs with a positive remainder over these campaigns.
# args: results_dir (results/l4)
import os, statistics as st, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paired import load

PAIRS = [("final3", "l4-ord-least", "l7-pullord", ()),
         ("skew3", "l4-ord-least", "l7-pullord", ()),
         ("conn3", "l4-x1", "l7-pullord-ka", ()),
         ("open3", "l4-ord-least-o210", "l7-pullord-o210", (5,)),
         ("p15_open", "l4-ord-least-o175", "l7-pullord-o175", ()),
         ("p15_open", "l4-ord-least-o210", "l7-pullord-o210", ())]
pos = tot = 0
for camp, a, b, skip in PAIRS:
    r = load(os.path.join(sys.argv[1], camp))
    x = [float(r[a][k]["cold_pct"]) - float(r[b][k]["cold_pct"]) for k in sorted(set(r[a]) & set(r[b])) if k not in skip]
    pos, tot = pos + sum(v > 0 for v in x), tot + len(x)
    print("  %-9s %-18s - %-16s %+.2f pp, positive %d/%d" % (camp, a, b, st.mean(x), sum(v > 0 for v in x), len(x)))
print("positive in %d of %d pairs" % (pos, tot))
