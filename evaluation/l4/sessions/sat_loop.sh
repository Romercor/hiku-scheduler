#!/bin/bash
# Two repetitions of the saturation steps; ascending rates in repetition 1, descending in repetition 2.
set -e
cd /root/rt/pw
for rep in 1 2; do
  rates="4000 8000 12000 16000 20000 24000"
  [ $rep = 2 ] && rates="24000 20000 16000 12000 8000 4000"
  for r in $rates; do
    RATE=$r NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run sat5_$r evaluation/l4/harness/arms/sat5.txt 1 $rep
  done
done
