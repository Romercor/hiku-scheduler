#!/bin/bash
# The whole path behind an nginx gateway, 5 rounds: gateway (client CPU), scheduler (idle-priority counter
# and irq trace) and workers, Hiku with kept-open connections against L4 with one connection per call.
set -e
cd /root/rt/pw
export MODES="hog trace" CALWAIT=${CALWAIT:-15} PREVUS=${PREVUS:-400} MAXVUS=${MAXVUS:-4000}
export CALARMS="gwl7 gw-l7 l7 pull-based 8 GW=l7; gwl4 gw-l4 l4 ordered+least-loaded 8 GW=l4"
export CONDS_ENV="gw_4000 1 4000 gwl7,gwl4; gw_8000 1 8000 gwl7,gwl4; gw_12000 1 12000 gwl7,gwl4; gw_16000 1 16000 gwl7,gwl4"
bash evaluation/l4/harness/cal.sh gw7 5
