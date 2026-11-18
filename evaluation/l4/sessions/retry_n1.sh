#!/bin/bash
until grep -q "ALL DONE" /root/rt/prework/n3.log 2>/dev/null; do sleep 60; done
cd /root/rt/pw
for a in 1 2 3; do
  bash evaluation/l4/harness/chain.sh /root/rt/prework/n1.steps > /root/rt/prework/n1_try$a.log 2>&1
  grep -q "SESSION DONE" /root/rt/prework/n1_try$a.log && break
  grep -q "STEP FAILED" /root/rt/prework/n1_try$a.log && ! grep -q "matrix.sh run" /root/rt/prework/n1_try$a.log || break
  sleep 600
done
echo ALL DONE $(date -u +%FT%TZ) >> /root/rt/prework/n1_retry.done
