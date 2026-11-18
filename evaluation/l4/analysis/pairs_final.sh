# Summary and paired differences of the comparison with Hiku under the paper load and the replay.
# Run merge.py first. usage: bash evaluation/l4/analysis/pairs_final.sh
P=evaluation/l4/harness/paired.py
M=throughput,p50,p95,p99,cold_pct,fail_pct
for c in results/l4/final_paper8 results/merged/final_ibm8; do
  echo "######## $c"; python3 evaluation/l4/harness/summary.py $c
  for pr in "l4-ord-least l7-pull" "l7-pullord l7-pull" "l4-ord-least l7-pullord" "l4-scan l7-pull" "l7-random l7-pull" "l7-leastconn l7-pull" "l7-chbl l7-pull" "l4-ord-bounded l4-ord-least"; do python3 $P $c $pr $M; done
done
