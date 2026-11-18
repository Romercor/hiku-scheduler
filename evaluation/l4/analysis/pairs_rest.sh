# Summaries and paired differences of the other reruns next to the earlier (reload on) campaign of the same
# experiment from release thesis-v1. Run merge.py first. usage: bash evaluation/l4/analysis/pairs_rest.sh
P="python3 evaluation/l4/harness/paired.py"; S="python3 evaluation/l4/harness/summary.py"
M=throughput,p50,p95,p99,cold_pct,fail_pct
N=results/l4; G=results/merged; O=results/l4
sec() { echo; echo "######## $1"; }
sec rq3_ibm8; $S $N/rq3_ibm8
for a in l4-wr-least l4-p2c-least l4-jsq-least l4-ord-bounded l4-ord-random l4-ord-hashed l4-ord-hashed2 l4-p2c-hashed l4-p2c-hashed2 l4-ord-least-port l7-pull; do $P $N/rq3_ibm8 $a l4-ord-least $M; done
sec rq3_orig; $S $O/rq3
sec conn3_ibm9; $S $N/conn3_ibm9
for pr in "l4-ka l4-x1" "l4-close2 l4-x1" "l4-close5 l4-x1" "l4-busy l4-x1" "l7-pull-ka l4-x1" "l7-pull-ka l4-ka" "l4-wr-ka l4-ka" "l7-pullord-ka l7-pull-ka"; do $P $N/conn3_ibm9 $pr $M; done
sec conn3_orig; $S $O/conn3
sec loss4_ibm9; $S $N/loss4_ibm9; $P $N/loss4_ibm9 l4-loss l4-noloss $M; $P $N/loss4_ibm9 l4-loss-r500 l4-noloss $M
sec loss4_orig; $S $O/loss4
sec pad4_ibm9; $S $N/pad4_ibm9; $P $N/pad4_ibm9 l4-pad100k l4-pad0 $M; $P $N/pad4_ibm9 l4-pad1m l4-pad0 $M
sec pad4c_orig; $S $O/pad4c
sec agelimit_ibm9b; $S $N/agelimit_ibm9b; $P $N/agelimit_ibm9b l4-kill l7-pull-kill $M
sec agelimit_orig; $S $O/agelimit
sec multi3_ibm10; $S $G/multi3_ibm10
for pr in "c10-s2 c10-s1" "c10-s4 c10-s1" "c0-s4 c0-s1" "c50-s4 c50-s1" "wr-s4 wr-s1" "x15-s4 x15-s1" "c0-s4 c10-s4" "c50-s4 c10-s4"; do $P $G/multi3_ibm10 $pr $M; done
sec multi3_orig; $S $O/multi3
sec skew3_9b; $S $N/skew3_9b; $P $N/skew3_9b l4-ord-least l7-pull $M; $P $N/skew3_9b l7-pullord l7-pull $M
sec skew3_orig; $S $O/skew3
sec top_9b; $S $N/top_9b; $P $N/top_9b l4-ord-least l7-pull $M; $P $N/top_9b l7-pullord l7-pull $M
sec open3_9b; $S $N/open3_9b
for pr in "l4-ord-least-o210 l7-pull-o210" "l7-pullord-o210 l7-pull-o210" "l4-ord-least-o210n l7-pull-o210n" "l7-pullord-o210n l7-pull-o210n"; do $P $N/open3_9b $pr $M; done
sec open3_orig; $S $O/open3
