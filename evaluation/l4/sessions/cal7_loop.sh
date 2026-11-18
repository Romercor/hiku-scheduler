#!/bin/bash
# CPU of both schedulers at high rates: idle-priority counter (upper estimate) and irq trace (lower bound).
set -e
cd /root/rt/pw
export MODES="hog trace" CALWAIT=${CALWAIT:-15} PREVUS=${PREVUS:-400} MAXVUS=${MAXVUS:-4000}
export CONDS_ENV="${CALCONDS:-noka_8000 1 8000; noka_16000 1 16000; ka_16000 0 16000 l7; noka_24000 1 24000 l4; noka_32000 1 32000 l4; noka_48000 1 48000 l4}"
bash evaluation/l4/harness/cal.sh cal7 5
