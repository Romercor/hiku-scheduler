#!/bin/bash
# usage: pilot_ladder.sh <session>   writes /root/rt/prework/replay_mean, exits 1 if no mean passes
cd /root/rt/pw
s=$1
for m in 80 70 60 50; do
  printf 'l7-pull l7 pull-based - NOKA=1,REPLAY=replay_ibm%s_{r}.json\nl4-ord-least l4 ordered+least-loaded - NOKA=1,REPLAY=replay_ibm%s_{r}.json\n' $m $m > /tmp/pilot_ladder.txt
  for r in 2 5; do bash evaluation/l4/harness/matrix.sh run pilot_ibm${s}_m$m /tmp/pilot_ladder.txt 1 $r; done
  if python3 /root/rt/prework/gate_replay.py results/l4/pilot_ibm${s}_m$m | grep -qx 1; then
    echo $m > /root/rt/prework/replay_mean; echo "replay mean $m calls/s"; exit 0
  fi
  echo "mean $m too high"
done
exit 1
