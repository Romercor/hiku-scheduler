#!/bin/bash
# Session n7b after n10: the CPU rounds (cal7) and the gateway balance (gw7) that n7 did not finish.
cd /root/rt/pw
until [ -e /root/rt/prework/n10.done ]; do sleep 60; done
for a in $(seq 1 36); do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n7b.steps > /root/rt/prework/n7b_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n7b_try$a.log && break
  grep -q "cal7_loop" /root/rt/prework/n7b_try$a.log && break
  [ -e /root/rt/prework/stop7b ] && break
  sleep 1200
done
echo ALL DONE $(date) >> /root/rt/prework/n7b.done
