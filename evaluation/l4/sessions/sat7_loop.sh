#!/bin/bash
# Saturation, 5 repetitions: rates ascending in odd repetitions, descending in even ones.
set -e
cd /root/rt/pw
export PREVUS=${PREVUS:-2000} MAXVUS=${MAXVUS:-10000}
for rep in 1 2 3 4 5; do
  rates="4000 8000 12000 16000 20000 24000"
  [ $((rep % 2)) = 0 ] && rates="24000 20000 16000 12000 8000 4000"
  for r in $rates; do
    RATE=$r NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run sat7_$r evaluation/l4/harness/arms/sat5.txt 1 $rep
  done
done
