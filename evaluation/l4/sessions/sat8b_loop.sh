#!/bin/bash
# Saturation retest with a client CPU steal check: the L4 default at 8,000-32,000 calls/s, Hiku's proxy with one
# connection per call at 8,000-16,000 and with kept-open connections at 12,000-16,000, 5 repetitions.
# A run whose client shows >= 10 % mean steal (or that has no k6 summary) is moved to sat8_stolen and repeated
# once after 1 min; the second attempt stays whatever its steal (steal comes with the load itself, see n12 run 1). Rates and arms alternate their order.
set -e
cd /root/rt/pw
A=/root/rt/prework/sat8_arms R=results/l4 S=results/l4/sat8_stolen
mkdir -p $S
steal() { awk '/%steal/ {for (i=1;i<=NF;i++) if ($i=="%steal") c=i} / all / && !/Average/ && c {s+=$c; n++} END {if (n) printf "%.1f", s/n; else print 99}' "$1"; }
one() {   # rate arm rep
  local c=sat8_$1 d=$R/sat8_$1/${2}_r$3 st
  for t in 1 2; do
    local vus="PREVUS=2000 MAXVUS=10000"; [ $1 -gt 24000 ] && vus="PREVUS=3000 MAXVUS=12000"
    env $vus RATE=$1 NOKA=1 WARM=2 COLD=0 KEEP=600 DUR=60s bash evaluation/l4/harness/pool.sh run $c $A/$2.txt 1 $3
    st=$(steal $d/client.mpstat 2>/dev/null) || st=99
    [ -f $d/summary.json ] || st=99
    echo "$1,$2,$3,$t,$st" >> $R/sat8_steal.csv
    echo "  client steal $st % (attempt $t)"
    awk -v s=$st 'BEGIN {exit !(s >= 10)}' || return 0
    [ $t = 2 ] && return 0
    mkdir -p $S/$c && mv $d $S/$c/${2}_r$3_b$t
    sed -i "/^$2,$3,/d" $R/$c/runs.csv 2>/dev/null || true
    sleep 60
  done
}
for rep in 1 2 3 4 5; do
  rates="8000 12000 16000 24000 32000"
  [ $((rep % 2)) = 0 ] && rates="32000 24000 16000 12000 8000"
  for r in $rates; do
    arms=""
    case $r in
      8000) arms="l4-ord-least l7-pull" ;;
      12000) arms="l7-pull l7-pull-ka" ;;
      16000) arms="l4-ord-least l7-pull l7-pull-ka" ;;
      *) arms="l4-ord-least" ;;
    esac
    [ $((rep % 2)) = 0 ] && arms=$(echo $arms | tr " " "\n" | tac | paste -sd" ")
    for a in $arms; do one $r $a $rep; done
  done
done
