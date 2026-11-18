#!/bin/bash
# Session n10 after n9 (one cluster at a time): up to 3 attempts while it fails before the campaigns start.
cd /root/rt/pw
until [ -e /root/rt/prework/n9.done ]; do sleep 60; done
export RELOAD_MS=3600000
for a in $(seq 1 36); do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n10.steps > /root/rt/prework/n10_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n10_try$a.log && break
  grep -q "run multi3_ibm10" /root/rt/prework/n10_try$a.log && break
  [ -e /root/rt/prework/stop10 ] && break
  sleep 1200
done
echo ALL DONE $(date) >> /root/rt/prework/n10.done
