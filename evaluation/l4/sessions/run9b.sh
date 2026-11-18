#!/bin/bash
# Session n9b after n7b: the n9 campaigns after the agelimit abort (one cluster at a time): up to 3 attempts while it fails before the campaigns start.
cd /root/rt/pw
until [ -e /root/rt/prework/n7b.done ]; do sleep 60; done
export RELOAD_MS=3600000
for a in $(seq 1 36); do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n9b.steps > /root/rt/prework/n9b_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n9b_try$a.log && break
  grep -q "run agelimit_ibm9b" /root/rt/prework/n9b_try$a.log && break
  [ -e /root/rt/prework/stop9b ] && break
  sleep 1200
done
echo ALL DONE $(date) >> /root/rt/prework/n9b.done
