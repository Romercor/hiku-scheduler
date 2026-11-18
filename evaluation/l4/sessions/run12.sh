#!/bin/bash
# Session n12: saturation retest with the client steal check. Retries the whole session while it fails
# before the loop starts (gate, setup), 20 min apart.
cd /root/rt/pw
for a in $(seq 1 12); do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n12.steps > /root/rt/prework/n12_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n12_try$a.log && break
  grep -q "sat8_loop" /root/rt/prework/n12_try$a.log && break
  [ -e /root/rt/prework/stop12 ] && break
  sleep 1200
done
echo ALL DONE $(date) >> /root/rt/prework/n12.done
