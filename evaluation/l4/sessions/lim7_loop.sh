#!/bin/bash
# The L4 scheduler beyond 24,000 calls/s, 5 repetitions, alternating the order of the rates.
set -e
cd /root/rt/pw
export PREVUS=${PREVUS:-3000} MAXVUS=${MAXVUS:-12000}
for rep in 1 2 3 4 5; do
  rates="${LIMRATES:-28000 32000 40000 48000 56000 64000}"
  [ $((rep % 2)) = 0 ] && rates=$(echo $rates | tr " " "\n" | tac | paste -sd" ")
  for r in $rates; do
    RATE=$r NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run lim7_$r evaluation/l4/harness/arms/lim7.txt 1 $rep
  done
done
