#!/bin/bash
until grep -q "ALL DONE" /root/rt/prework/n1.log 2>/dev/null; do sleep 60; done
cd /root/rt/pw
bash evaluation/l4/harness/chain.sh /root/rt/prework/n3.steps > /root/rt/prework/n3.log 2>&1
echo ALL DONE $(date -u +%FT%TZ) >> /root/rt/prework/n3.log
