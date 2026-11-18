#!/bin/bash
set -e
cd /root/rt/pw
for rep in 1 2; do
  rates="8000 16000"
  [ $rep = 2 ] && rates="16000 8000"
  for r in $rates; do
    RATE=$r NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run gw_$r evaluation/l4/harness/arms/gw.txt 1 $rep
  done
done
