#!/usr/bin/bash
# Measures what ingesting availability signals costs the scheduler at each datagram rate, by the
# kernel's own accounting of the XDP program. Needs matrix.sh prep first.
# Why: the signals are the price of pulling; the real workers are stopped, so every signal counted
# came from sigflood.go and the rate is known.
# usage: sigcost.sh <campaign> <pass> <rate_pps>...
#   env: SECS (30) PAIRS_W (100 workers) PAIRS_F (40 functions)
set -e
. "$(dirname "$0")/lib.sh"
cd "$REPO"
[ $# -ge 3 ] || usage
SCHED=${SPUB[0]} SCHED_INT=${SPRV[0]} CLIENT=${CL[0]}
SECS=${SECS:-30} PAIRS_W=${PAIRS_W:-100} PAIRS_F=${PAIRS_F:-40}
camp=$1 pass=$2; shift 2
d="$OUT/$camp"; mkdir -p "$d"
build() {   # idle_map size
  sshx "$SCHED" "sudo pkill -x hiku; cd ~/hiku-src && IDLE_MAX=$1 bash scripts/setup_l4.sh >/dev/null 2>&1"
}

(cd evaluation/l4 && CGO_ENABLED=0 go build -o /tmp/sigflood sigflood.go)
scpx /tmp/sigflood ubuntu@"$CLIENT":~/sigflood
stop_workers
sshx "$SCHED" "command -v bpftool >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq linux-tools-\$(uname -r) >/dev/null 2>&1; sudo sysctl -qw kernel.bpf_stats_enabled=1"
build $((PAIRS_W * PAIRS_F * 2))
for rate in "$@"; do
  sshx "$SCHED" "bash ~/start_sched.sh l4 weighted-random+random; sudo pkill -x mpstat" > /dev/null
  sshx "$SCHED" "sleep 3; mpstat -P ALL $((SECS - 6)) 1 | grep Average" > "$d/mpstat_${pass}_$rate.txt" &
  sent=$(sshx "$CLIENT" "./sigflood $SCHED_INT $rate $SECS $PAIRS_W $PAIRS_F 8" | grep -o '= [0-9]*' | tr -d '= ')
  wait
  sshx "$SCHED" "sleep 3; head -2 /tmp/sched.log; tail -1 /tmp/sched.log; sudo bpftool prog show name availability" > "$d/sched_${pass}_$rate.txt"
  python3 "$H/sigcost_row.py" "$d" "$pass" "$rate" "$sent" "$SECS" "$((PAIRS_W * PAIRS_F))"
done
sshx "$SCHED" "sudo pkill -x mpstat; sudo sysctl -qw kernel.bpf_stats_enabled=0" || true
build 4096
