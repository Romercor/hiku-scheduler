#!/bin/bash
set -e
cd /root/rt/pw
for rep in 1 2; do
  rates="8000 16000 24000 28000 32000"
  [ $rep = 2 ] && rates="32000 28000 24000 16000 8000"
  for r in $rates; do
    RATE=$r NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run sat6_$r evaluation/l4/harness/arms/sat6.txt 1 $rep
  done
done
