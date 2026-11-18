#!/bin/bash
cd /root/rt/pw
bash evaluation/l4/harness/chain.sh /root/rt/prework/n2.steps > /root/rt/prework/n2.log 2>&1
bash evaluation/l4/harness/chain.sh /root/rt/prework/n1.steps > /root/rt/prework/n1.log 2>&1
echo ALL DONE $(date -u +%FT%TZ) >> /root/rt/prework/n1.log
