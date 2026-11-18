#!/bin/bash
# Session n7 with up to 3 attempts while the cluster fails before the go signal (speed gate, setup).
cd /root/rt/pw
for a in $(seq 6 41); do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n7.steps > /root/rt/prework/n7_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n7_try$a.log && break
  grep -q "sat7_loop" /root/rt/prework/n7_try$a.log && break
  [ -e /root/rt/prework/stop7 ] && break
  sleep 1200
done
echo ALL DONE $(date) >> /root/rt/prework/n7.done
